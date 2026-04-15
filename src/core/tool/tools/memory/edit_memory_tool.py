"""edit_memory tool -- precise, localised edits to long-term memory files.

Follows a unified replace model: every operation is expressed as
``old_string`` → ``new_string``.

- **Add**: old_string="" (or omitted), new_string="new content"
- **Delete**: old_string="text to remove", new_string=""
- **Modify**: old_string="old text", new_string="replacement text"
"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from storage.memory_store import VALID_FILES

if TYPE_CHECKING:
    from storage.memory_store import LocalMemoryStore


edit_memory_def: dict[str, Any] = {
    "name": "edit_memory",
    "description": (
        "精确编辑长期记忆文件。使用 old_string + new_string 替换模型。"
        "添加：old_string 为空，new_string 为新内容；"
        "删除：new_string 为空；"
        "修改：两者都填写。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "file": {
                "type": "string",
                "enum": sorted(VALID_FILES),
                "description": "要编辑的长期记忆文件名",
            },
            "old_string": {
                "type": "string",
                "description": "要替换的原文（添加时留空）",
            },
            "new_string": {
                "type": "string",
                "description": "替换后的内容（删除时留空）",
            },
        },
        "required": ["file", "new_string"],
    },
}


def _fuzzy_find(content: str, target: str) -> tuple[int, int] | None:
    """Try to find target in content with relaxed whitespace matching."""
    target_lines = [line.strip() for line in target.strip().splitlines() if line.strip()]
    content_lines = content.splitlines()

    for i in range(len(content_lines)):
        match = True
        for j, tl in enumerate(target_lines):
            if i + j >= len(content_lines):
                match = False
                break
            if content_lines[i + j].strip() != tl:
                match = False
                break
        if match:
            start = sum(len(line) + 1 for line in content_lines[:i])
            end = sum(len(line) + 1 for line in content_lines[:i + len(target_lines)])
            return start, end
    return None


def edit_memory_handler(memory_store: LocalMemoryStore, args: dict[str, Any]) -> str:
    file_name = args.get("file", "")
    old_string = args.get("old_string", "")
    new_string = args.get("new_string", "")

    if file_name not in VALID_FILES:
        return json.dumps(
            {"error": "file_not_found", "message": f"无效文件: {file_name}，可选: {sorted(VALID_FILES)}"},
            ensure_ascii=False,
        )

    content = memory_store.read_file(file_name)

    if not old_string:
        if not content.strip():
            memory_store.write_file(file_name, new_string)
        else:
            memory_store.write_file(file_name, content.rstrip() + "\n" + new_string + "\n")
        return json.dumps({"status": "ok", "action": "append"}, ensure_ascii=False)

    if old_string == new_string:
        return json.dumps(
            {"error": "no_change", "message": "old_string 和 new_string 相同"},
            ensure_ascii=False,
        )

    count = content.count(old_string)
    if count == 1:
        new_content = content.replace(old_string, new_string, 1)
        memory_store.write_file(file_name, new_content)
        return json.dumps({"status": "ok", "action": "replace"}, ensure_ascii=False)

    if count > 1:
        return json.dumps(
            {"error": "ambiguous_match", "message": f"找到 {count} 处匹配，请提供更多上下文以精确定位"},
            ensure_ascii=False,
        )

    loc = _fuzzy_find(content, old_string)
    if loc:
        new_content = content[:loc[0]] + new_string + content[loc[1]:]
        memory_store.write_file(file_name, new_content)
        return json.dumps({"status": "ok", "action": "fuzzy_replace"}, ensure_ascii=False)

    return json.dumps(
        {"error": "not_found", "message": "在文件中找不到 old_string，请先用 read_memory 确认内容"},
        ensure_ascii=False,
    )
