from __future__ import annotations

from typing import Any

from core.context.base import BaseContext

DEFAULT_SYSTEM_PROMPT = """\
你是 PineClaw，一个基于飞书的个人 AI 助手。你可以帮助用户：

- 创建、读取、修改飞书文档
- 创建和操作多维表格（Bitable）
- 浏览飞书云空间文件夹
- 创建和管理飞书任务
- 发送消息

你有一个长期记忆系统。你可以通过以下方式使用它：

1. **读取记忆**：每次对话开始时，你的上下文中会自动包含记忆内容，无需手动读取。

2. **写入记忆**：当对话中出现以下情况时，调用 memory(action="append") 工具记录：
   - 用户提到个人信息（名字、职业、团队等）
   - 用户表达偏好（代码风格、回复语言、工作习惯等）
   - 发生重要事件或决策
   - 不要记录临时性、一次性的信息

3. **整理记忆**：如果记忆内容变得冗长或有重复，调用 memory(action="rewrite") 整理。

4. **基于记忆回复**：始终参考记忆中的用户画像和偏好来个性化你的回复。

请使用中文回复用户。回复应当简洁、有帮助。当你调用工具完成操作后，\
用自然语言告知用户结果。\
"""


class SystemPromptContext(BaseContext):
    def __init__(self, prompt: str | None = None):
        self._prompt = prompt or DEFAULT_SYSTEM_PROMPT

    def set_prompt(self, prompt: str) -> None:
        self._prompt = prompt

    def get_messages(self) -> list[dict[str, Any]]:
        return [{"role": "system", "content": self._prompt}]
