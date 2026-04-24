"""Cron 表达式解析工具。

基于 croniter 库，提供验证、下次触发时间计算、人类可读转换。
所有时间均使用本地时区。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from croniter import croniter

from utils.logger import get_logger

logger = get_logger("cron_parser")


def is_valid_cron(expr: str) -> bool:
    """验证 5 字段 cron 表达式是否合法。"""
    return croniter.is_valid(expr)


def next_cron_time(cron: str, from_time: datetime | None = None) -> datetime | None:
    """计算 cron 表达式在 from_time 之后的下一次触发时间。

    Parameters
    ----------
    cron:
        标准 5 字段 cron 表达式 (分 时 日 月 星期)。
    from_time:
        基准时间，默认为当前时间。

    Returns
    -------
    下次触发的 datetime（本地时区），如果一年内没有匹配则返回 None。
    """
    if not is_valid_cron(cron):
        return None

    base = from_time or datetime.now()
    try:
        it = croniter(cron, base)
        nxt: datetime = it.get_next(datetime)
    except (ValueError, KeyError):
        return None

    if nxt - base > timedelta(days=366):
        return None

    return nxt


def has_future_match(cron: str) -> bool:
    """检查 cron 表达式在未来一年内是否有匹配时间点。"""
    return next_cron_time(cron) is not None


# ------------------------------------------------------------------
# 人类可读转换
# ------------------------------------------------------------------

_WEEKDAY_NAMES = {
    "0": "周日", "1": "周一", "2": "周二", "3": "周三",
    "4": "周四", "5": "周五", "6": "周六", "7": "周日",
}


def _format_time(hour: str, minute: str) -> str:
    """将小时和分钟格式化为 HH:MM。"""
    return f"{int(hour):02d}:{int(minute):02d}"


def cron_to_human(cron: str) -> str:
    """将 cron 表达式转为人类可读的中文描述。

    覆盖常见模式，不匹配时直接返回原始 cron 字符串。
    """
    if not is_valid_cron(cron):
        return cron

    parts = cron.strip().split()
    if len(parts) != 5:
        return cron

    minute, hour, dom, month, dow = parts

    # */N * * * * — 每 N 分钟
    if re.match(r"^\*/\d+$", minute) and hour == "*" and dom == "*" and month == "*" and dow == "*":
        n = minute.split("/")[1]
        return f"每{n}分钟"

    # 0 */N * * * — 每 N 小时
    if minute == "0" and re.match(r"^\*/\d+$", hour) and dom == "*" and month == "*" and dow == "*":
        n = hour.split("/")[1]
        return f"每{n}小时"

    # 0 * * * * — 每小时整点
    if minute == "0" and hour == "*" and dom == "*" and month == "*" and dow == "*":
        return "每小时"

    # M * * * * — 每小时的第 M 分钟
    if minute.isdigit() and hour == "*" and dom == "*" and month == "*" and dow == "*":
        return f"每小时的第{minute}分钟"

    # M H * * * — 每天 HH:MM
    if minute.isdigit() and hour.isdigit() and dom == "*" and month == "*" and dow == "*":
        return f"每天 {_format_time(hour, minute)}"

    # M H * * 1-5 — 工作日 HH:MM
    if minute.isdigit() and hour.isdigit() and dom == "*" and month == "*" and dow == "1-5":
        return f"工作日 {_format_time(hour, minute)}"

    # M H * * N — 每周某天 HH:MM
    if minute.isdigit() and hour.isdigit() and dom == "*" and month == "*" and dow.isdigit():
        day_name = _WEEKDAY_NAMES.get(dow, f"星期{dow}")
        return f"每{day_name} {_format_time(hour, minute)}"

    # M H D Mon * — 特定日期 HH:MM（一次性任务）
    if minute.isdigit() and hour.isdigit() and dom.isdigit() and month.isdigit() and dow == "*":
        return f"{int(month)}月{int(dom)}日 {_format_time(hour, minute)}"

    return cron
