"""天工锻造令工具的执行逻辑。

如意通过此工具向天工下达锻造令——生成一份 Markdown 文件写入
.heartclaw/tiangong/orders/pending/ 目录，天工定时巡查后开始锻造。
"""

from __future__ import annotations

import platform
import re
from datetime import datetime
from typing import Any

from config.settings import get_heartclaw_home
from core.tool.types import ToolResult
from utils.logger import get_logger

logger = get_logger("tool.tiangong_evolve")


async def tiangong_evolve_handler(args: dict[str, Any]) -> ToolResult:
    """生成锻造令并写入 pending 目录。"""
    task: str = args.get("task", "").strip()
    if not task:
        return ToolResult.fail("task is required: 需要描述锻造什么工具")

    tool_name: str = args.get("tool_name", "").strip()
    if not tool_name:
        tool_name = _derive_tool_name(task)

    now = datetime.now()
    filename = f"{now.strftime('%Y%m%d-%H%M%S')}-{tool_name}.md"

    requester_env = _detect_runtime_env()
    target_env = _build_target_env(args, requester_env)
    order_content = _build_order(tool_name, task, now, requester_env, target_env)

    pending_dir = get_heartclaw_home() / "tiangong" / "orders" / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    order_path = pending_dir / filename

    try:
        order_path.write_text(order_content, encoding="utf-8")
    except OSError as e:
        logger.error("Failed to write forge order: %s", e)
        return ToolResult.fail(f"写入锻造令失败: {e}")

    logger.info("Forge order created: %s", order_path)
    return ToolResult.ok(
        f"锻造令已下达：{filename}\n"
        f"天工将在下次巡查时开始锻造 {tool_name}。\n"
        f"锻造令位置：{order_path}"
    )


def render_evolve_result(result: ToolResult) -> str:
    """格式化锻造令结果供 LLM 阅读。"""
    if not result.success:
        return f"Error: {result.error}"
    return str(result.data)


def _derive_tool_name(task: str) -> str:
    """从任务描述中提取一个简短的工具名。

    取前 30 个字符，替换非字母数字字符为短横线，转小写。
    """
    short = task[:30]
    name = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", short).strip("-").lower()
    return name or "new-tool"


def _build_order(
    tool_name: str,
    task: str,
    now: datetime,
    requester_env: dict[str, str],
    target_env: dict[str, str],
) -> str:
    """构建锻造令 Markdown 内容。"""
    same_target = (
        requester_env["os"] == target_env["os"]
        and requester_env["arch"] == target_env["arch"]
    )
    target_note = target_env.get("note", "")
    target_note_line = f"- 说明：{target_note}\n" if target_note else ""

    return (
        f"# 锻造令：{tool_name}\n"
        f"\n"
        f"## 需求描述\n"
        f"\n"
        f"{task}\n"
        f"\n"
        f"## 请求方运行环境（如意）\n"
        f"\n"
        f"- 操作系统：{requester_env['os']}\n"
        f"- 架构：{requester_env['arch']}\n"
        f"- Python：{requester_env['python_version']}\n"
        f"- 平台信息：{requester_env['platform']}\n"
        f"- Rust 目标三元组参考：{requester_env['rust_target']}\n"
        f"\n"
        f"## 目标运行环境（交付目标）\n"
        f"\n"
        f"- 操作系统：{target_env['os']}\n"
        f"- 架构：{target_env['arch']}\n"
        f"- Rust 目标三元组参考：{target_env['rust_target']}\n"
        f"{target_note_line}"
        f"- 与如意环境一致：{'是' if same_target else '否'}\n"
        f"\n"
        f"## 构建提示\n"
        f"\n"
        f"- 请优先确认交付二进制能在目标运行环境直接执行。\n"
        f"- 若目标环境与当前构建环境不一致，请先判断是否需要交叉编译，"
        f"无法保证兼容时需在结果中明确说明。\n"
        f"\n"
        f"## 元信息\n"
        f"\n"
        f"- 创建时间：{now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- 请求方：如意\n"
        f"- 优先级：normal\n"
    )


def _build_target_env(
    args: dict[str, Any],
    requester_env: dict[str, str],
) -> dict[str, str]:
    target_os_raw = _optional_str(args.get("target_os"))
    target_arch_raw = _optional_str(args.get("target_arch"))
    target_note = _optional_str(args.get("target_env_note"))

    target_os = _normalize_os(target_os_raw) if target_os_raw else requester_env["os"]
    target_arch = (
        _normalize_arch(target_arch_raw)
        if target_arch_raw
        else requester_env["arch"]
    )

    return {
        "os": target_os,
        "arch": target_arch,
        "rust_target": _rust_target_triple(target_os, target_arch),
        "note": target_note,
    }


def _detect_runtime_env() -> dict[str, str]:
    os_name = _normalize_os(platform.system())
    arch = _normalize_arch(platform.machine())
    return {
        "os": os_name,
        "arch": arch,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "rust_target": _rust_target_triple(os_name, arch),
    }


def _normalize_os(raw: str) -> str:
    value = raw.strip().lower()
    mapping = {
        "darwin": "macos",
        "mac": "macos",
        "macos": "macos",
        "linux": "linux",
        "windows": "windows",
        "win32": "windows",
    }
    return mapping.get(value, value or "unknown")


def _normalize_arch(raw: str) -> str:
    value = raw.strip().lower()
    mapping = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
    }
    return mapping.get(value, value or "unknown")


def _rust_target_triple(os_name: str, arch: str) -> str:
    mapping = {
        ("linux", "x86_64"): "x86_64-unknown-linux-gnu",
        ("linux", "aarch64"): "aarch64-unknown-linux-gnu",
        ("macos", "x86_64"): "x86_64-apple-darwin",
        ("macos", "aarch64"): "aarch64-apple-darwin",
        ("windows", "x86_64"): "x86_64-pc-windows-msvc",
        ("windows", "aarch64"): "aarch64-pc-windows-msvc",
    }
    return mapping.get((os_name, arch), "unknown")


def _optional_str(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""
