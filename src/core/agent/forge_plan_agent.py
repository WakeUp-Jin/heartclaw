"""锻造计划自省 Agent — 分析短期记忆中的重复工作流，提出锻造建议。

纯 Agent 逻辑：接收数据、调用 LLM、返回结构化结果。
不关心何时被调用、结果写到哪里（由 scheduler 层负责）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, TYPE_CHECKING

from core.prompts.forge import FORGE_PLAN_SYSTEM_PROMPT
from utils.logger import get_logger

if TYPE_CHECKING:
    from core.llm.services.base import BaseLLMService
    from storage.short_memory_store import ShortMemoryStore

logger = get_logger("forge_plan_agent")

_NO_PROPOSAL_MARKERS = {"无需锻造", "无需锻造。", "没有需要锻造的工具", "无"}


@dataclass
class ForgePlanResult:
    """自省分析的结果。"""
    has_proposal: bool
    tool_name: str = ""
    plan_content: str = ""
    reason: str = ""


async def run_forge_plan_analysis(
    llm: BaseLLMService,
    short_store: ShortMemoryStore,
    heartclaw_home: Path,
    recent_days: int = 7,
) -> ForgePlanResult:
    """分析近期短期记忆，判断是否有值得锻造的工作流。

    Parameters
    ----------
    llm : BaseLLMService
        LOW-tier LLM 服务实例。
    short_store : ShortMemoryStore
        短期记忆存储。
    heartclaw_home : Path
        ~/.heartclaw 根目录。
    recent_days : int
        回溯天数，默认 7 天。

    Returns
    -------
    ForgePlanResult
        包含是否有提议、工具名、计划内容。
    """
    daily_text = _load_recent_records(short_store, recent_days)
    if not daily_text.strip():
        return ForgePlanResult(has_proposal=False, reason="no_records")

    existing_tools_text = _collect_existing_tools(heartclaw_home)

    user_message = (
        f"## 近 {recent_days} 天的用户对话记录\n\n"
        f"{daily_text}\n\n"
        f"## 已有工具列表（不得重复提议）\n\n"
        f"{existing_tools_text if existing_tools_text.strip() else '(暂无已有工具)'}\n\n"
        f"请分析对话记录，判断是否有值得锻造为 CLI 工具的重复工作流。"
    )

    try:
        response = await llm.simple_chat(user_message, system_prompt=FORGE_PLAN_SYSTEM_PROMPT)
    except Exception as e:
        logger.error("LLM call failed for forge plan analysis: %s", e)
        return ForgePlanResult(has_proposal=False, reason=f"llm_error: {e}")

    response_stripped = response.strip()

    if response_stripped in _NO_PROPOSAL_MARKERS:
        return ForgePlanResult(has_proposal=False, reason="no_proposal")

    tool_name = _extract_tool_name(response_stripped)
    if not tool_name:
        return ForgePlanResult(has_proposal=False, reason="parse_failed")

    plan_content = _clean_plan_content(response_stripped)

    logger.info("Forge plan proposed: %s", tool_name)
    return ForgePlanResult(
        has_proposal=True,
        tool_name=tool_name,
        plan_content=plan_content,
    )


# ------------------------------------------------------------------
# 数据收集
# ------------------------------------------------------------------

def _load_recent_records(
    short_store: ShortMemoryStore,
    recent_days: int,
) -> str:
    """读取近 N 天的短期记忆，转为可读文本。"""
    role_labels = {"user": "用户", "assistant": "助手", "tool": "工具", "system": "系统"}
    all_lines: list[str] = []
    today = date.today()

    for i in range(recent_days):
        d = today - timedelta(days=i)
        records = short_store.load_daily(d)
        if not records:
            continue

        all_lines.append(f"### {d.isoformat()}")
        for item in records:
            role = item.get("role", "?")
            content = item.get("content", "")
            label = role_labels.get(role, role)
            if content:
                truncated = content[:500] + "..." if len(content) > 500 else content
                all_lines.append(f"{label}: {truncated}")
        all_lines.append("")

    return "\n".join(all_lines)


def _collect_existing_tools(heartclaw_home: Path) -> str:
    """从三个来源收集已有工具信息，拼成文本供 LLM 参考。

    来源:
    1. skills/TianGongToolList/SKILL.md — 天工当前可用工具清单
    2. tiangong/forge-logs/*.md — 已锻造工具的记录
    3. tiangong/orders/done/*.md — 已完成的锻造令
    """
    sections: list[str] = []

    # 1. TianGongToolList/SKILL.md
    skill_list_path = heartclaw_home / "skills" / "TianGongToolList" / "SKILL.md"
    if skill_list_path.is_file():
        try:
            content = skill_list_path.read_text(encoding="utf-8")
            sections.append(f"### 天工可用工具清单\n\n{content}")
        except OSError:
            pass

    # 2. forge-logs/
    forge_logs_dir = heartclaw_home / "tiangong" / "forge-logs"
    if forge_logs_dir.is_dir():
        log_names: list[str] = []
        for log_file in sorted(forge_logs_dir.glob("*.md")):
            log_names.append(f"- {log_file.stem}")
        if log_names:
            sections.append(
                "### 锻造记录中的工具\n\n" + "\n".join(log_names)
            )

    # 3. orders/done/
    done_dir = heartclaw_home / "tiangong" / "orders" / "done"
    if done_dir.is_dir():
        done_names: list[str] = []
        for done_file in sorted(done_dir.glob("*.md"))[-20:]:
            done_names.append(f"- {done_file.stem}")
        if done_names:
            sections.append(
                "### 已完成的锻造令\n\n" + "\n".join(done_names)
            )

    return "\n\n".join(sections)


# ------------------------------------------------------------------
# 解析 LLM 返回
# ------------------------------------------------------------------

def _extract_tool_name(response: str) -> str:
    """从 LLM 返回中提取 TOOL_NAME 行。"""
    for line in response.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("TOOL_NAME:"):
            name = stripped.split(":", 1)[1].strip()
            if name:
                return name
    return ""


def _clean_plan_content(response: str) -> str:
    """去掉 TOOL_NAME 行，保留锻造计划正文。"""
    lines: list[str] = []
    for line in response.splitlines():
        if line.strip().upper().startswith("TOOL_NAME:"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()
