from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable
import time


class ToolCallStatus(str, Enum):
    """工具调用生命周期状态

    完整流程: validating -> awaiting_approval -> scheduled -> executing -> success/error/cancelled
    """
    VALIDATING = "validating"
    AWAITING_APPROVAL = "awaiting_approval"
    SCHEDULED = "scheduled"
    EXECUTING = "executing"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


class ApprovalMode(str, Enum):
    """审批模式：控制工具执行前的确认行为"""
    DEFAULT = "default"   # 非只读工具需要用户确认
    YOLO = "yolo"         # 全部自动批准


@dataclass
class ConfirmDetails:
    """确认详情，描述需要用户确认的工具调用"""
    title: str
    message: str
    tool_name: str
    args_summary: str = ""


@dataclass
class ToolParameterSchema:
    """JSON Schema 风格的工具参数定义"""
    type: str = "object"
    properties: dict[str, Any] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "properties": self.properties,
            "required": self.required,
        }


@dataclass
class ToolResult:
    """工具执行的统一结果，所有 handler 都应返回此类型"""
    success: bool
    data: Any = None
    error: str | None = None

    @staticmethod
    def ok(data: Any = None) -> ToolResult:
        return ToolResult(success=True, data=data)

    @staticmethod
    def fail(error: str) -> ToolResult:
        return ToolResult(success=False, error=error)


@dataclass
class PermissionResult:
    """权限验证函数 (check_permissions) 的返回结果。

    - passed=True  表示验证通过，可继续调度
    - passed=False 表示验证失败，调度器会将状态设为 ERROR
    - sanitized_args 可以携带验证后修正过的参数（如路径展开、默认值填充），
      调度器会用它替换原始 args 传给 handler
    """
    passed: bool
    error: str | None = None
    sanitized_args: dict[str, Any] | None = None

    @staticmethod
    def ok(sanitized_args: dict[str, Any] | None = None) -> PermissionResult:
        return PermissionResult(passed=True, sanitized_args=sanitized_args)

    @staticmethod
    def fail(error: str) -> PermissionResult:
        return PermissionResult(passed=False, error=error)


@dataclass
class InternalTool:
    """工具定义——名称、描述、参数 Schema、执行函数、权限验证、输出格式化。

    字段说明:
    - handler:           工具的核心执行逻辑
    - check_permissions: 可选的权限验证函数，在调度流程的 validating 阶段被调用
    - render_result:     可选的结果格式化函数，将 ToolResult 转为大模型可读的字符串
    - is_read_only:      标记为只读工具（影响审批模式判断和并行调度）
    """
    name: str
    description: str
    parameters: ToolParameterSchema
    handler: Callable[[dict[str, Any]], Awaitable[ToolResult]]
    check_permissions: Callable[[dict[str, Any]], Awaitable[PermissionResult]] | None = None
    render_result: Callable[[ToolResult], str] | None = None
    category: str = "general"
    is_read_only: bool = False

    def get_openai_function(self) -> dict[str, Any]:
        """输出 OpenAI function calling 格式的工具定义"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters.to_dict(),
        }


@dataclass
class ToolCallRecord:
    """单次工具调用的完整生命周期记录"""
    call_id: str
    tool_name: str
    status: ToolCallStatus = ToolCallStatus.VALIDATING
    args: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: str | None = None
    start_time: float = field(default_factory=time.time)
    duration_ms: float | None = None
    confirm_details: ConfirmDetails | None = None

    def elapsed_ms(self) -> float:
        return (time.time() - self.start_time) * 1000


@dataclass
class ScheduleResult:
    """调度器返回给 tool_loop 的结果"""
    call_id: str
    tool_name: str
    success: bool
    status: ToolCallStatus
    result: Any = None
    result_string: str = ""
    error: str | None = None
