"""天工反馈重锻工具的执行逻辑。

如意通过此工具向天工反馈工具运行错误——将模型生成的反馈重锻令
Markdown 写入 pending/ 目录，天工巡查后基于历史上下文进行修复。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from config.settings import get_heartclaw_home
from core.tool.types import ToolResult
from utils.logger import get_logger

logger = get_logger("tool.tiangong_feedback")


async def tiangong_feedback_handler(args: dict[str, Any]) -> ToolResult:
    """验证锻造记录存在后，将模型生成的重锻令写入 pending 目录。"""
    tool_name: str = args.get("tool_name", "").strip()
    if not tool_name:
        return ToolResult.fail("tool_name is required: 需要指定工具名称")

    content: str = args.get("content", "").strip()
    if not content:
        return ToolResult.fail("content is required: 需要提供反馈重锻令内容")

    home = get_heartclaw_home()
    forge_log_path = home / "tiangong" / "forge-logs" / f"{tool_name}.md"

    if not forge_log_path.is_file():
        return ToolResult.fail(
            f"未找到 {tool_name} 的锻造记录: {forge_log_path}\n"
            f"请确认工具名称是否正确，或该工具是否已被锻造过。"
        )

    now = datetime.now()
    filename = f"{now.strftime('%Y%m%d-%H%M%S')}-reforge-{tool_name}.md"

    pending_dir = home / "tiangong" / "orders" / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    order_path = pending_dir / filename

    try:
        order_path.write_text(content, encoding="utf-8")
    except OSError as e:
        logger.error("Failed to write reforge order: %s", e)
        return ToolResult.fail(f"写入反馈重锻令失败: {e}")

    logger.info("Reforge order created: %s", order_path)
    return ToolResult.ok(
        f"反馈重锻令已下达：{filename}\n"
        f"天工将在下次巡查时基于历史上下文修复 {tool_name}。\n"
        f"重锻令位置：{order_path}"
    )


def render_feedback_result(result: ToolResult) -> str:
    """格式化反馈重锻结果供 LLM 阅读。"""
    if not result.success:
        return f"Error: {result.error}"
    return str(result.data)
