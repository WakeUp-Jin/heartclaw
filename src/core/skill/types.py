"""Skill 元数据类型定义。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SkillMeta:
    """Tier 1 元数据：启动时扫描 SKILL.md frontmatter 得到，注入 system prompt catalog。

    Attributes:
        name: frontmatter 的 name 字段（Skill 唯一标识）
        description: frontmatter 的 description 字段（模型据此判断是否加载）
        location: SKILL.md 的绝对路径（模型用 ReadFile 读取此路径）
    """

    name: str
    description: str
    location: Path
