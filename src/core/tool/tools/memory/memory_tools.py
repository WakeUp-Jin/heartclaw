"""Memory tools -- read / append / rewrite / edit long-term memory files."""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from storage.memory_store import VALID_FILES
from core.tool.tools.memory.edit_memory_tool import edit_memory_def, edit_memory_handler

if TYPE_CHECKING:
    from storage.memory_store import LocalMemoryStore


# ------------------------------------------------------------------
# read_memory
# ------------------------------------------------------------------

read_memory_def: dict[str, Any] = {
    "name": "read_memory",
    "description": "读取指定的长期记忆文件内容。",
    "parameters": {
        "type": "object",
        "properties": {
            "file": {
                "type": "string",
                "enum": sorted(VALID_FILES),
                "description": "要读取的长期记忆文件名",
            },
        },
        "required": ["file"],
    },
}


def _read_memory_handler(memory_store: LocalMemoryStore, args: dict[str, Any]) -> str:
    file_name = args.get("file", "")
    if file_name not in VALID_FILES:
        return json.dumps(
            {"error": f"无效文件: {file_name}，可选: {sorted(VALID_FILES)}"},
            ensure_ascii=False,
        )
    content = memory_store.read_file(file_name)
    if not content.strip():
        return json.dumps(
            {"status": "ok", "content": "(空文件)", "file": file_name},
            ensure_ascii=False,
        )
    return json.dumps(
        {"status": "ok", "content": content, "file": file_name},
        ensure_ascii=False,
    )


# ------------------------------------------------------------------
# memory (append / rewrite)
# ------------------------------------------------------------------

memory_def: dict[str, Any] = {
    "name": "memory",
    "description": (
        "长期记忆操作。"
        "action=append：向指定记忆文件追加内容（需要 file、content）；"
        "action=rewrite：重写指定记忆文件的全部内容（需要 file、content，谨慎使用）。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["append", "rewrite"],
                "description": "操作类型",
            },
            "file": {
                "type": "string",
                "enum": sorted(VALID_FILES),
                "description": "目标长期记忆文件名",
            },
            "content": {
                "type": "string",
                "description": "要追加或覆写的内容，Markdown 格式",
            },
        },
        "required": ["action", "file", "content"],
    },
}


def _handle_append(memory_store: LocalMemoryStore, args: dict[str, Any]) -> str:
    file_name = args.get("file", "")
    content = args.get("content", "")

    if file_name not in VALID_FILES:
        return json.dumps({"error": f"无效文件: {file_name}"}, ensure_ascii=False)

    success = memory_store.append_to_file(file_name, content)
    if success:
        return json.dumps(
            {"status": "ok", "message": f"已追加到 {file_name}"},
            ensure_ascii=False,
        )
    return json.dumps({"status": "failed", "message": "写入失败"}, ensure_ascii=False)


def _handle_rewrite(memory_store: LocalMemoryStore, args: dict[str, Any]) -> str:
    file_name = args.get("file", "")
    content = args.get("content", "")

    if file_name not in VALID_FILES:
        return json.dumps({"error": f"无效文件: {file_name}"}, ensure_ascii=False)

    success, msg = memory_store.safe_write(file_name, content)
    if success:
        return json.dumps(
            {"status": "ok", "message": f"{file_name} 已更新"},
            ensure_ascii=False,
        )
    return json.dumps(
        {"status": "blocked", "message": msg},
        ensure_ascii=False,
    )


_ACTION_MAP = {
    "append": _handle_append,
    "rewrite": _handle_rewrite,
}


def memory_handler(memory_store: LocalMemoryStore, args: dict[str, Any]) -> str:
    action = args.get("action", "")
    handler = _ACTION_MAP.get(action)
    if handler is None:
        return json.dumps({"error": f"Unknown action: {action}"})
    return handler(memory_store, args)


# ------------------------------------------------------------------
# Registration
# ------------------------------------------------------------------

def register_memory_tools(tool_manager: Any, memory_store: LocalMemoryStore) -> None:
    """Register all memory-related tools."""

    async def _memory_handler(args: dict[str, Any]) -> str:
        return memory_handler(memory_store, args)

    async def _read_handler(args: dict[str, Any]) -> str:
        return _read_memory_handler(memory_store, args)

    async def _edit_handler(args: dict[str, Any]) -> str:
        return edit_memory_handler(memory_store, args)

    tool_manager.register_legacy(
        name="memory",
        definition=memory_def,
        handler=_memory_handler,
        category="memory",
    )

    tool_manager.register_legacy(
        name="read_memory",
        definition=read_memory_def,
        handler=_read_handler,
        category="memory",
    )

    tool_manager.register_legacy(
        name="edit_memory",
        definition=edit_memory_def,
        handler=_edit_handler,
        category="memory",
    )
