"""定时任务 JSON 文件存储层。

所有任务持久化到 ``~/.heartclaw/scheduled_tasks.json``。
读取时对损坏数据做容错处理（文件不存在 / JSON 损坏 / 字段缺失均返回空列表）。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from config.settings import get_heartclaw_home
from utils.logger import get_logger

logger = get_logger("cron_tasks")

MAX_TASKS = 50

REQUIRED_FIELDS = {"id", "cron", "prompt", "chat_id", "created_at", "recurring"}


def _tasks_file() -> Path:
    return get_heartclaw_home() / "scheduled_tasks.json"


# ------------------------------------------------------------------
# 数据结构
# ------------------------------------------------------------------

@dataclass
class CronTask:
    id: str
    cron: str
    prompt: str
    chat_id: str
    created_at: float
    last_fired_at: float | None = None
    recurring: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> CronTask | None:
        """从字典构造 CronTask，字段缺失时返回 None。"""
        if not REQUIRED_FIELDS.issubset(d.keys()):
            return None
        try:
            return CronTask(
                id=str(d["id"]),
                cron=str(d["cron"]),
                prompt=str(d["prompt"]),
                chat_id=str(d["chat_id"]),
                created_at=float(d["created_at"]),
                last_fired_at=float(d["last_fired_at"]) if d.get("last_fired_at") is not None else None,
                recurring=bool(d.get("recurring", True)),
            )
        except (TypeError, ValueError) as e:
            logger.warning("Invalid task data: %s — %s", d.get("id", "?"), e)
            return None


# ------------------------------------------------------------------
# CRUD
# ------------------------------------------------------------------

def read_cron_tasks() -> list[CronTask]:
    """读取所有任务。文件不存在或损坏时返回空列表。"""
    path = _tasks_file()
    if not path.exists():
        return []

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read cron tasks file: %s", e)
        return []

    raw_tasks = raw.get("tasks", []) if isinstance(raw, dict) else []
    tasks: list[CronTask] = []
    for item in raw_tasks:
        task = CronTask.from_dict(item)
        if task is not None:
            tasks.append(task)
    return tasks


def write_cron_tasks(tasks: list[CronTask]) -> None:
    """覆盖写入全部任务。"""
    path = _tasks_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"tasks": [t.to_dict() for t in tasks]}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add_cron_task(cron: str, prompt: str, chat_id: str, recurring: bool = True) -> str:
    """添加一个任务，返回新任务的 ID。"""
    tasks = read_cron_tasks()
    if len(tasks) >= MAX_TASKS:
        raise ValueError(f"任务数量已达上限 ({MAX_TASKS})，请先删除不需要的任务")

    task_id = uuid.uuid4().hex[:8]
    task = CronTask(
        id=task_id,
        cron=cron,
        prompt=prompt,
        chat_id=chat_id,
        created_at=time.time(),
        recurring=recurring,
    )
    tasks.append(task)
    write_cron_tasks(tasks)
    logger.info("Added cron task %s: cron=%s, recurring=%s", task_id, cron, recurring)
    return task_id


def remove_cron_tasks(ids: list[str]) -> int:
    """按 ID 删除任务，返回实际删除的数量。"""
    tasks = read_cron_tasks()
    id_set = set(ids)
    remaining = [t for t in tasks if t.id not in id_set]
    removed = len(tasks) - len(remaining)
    if removed > 0:
        write_cron_tasks(remaining)
        logger.info("Removed %d cron task(s): %s", removed, ids)
    return removed


def mark_fired(ids: list[str], fired_at: float) -> None:
    """更新指定任务的 last_fired_at。"""
    tasks = read_cron_tasks()
    id_set = set(ids)
    changed = False
    for t in tasks:
        if t.id in id_set:
            t.last_fired_at = fired_at
            changed = True
    if changed:
        write_cron_tasks(tasks)
