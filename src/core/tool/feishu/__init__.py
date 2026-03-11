from __future__ import annotations

from typing import TYPE_CHECKING

from core.tool.feishu.message import feishu_message_def, feishu_message_handler
from core.tool.feishu.doc import feishu_doc_def, feishu_doc_handler
from core.tool.feishu.bitable import (
    feishu_bitable_def, feishu_bitable_handler,
    feishu_bitable_record_def, feishu_bitable_record_handler,
)
from core.tool.feishu.drive import feishu_drive_def, feishu_drive_handler
from core.tool.feishu.task import feishu_task_def, feishu_task_handler

if TYPE_CHECKING:
    from core.tool.feishu.client import FeishuClient
    from core.tool.manager import ToolManager


_FEISHU_TOOLS = [
    (feishu_message_def, feishu_message_handler),
    (feishu_doc_def, feishu_doc_handler),
    (feishu_bitable_def, feishu_bitable_handler),
    (feishu_bitable_record_def, feishu_bitable_record_handler),
    (feishu_drive_def, feishu_drive_handler),
    (feishu_task_def, feishu_task_handler),
]


def register_feishu_tools(tool_manager: ToolManager, feishu_client: FeishuClient) -> None:
    """Register all 6 unified Feishu API tools into ToolManager."""
    for definition, handler in _FEISHU_TOOLS:
        tool_manager.register(
            name=definition["name"],
            definition=definition,
            handler=lambda args, h=handler: h(feishu_client, args),
            category="feishu",
        )
