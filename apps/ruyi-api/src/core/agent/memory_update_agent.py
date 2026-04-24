"""Dedicated LOW-model agents for daily long-term memory updates.

Each agent is a thin wrapper around a single LLM call (not a full Agent
with tool loops).  It reads today's short-term records plus the current
content of its assigned long-term memory file, then decides whether an
update is needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.prompts.memory_update import MEMORY_UPDATE_PROMPTS
from utils.logger import get_logger

if TYPE_CHECKING:
    from core.llm.services.base import BaseLLMService
    from storage.memory_store import LocalMemoryStore

logger = get_logger("memory_update_agent")

_NO_UPDATE_MARKERS = {"无需更新", "无需更新。", "不需要更新", "无变化"}


async def run_single_update(
    llm: BaseLLMService,
    memory_store: LocalMemoryStore,
    file_name: str,
    daily_text: str,
) -> tuple[str, bool, str]:
    """Run a single memory update agent for one file.

    Returns (file_name, updated, detail_message).
    """
    system_prompt = MEMORY_UPDATE_PROMPTS.get(file_name, "")
    if not system_prompt:
        return file_name, False, "no prompt defined"

    current_content = memory_store.read_file(file_name)

    user_message = (
        f"## 当前「{file_name}」文件内容\n\n"
        f"{current_content if current_content.strip() else '(空)'}\n\n"
        f"## 今天的对话记录\n\n{daily_text}\n\n"
        f"请分析对话记录，决定是否需要更新文件。"
        f"如果需要更新，直接输出更新后的完整文件内容（保留所有已有内容+新增内容）。"
        f"如果不需要更新，只回复「无需更新」。"
    )

    try:
        response = await llm.simple_chat(user_message, system_prompt=system_prompt)
    except Exception as e:
        logger.error("LLM call failed for %s: %s", file_name, e)
        return file_name, False, f"llm_error: {e}"

    response_stripped = response.strip()

    if response_stripped in _NO_UPDATE_MARKERS:
        return file_name, False, "no update needed"

    success, msg = memory_store.safe_write(file_name, response_stripped)
    if success:
        logger.info("Updated %s: %s", file_name, msg)
        return file_name, True, msg
    else:
        logger.warning("Update blocked for %s: %s", file_name, msg)
        return file_name, False, msg
