from __future__ import annotations

import json
from typing import Any

from core.tool.types import InternalTool, ToolResult
from utils.logger import get_logger

logger = get_logger("tool.manager")


class ToolManager:
    """工具注册中心——管理所有 InternalTool 的注册、查询与执行。"""

    def __init__(self) -> None:
        self._tools: dict[str, InternalTool] = {}

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------

    def register(self, tool: InternalTool) -> None:
        """注册一个 InternalTool 对象。"""
        self._tools[tool.name] = tool
        logger.debug("Registered tool: %s [%s]", tool.name, tool.category)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_tool(self, name: str) -> InternalTool | None:
        return self._tools.get(name)

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    async def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        """执行工具，返回 ToolResult。"""
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult.fail(f"Unknown tool: {name}")

        return await tool.handler(args)

    def render(self, name: str, result: ToolResult) -> str:
        """对 ToolResult 做输出格式化，供回写上下文使用。"""
        tool = self._tools.get(name)
        if tool and tool.render_result:
            return tool.render_result(result)

        if not result.success:
            return json.dumps({"error": result.error}, ensure_ascii=False)
        if isinstance(result.data, str):
            return result.data
        return json.dumps(result.data, ensure_ascii=False, default=str)

    # ------------------------------------------------------------------
    # OpenAI function calling 格式输出
    # ------------------------------------------------------------------

    def get_formatted_tools(self) -> list[dict[str, Any]]:
        """返回所有工具的 OpenAI function calling 格式。"""
        return [
            {"type": "function", "function": tool.get_openai_function()}
            for tool in self._tools.values()
        ]
