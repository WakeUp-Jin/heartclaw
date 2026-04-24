"""Memory tools -- read / append / rewrite / edit long-term memory files."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.tool.types import InternalTool, ToolParameterSchema, ToolResult
from storage.memory_store import VALID_FILES
from core.tool.tools.memory.edit_memory_tool import (
    EDIT_MEMORY_DESCRIPTION,
    EditMemoryParameters,
    edit_memory_handler,
)

if TYPE_CHECKING:
    from core.tool.manager import ToolManager
    from storage.memory_store import LocalMemoryStore


# ------------------------------------------------------------------
# read_memory
# ------------------------------------------------------------------

READ_MEMORY_DESCRIPTION = "读取指定的长期记忆文件内容。"

ReadMemoryParameters = ToolParameterSchema(
    type="object",
    properties={
            "file": {
                "type": "string",
                "enum": sorted(VALID_FILES),
                "description": "要读取的长期记忆文件名",
            },
    },
    required=["file"],
)


def _read_memory_handler(
    memory_store: LocalMemoryStore, args: dict[str, str],
) -> ToolResult:
    file_name = args.get("file", "")
    if file_name not in VALID_FILES:
        return ToolResult.fail(
            f"无效文件: {file_name}，可选: {sorted(VALID_FILES)}",
        )
    content = memory_store.read_file(file_name)
    if not content.strip():
        content = "(空文件)"
    return ToolResult.ok({"status": "ok", "content": content, "file": file_name})


# ------------------------------------------------------------------
# memory (append / rewrite)
# ------------------------------------------------------------------

MEMORY_DESCRIPTION = (
    "长期记忆操作。"
    "action=append：向指定记忆文件追加内容（需要 file、content）；"
    "action=rewrite：重写指定记忆文件的全部内容（需要 file、content，谨慎使用）。"
)

MemoryParameters = ToolParameterSchema(
    type="object",
    properties={
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
    required=["action", "file", "content"],
)


def _handle_append(memory_store: LocalMemoryStore, args: dict[str, str]) -> ToolResult:
    file_name = args.get("file", "")
    content = args.get("content", "")

    if file_name not in VALID_FILES:
        return ToolResult.fail(f"无效文件: {file_name}")

    success = memory_store.append_to_file(file_name, content)
    if success:
        return ToolResult.ok({"status": "ok", "message": f"已追加到 {file_name}"})
    return ToolResult.fail("写入失败")


def _handle_rewrite(memory_store: LocalMemoryStore, args: dict[str, str]) -> ToolResult:
    file_name = args.get("file", "")
    content = args.get("content", "")

    if file_name not in VALID_FILES:
        return ToolResult.fail(f"无效文件: {file_name}")

    success, msg = memory_store.safe_write(file_name, content)
    if success:
        return ToolResult.ok({"status": "ok", "message": f"{file_name} 已更新"})
    return ToolResult.fail(msg)


_ACTION_MAP = {
    "append": _handle_append,
    "rewrite": _handle_rewrite,
}


def memory_handler(memory_store: LocalMemoryStore, args: dict[str, str]) -> ToolResult:
    action = args.get("action", "")
    handler = _ACTION_MAP.get(action)
    if handler is None:
        return ToolResult.fail(f"Unknown action: {action}")
    return handler(memory_store, args)


# ------------------------------------------------------------------
# Registration
# ------------------------------------------------------------------

def register_memory_tools(tool_manager: ToolManager, memory_store: LocalMemoryStore) -> None:
    """Register all memory-related tools."""

    async def _memory_handler(args: dict[str, str]) -> ToolResult:
        return memory_handler(memory_store, args)

    async def _read_handler(args: dict[str, str]) -> ToolResult:
        return _read_memory_handler(memory_store, args)

    async def _edit_handler(args: dict[str, str]) -> ToolResult:
        return ToolResult.ok(edit_memory_handler(memory_store, args))

    tool_manager.register(
        InternalTool(
            name="memory",
            description=MEMORY_DESCRIPTION,
            parameters=MemoryParameters,
            handler=_memory_handler,
            category="memory",
        )
    )

    tool_manager.register(
        InternalTool(
            name="read_memory",
            description=READ_MEMORY_DESCRIPTION,
            parameters=ReadMemoryParameters,
            handler=_read_handler,
            category="memory",
            is_read_only=True,
        )
    )

    tool_manager.register(
        InternalTool(
            name="edit_memory",
            description=EDIT_MEMORY_DESCRIPTION,
            parameters=EditMemoryParameters,
            handler=_edit_handler,
            category="memory",
        )
    )
