"""Bash 工具定义与权限验证。

权限验证实现了文档中的核心安全检查（MVP 阶段）：
1. 基础参数检查
2. 控制字符与 Unicode 空白拒绝
3. 危险删除路径拦截 (rm/rmdir)
4. eval-like builtin 拦截
5. 只读命令识别
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from core.tool.types import InternalTool, ToolParameterSchema, PermissionResult
from core.tool.tools.bash.executor import bash_handler, render_bash_result

# ── 安全检查用的正则和集合 ──

# 控制字符：可能导致 tree-sitter 与 bash 分词不一致
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

# Unicode 空白：看起来像空格但 bash 会当分隔符，tree-sitter 不会
UNICODE_WHITESPACE_RE = re.compile(
    r"[\u00a0\u1680\u2000-\u200b\u2028\u2029\u202f\u205f\u3000\ufeff]"
)

# eval-like builtin：会把参数当"代码"再执行的 shell 内建命令
EVAL_LIKE_BUILTINS = frozenset({
    "eval", "source", ".", "exec", "command", "builtin",
    "fc", "coproc", "noglob", "nocorrect", "trap", "enable",
    "mapfile", "readarray", "hash", "bind", "complete",
    "compgen", "alias", "let",
})

# eval-like 的安全例外（只查询不执行）
EVAL_SAFE_EXCEPTIONS: dict[str, set[str]] = {
    "command": {"-v", "-V"},
    "fc": {"-l", "-ln"},
    "compgen": {"-c", "-f", "-v"},
}

# 只读命令：这些命令不会修改文件系统
READONLY_COMMANDS = frozenset({
    "ls", "cat", "head", "tail", "wc", "find", "grep", "rg",
    "file", "stat", "du", "df", "which", "whereis", "type",
    "echo", "printf", "date", "uname", "whoami", "id", "env",
    "printenv", "pwd", "hostname", "uptime", "free", "ps",
    "tree", "less", "more", "diff", "sort", "uniq", "tr",
    "cut", "awk", "sed", "jq", "curl", "wget", "ping",
    "python", "python3", "node", "npm", "pip", "pip3",
    "cargo", "go", "java", "javac", "gcc", "g++", "make",
})

# git 只读子命令
GIT_READONLY_SUBCOMMANDS = frozenset({
    "status", "diff", "log", "show", "branch", "tag",
    "remote", "stash", "ls-files", "ls-tree", "rev-parse",
    "describe", "shortlog", "blame", "config",
})

# Windows 驱动器根目录
WINDOWS_DRIVE_ROOT_RE = re.compile(r"^[a-zA-Z]:[\\/]?$")
WINDOWS_DRIVE_CHILD_RE = re.compile(r"^[a-zA-Z]:[\\/][^\\/]+$")


def _extract_first_command(command: str) -> str:
    """粗略提取命令链中第一个命令名（不做完整 AST 解析）。"""
    # 去掉前导环境变量赋值 (VAR=val cmd ...)
    parts = command.strip().split()
    for part in parts:
        if "=" in part and not part.startswith("-"):
            continue
        return part
    return ""


def _is_readonly_command(command: str) -> bool:
    """判断命令是否为只读命令。"""
    cmd_name = _extract_first_command(command)
    base = os.path.basename(cmd_name)

    if base in READONLY_COMMANDS:
        return True

    if base == "git":
        parts = command.strip().split()
        for i, p in enumerate(parts):
            if p == "git":
                if i + 1 < len(parts) and parts[i + 1] in GIT_READONLY_SUBCOMMANDS:
                    return True
                break
    return False


def _is_dangerous_removal_path(resolved_path: str) -> bool:
    """检测 rm/rmdir 目标路径是否为系统关键路径。"""
    forward = resolved_path.replace("\\", "/")

    # 通配符删除
    if forward == "*" or forward.endswith("/*"):
        return True

    normalized = forward.rstrip("/") if forward != "/" else forward

    # 根目录
    if normalized == "/":
        return True

    # Windows 驱动器根目录
    if WINDOWS_DRIVE_ROOT_RE.match(normalized):
        return True

    # 用户主目录
    home = str(Path.home()).replace("\\", "/")
    if normalized == home:
        return True

    # 根目录的直接子目录 (如 /usr, /etc, /tmp)
    parent = os.path.dirname(normalized)
    if parent == "/":
        return True

    # Windows 驱动器的直接子目录 (如 C:\Windows)
    if WINDOWS_DRIVE_CHILD_RE.match(normalized):
        return True

    return False


def _check_dangerous_rm(command: str) -> str | None:
    """检查 rm/rmdir 命令中是否包含危险路径，返回错误信息或 None。"""
    parts = command.strip().split()
    if not parts:
        return None

    cmd_base = os.path.basename(parts[0])
    if cmd_base not in ("rm", "rmdir"):
        return None

    for part in parts[1:]:
        if part.startswith("-"):
            continue
        if _is_dangerous_removal_path(part):
            return f"拒绝执行：检测到危险删除路径 '{part}'"

    return None


def _check_eval_like(command: str) -> str | None:
    """检查命令是否使用了 eval-like builtin，返回错误信息或 None。"""
    cmd_name = _extract_first_command(command)
    base = os.path.basename(cmd_name)

    if base not in EVAL_LIKE_BUILTINS:
        return None

    # 检查安全例外
    safe_flags = EVAL_SAFE_EXCEPTIONS.get(base)
    if safe_flags:
        parts = command.strip().split()
        for part in parts[1:]:
            if part in safe_flags:
                return None

    return f"拒绝执行：'{base}' 会将参数作为代码执行，存在安全风险"


async def bash_check_permissions(args: dict[str, Any]) -> PermissionResult:
    """Bash 工具的多层权限验证。"""
    command = args.get("command", "").strip()

    # 1. 基础参数检查
    if not command:
        return PermissionResult.fail("command 不能为空")

    # 2. 控制字符拒绝
    if CONTROL_CHAR_RE.search(command):
        return PermissionResult.fail(
            "命令中包含控制字符，可能导致解析歧义，拒绝执行"
        )

    # 3. Unicode 空白拒绝
    if UNICODE_WHITESPACE_RE.search(command):
        return PermissionResult.fail(
            "命令中包含 Unicode 空白字符，可能导致解析歧义，拒绝执行"
        )

    # 4. 危险删除路径拦截
    # 对 && 和 ; 分隔的多段命令逐段检查
    for segment in re.split(r"[;&|]+", command):
        segment = segment.strip()
        if not segment:
            continue

        rm_err = _check_dangerous_rm(segment)
        if rm_err:
            return PermissionResult.fail(rm_err)

        eval_err = _check_eval_like(segment)
        if eval_err:
            return PermissionResult.fail(eval_err)

    # 5. 超时参数清洗
    sanitized = dict(args)
    timeout = args.get("timeout")
    if timeout is not None:
        sanitized["timeout"] = max(1000, min(int(timeout), 10 * 60 * 1000))

    return PermissionResult.ok(sanitized_args=sanitized)


# ── 工具描述（给模型看的提示词）──

BASH_DESCRIPTION = """\
执行给定的 bash 命令并返回其输出。
工作目录在命令之间是持久化的，但 shell 状态不持久化。

重要：避免使用此工具运行 find、grep、cat、head、tail、sed、awk 或 echo 命令，\
除非明确指示或已验证专用工具无法完成任务。应使用适当的专用工具。

# Instructions
- 如果命令将创建新目录或文件，首先运行 ls 验证父目录存在且位置正确。
- 始终对包含空格的文件路径使用双引号引用。
- 尽量使用绝对路径，避免使用 cd。
- 可指定可选超时（毫秒，最多 10 分钟），默认 2 分钟后超时。
- 执行多个命令时，独立命令可并行调用；依赖命令用 && 链式执行。
- 不要用换行符分隔命令。\
"""


BashTool = InternalTool(
    name="Bash",
    description=BASH_DESCRIPTION,
    parameters=ToolParameterSchema(
        type="object",
        properties={
            "command": {
                "type": "string",
                "description": "要执行的命令",
            },
            "timeout": {
                "type": "integer",
                "description": "可选的超时时间（毫秒），默认 120000，最大 600000",
            },
            "description": {
                "type": "string",
                "description": "用主动语态简明扼要地描述该命令的作用",
            },
        },
        required=["command"],
    ),
    handler=bash_handler,
    check_permissions=bash_check_permissions,
    render_result=render_bash_result,
    category="system",
    is_read_only=False,
)
