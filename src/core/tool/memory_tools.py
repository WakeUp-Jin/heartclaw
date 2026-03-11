"""记忆工具 - 合并 append/rewrite 为单一 memory 工具"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from memory.memory_store import MemoryStore


memory_def: dict[str, Any] = {
    "name": "memory",
    "description": (
        "长期记忆操作。"
        "action=append：向记忆追加一条新信息（用户偏好、重要事实等），需要 section 和 content；"
        "action=rewrite：整理和重写整个记忆文件（谨慎使用），需要 content 且必须以 '# PineClaw Memory' 开头。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["append", "rewrite"],
                "description": "操作类型：append=追加记忆, rewrite=重写整个记忆",
            },
            "section": {
                "type": "string",
                "description": "记忆分类，如：用户画像、工作习惯、重要事实、偏好指令（append 时必填）",
            },
            "content": {
                "type": "string",
                "description": "记忆内容，Markdown 格式（必填）",
            },
        },
        "required": ["action", "content"],
    },
}


async def _handle_append(memory_store: MemoryStore, args: dict[str, Any]) -> str:
    section = args.get("section") or "未分类"
    content = args["content"]

    current_text = memory_store.get_memory_text()
    if f"## {section}" in current_text:
        append_text = f"- {content}"
    else:
        append_text = f"\n## {section}\n- {content}"

    success = await memory_store.append(append_text)
    if success:
        return json.dumps({"status": "ok", "message": f"已记住：{content}"}, ensure_ascii=False)
    return json.dumps(
        {"status": "cached", "message": "记忆写入飞书失败，已缓存在本地，将在下次重试"},
        ensure_ascii=False,
    )


async def _handle_rewrite(memory_store: MemoryStore, args: dict[str, Any]) -> str:
    content = args["content"]

    if not content.startswith("# PineClaw Memory"):
        return json.dumps(
            {"error": "记忆内容必须以 '# PineClaw Memory' 开头"},
            ensure_ascii=False,
        )

    success = await memory_store.replace(content)
    if success:
        return json.dumps({"status": "ok", "message": "记忆已整理并更新"}, ensure_ascii=False)
    return json.dumps(
        {"status": "failed", "message": "记忆覆写飞书失败，已回滚"},
        ensure_ascii=False,
    )


_ACTION_MAP = {
    "append": _handle_append,
    "rewrite": _handle_rewrite,
}


async def memory_handler(memory_store: MemoryStore, args: dict[str, Any]) -> str:
    action = args.get("action", "")
    handler = _ACTION_MAP.get(action)
    if handler is None:
        return json.dumps({"error": f"Unknown action: {action}"})
    return await handler(memory_store, args)


def register_memory_tools(tool_manager: Any, memory_store: MemoryStore) -> None:
    """Register the unified memory tool."""
    tool_manager.register(
        name="memory",
        definition=memory_def,
        handler=lambda args: memory_handler(memory_store, args),
        category="memory",
    )
