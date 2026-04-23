"""工具输出裁剪器 —— 控制工具结果写入上下文时的长度。

两层裁剪策略（参考上下文压缩调度文档）：
  第一层: 原始输出超过 MAX_RAW_CHARS 时硬截断，防止撑爆后续 LLM 总结
  第二层: 超过 MAX_RESULT_CHARS 时，保留前 MAX_RESULT_CHARS 字符 + LLM 摘要
"""

from __future__ import annotations

from typing import Callable, Awaitable

from utils.logger import get_logger

logger = get_logger("tool.truncator")

TRUNCATION_PROMPT = (
    "请对以下工具输出内容进行简洁摘要，保留关键信息（文件路径、错误信息、"
    "数据结构、重要数值等），摘要控制在 300 字以内：\n\n"
)


class OutputTruncator:
    """工具输出裁剪器。

    Parameters
    ----------
    max_raw_chars:
        第一层硬截断阈值，超过此长度先截断再做后续处理。
    max_result_chars:
        第二层上限，超过此长度时触发 LLM 摘要。
    """

    def __init__(
        self,
        max_raw_chars: int = 100_000,
        max_result_chars: int = 2_000,
    ) -> None:
        self.max_raw_chars = max_raw_chars
        self.max_result_chars = max_result_chars

    async def truncate(
        self,
        text: str,
        summarize_fn: Callable[[str], Awaitable[str]] | None = None,
    ) -> str:
        """对工具输出执行两层裁剪。

        Parameters
        ----------
        text:
            经过 render_result 格式化后的工具输出字符串。
        summarize_fn:
            LLM 摘要函数（使用 low 模型），为 None 时退化为纯截断。

        Returns
        -------
        裁剪/摘要后的字符串，长度可控。
        """
        if len(text) <= self.max_result_chars:
            return text

        # ── 第一层：硬截断，防止后续 LLM 总结时也被撑爆 ──
        if len(text) > self.max_raw_chars:
            half = self.max_raw_chars // 2
            text = text[:half] + "\n\n... [truncated] ...\n\n" + text[-half:]
            logger.info(
                "第一层裁剪: 原始输出 >%d 字符, 已硬截断至 %d",
                self.max_raw_chars, len(text),
            )

        # ── 第二层：保留前 max_result_chars 字符 + LLM 摘要 ──
        head = text[: self.max_result_chars]

        if summarize_fn is not None:
            try:
                summary = await summarize_fn(TRUNCATION_PROMPT + text)
                result = (
                    f"{head}\n\n"
                    f"... [以上为前 {self.max_result_chars} 字符，以下为 LLM 摘要] ...\n\n"
                    f"{summary}"
                )
                logger.info(
                    "第二层裁剪: %d 字符 -> 前 %d + LLM 摘要 (%d 字符)",
                    len(text), self.max_result_chars, len(summary),
                )
                return result
            except Exception as e:
                logger.warning("LLM 摘要失败，退化为纯截断: %s", e)

        # 无 summarize_fn 或摘要失败：保留前半 + 后半
        half = self.max_result_chars // 2
        result = text[:half] + "\n\n... [truncated] ...\n\n" + text[-half:]
        logger.info(
            "第二层裁剪(纯截断): %d 字符 -> %d", len(text), len(result),
        )
        return result
