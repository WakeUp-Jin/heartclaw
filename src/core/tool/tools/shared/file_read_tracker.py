"""文件读取状态追踪器 —— TOCTOU 防护的共享模块。

当 ReadFile 工具成功读取文件后，记录文件路径和当时的 mtime。
当 Edit / Write 工具执行前，调用 check_freshness 检查文件是否在
模型读取之后被外部修改过。如果 mtime 变了，说明模型依据的是旧内容，
应该拒绝此次写入并提示模型重新读取。

TOCTOU = Time-of-Check to Time-of-Use
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from utils.logger import get_logger

logger = get_logger("tool.file_read_tracker")


@dataclass
class _ReadRecord:
    """单个文件的读取记录。"""
    mtime: float
    is_partial: bool = False


class FileReadTracker:
    """维护文件路径 -> 读取时 mtime 的映射。

    整个 Agent 会话共享同一个实例。
    """

    def __init__(self) -> None:
        self._records: dict[str, _ReadRecord] = {}

    def record_read(
        self,
        file_path: str,
        *,
        is_partial: bool = False,
    ) -> None:
        """ReadFile 工具调用成功后调用，记录文件的 mtime。

        Parameters
        ----------
        file_path:
            已规范化为绝对路径的文件路径。
        is_partial:
            如果只读了文件的一部分（offset/limit），标记为 partial。
        """
        try:
            mtime = os.path.getmtime(file_path)
        except OSError:
            logger.warning("record_read: 无法获取 mtime: %s", file_path)
            return

        self._records[file_path] = _ReadRecord(mtime=mtime, is_partial=is_partial)
        logger.debug("record_read: %s (mtime=%.3f, partial=%s)", file_path, mtime, is_partial)

    def check_freshness(self, file_path: str) -> tuple[bool, str]:
        """Edit / Write 工具执行前检查文件是否仍然"新鲜"。

        Returns
        -------
        (passed, message)
            passed=True  表示检查通过，可以继续执行。
            passed=False 表示检查失败，message 中包含原因。
        """
        record = self._records.get(file_path)

        if record is None:
            return False, (
                f"文件 {file_path} 尚未被读取。"
                "请先使用 ReadFile 工具读取文件内容，再执行编辑或写入操作。"
            )

        try:
            current_mtime = os.path.getmtime(file_path)
        except FileNotFoundError:
            return True, ""
        except OSError as e:
            logger.warning("check_freshness: 无法获取 mtime: %s (%s)", file_path, e)
            return True, ""

        if current_mtime > record.mtime:
            return False, (
                f"文件 {file_path} 在你读取之后已被外部修改。"
                "请重新使用 ReadFile 工具读取最新内容后再操作。"
            )

        return True, ""

    def update_after_write(self, file_path: str) -> None:
        """写入/编辑完成后更新 mtime 记录，防止下次编辑时 TOCTOU 误报。"""
        try:
            mtime = os.path.getmtime(file_path)
        except OSError:
            logger.warning("update_after_write: 无法获取 mtime: %s", file_path)
            return

        self._records[file_path] = _ReadRecord(mtime=mtime, is_partial=False)

    def clear(self) -> None:
        """清除所有记录（用于会话重置）。"""
        self._records.clear()


# 全局单例，整个 Agent 会话共享
file_read_tracker = FileReadTracker()
