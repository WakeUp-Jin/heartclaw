"""Skill 目录扫描与 catalog 构建。

职责仅限 Tier 1（渐进式加载的第一层）：
- 扫描约定路径，发现所有 SKILL.md
- 解析 frontmatter 提取 name + description
- 构建 XML catalog 文本，注入 system prompt

Tier 2（读取 SKILL.md 正文）和 Tier 3（读 references / 执行 scripts）
完全由模型通过 ReadFile / Bash 工具自主完成。
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import yaml

from core.skill.types import SkillMeta
from utils.logger import get_logger

logger = get_logger("skill.scanner")

# 扫描的子目录名（按优先级排列，项目级在前，用户级在后）
_PROJECT_SKILL_DIRS = [".heartclaw/skills", ".agents/skills", ".claude/skills"]
_USER_SKILL_DIRS = [".heartclaw/skills", ".agents/skills", ".claude/skills"]

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv"}


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def scan_skills(project_root: Path) -> list[SkillMeta]:
    """扫描项目级和用户级目录，返回去重后的 SkillMeta 列表。

    扫描顺序（优先级从高到低）：
      1. <project>/.heartclaw/skills/
      2. <project>/.agents/skills/
      3. <project>/.claude/skills/
      4. ~/.heartclaw/skills/
      5. ~/.agents/skills/
      6. ~/.claude/skills/

    同名 Skill 优先级高的胜出，后续的被跳过并打 warning。
    """
    search_dirs: list[Path] = []

    for rel in _PROJECT_SKILL_DIRS:
        search_dirs.append(project_root / rel)

    home = Path.home()
    for rel in _USER_SKILL_DIRS:
        search_dirs.append(home / rel)

    seen_names: dict[str, Path] = {}
    skills: list[SkillMeta] = []

    for skills_dir in search_dirs:
        if not skills_dir.is_dir():
            continue
        
        # 使用iterdir方法遍历该文件夹下面的全部文件
        for child in sorted(skills_dir.iterdir()):
            if not child.is_dir() or child.name in _SKIP_DIRS:
                continue

            skill_md = child / "SKILL.md"
            if not skill_md.is_file():
                continue

            meta = _parse_skill_md(skill_md)
            if meta is None:
                continue

            if meta.name in seen_names:
                logger.warning(
                    "Skill '%s' at %s shadowed by %s (higher priority)",
                    meta.name, skill_md, seen_names[meta.name],
                )
                continue

            seen_names[meta.name] = skill_md
            skills.append(meta)
            logger.debug("Discovered skill: %s -> %s", meta.name, skill_md)

    if skills:
        logger.info("Discovered %d skill(s): %s", len(skills), [s.name for s in skills])
    else:
        logger.debug("No skills discovered")

    return skills


def build_catalog(skills: list[SkillMeta]) -> str:
    """将 SkillMeta 列表构建为 XML catalog 文本（含行为指令）。

    空列表时返回空字符串——不注入任何内容，避免空标签困惑模型。
    """
    if not skills:
        return ""

    lines = [
        "<agent_skills>",
        "The following skills provide specialized instructions for specific tasks.",
        "When a task matches a skill's description, use the ReadFile tool to load",
        "the SKILL.md at the listed fullPath before proceeding.",
        "When a skill's instructions reference relative paths (like scripts/run.sh",
        "or references/guide.md), resolve them against the skill's directory",
        "(the parent directory of the SKILL.md file) and use absolute paths",
        "in tool calls.",
        "Only load a skill when the current task is relevant. Do NOT load all",
        "skills preemptively.",
        "",
        "<available_skills>",
    ]

    for skill in skills:
        desc = xml_escape(skill.description.strip())
        path = xml_escape(str(skill.location))
        name = xml_escape(skill.name)
        lines.append(f'  <skill>')
        lines.append(f'    <name>{name}</name>')
        lines.append(f'    <description>{desc}</description>')
        lines.append(f'    <location>{path}</location>')
        if skill.always_load_content and skill.body:
            lines.append(f'    <content>')
            lines.append(f'      {xml_escape(skill.body)}')
            lines.append(f'    </content>')
        lines.append(f'  </skill>')

    lines.append("</available_skills>")
    lines.append("</agent_skills>")

    return "\n".join(lines)


# ------------------------------------------------------------------
# Private helpers
# ------------------------------------------------------------------


def _parse_skill_md(skill_md: Path) -> SkillMeta | None:
    """解析一个 SKILL.md，返回 SkillMeta 或 None（解析失败时跳过）。"""
    try:
        content = skill_md.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("Cannot read %s: %s", skill_md, e)
        return None

    meta, body = _extract_frontmatter(content)
    if meta is None:
        logger.warning("Unparseable frontmatter in %s, skipped", skill_md)
        return None

    name = meta.get("name", "")
    description = meta.get("description", "")

    if not name:
        name = skill_md.parent.name

    if not description:
        logger.warning("%s has no description, skipped (description is required for catalog)", skill_md)
        return None

    always_load = bool(meta.get("always_load_content", False))

    return SkillMeta(
        name=str(name).strip(),
        description=str(description).strip(),
        location=skill_md.resolve(),
        always_load_content=always_load,
        body=body if always_load else "",
    )


def _extract_frontmatter(content: str) -> tuple[dict | None, str]:
    """从 SKILL.md 内容中提取 YAML frontmatter 和 body。

    处理常见的畸形 YAML（如冒号值未引用）。
    返回 (meta_dict, body_string)，解析失败时 meta_dict 为 None。
    """
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", content, re.DOTALL)
    if not match:
        return None, content

    yaml_text = match.group(1)
    body = match.group(2).strip()

    parsed = _safe_yaml_load(yaml_text)
    if parsed is None:
        return None, body

    if not isinstance(parsed, dict):
        return None, body

    return parsed, body


def _safe_yaml_load(yaml_text: str) -> dict | None:
    """尝试解析 YAML，失败时对常见问题做 fallback 重试。"""
    try:
        return yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        pass

    # Fallback: 把 description 等字段中未引用的冒号值包裹为块标量
    fixed = re.sub(
        r"^(description|name|compatibility):\s+(.+)$",
        lambda m: f"{m.group(1)}: |\n  {m.group(2)}",
        yaml_text,
        flags=re.MULTILINE,
    )
    try:
        return yaml.safe_load(fixed)
    except yaml.YAMLError as e:
        logger.warning("YAML parse failed even after fallback: %s", e)
        return None
