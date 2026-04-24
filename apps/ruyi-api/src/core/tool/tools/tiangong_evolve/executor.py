"""天工锻造令工具的执行逻辑。

如意通过此工具向天工下达锻造令——将模型生成的锻造令 Markdown
写入 .heartclaw/tiangong/orders/pending/ 目录，
天工定时巡查后开始锻造。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from config.settings import get_heartclaw_home
from core.tool.types import ToolResult
from utils.logger import get_logger

logger = get_logger("tool.tiangong_evolve")


async def tiangong_evolve_handler(args: dict[str, Any]) -> ToolResult:
    """将模型生成的锻造令写入 pending 目录。"""
    tool_name: str = args.get("tool_name", "").strip()
    if not tool_name:
        return ToolResult.fail("tool_name is required: 需要指定工具名称")

    content: str = args.get("content", "").strip()
    if not content:
        return ToolResult.fail("content is required: 需要提供锻造令内容")

    now = datetime.now()
    filename = f"{now.strftime('%Y%m%d-%H%M%S')}-{tool_name}.md"

    pending_dir = get_heartclaw_home() / "tiangong" / "orders" / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    order_path = pending_dir / filename

    try:
        order_path.write_text(content, encoding="utf-8")
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
