"""Message sanitization and validation.

Ensures tool_calls and tool responses are properly paired before sending
messages to the LLM API.  Unpaired messages cause API errors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationIssue:
    type: str
    detail: str


@dataclass
class ValidationResult:
    valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)


def sanitize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove incomplete tool call chains from a message sequence.

    Rules:
    1. An assistant message with ``tool_calls`` must have a matching tool
       response for *every* call id.  If any response is missing the
       assistant message **and** its partial responses are removed.
    2. A tool message whose ``tool_call_id`` does not appear in any preceding
       assistant ``tool_calls`` is removed.
    """
    removed: set[int] = set()

    # Map every tool_call id -> index of the assistant message that owns it
    call_id_to_assistant: dict[str, int] = {}
    for i, msg in enumerate(messages):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id")
                if tc_id:
                    call_id_to_assistant[tc_id] = i

    # Collect ids that have a tool response
    response_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "tool" and msg.get("tool_call_id"):
            response_ids.add(msg["tool_call_id"])

    # Rule 1: remove assistant messages with incomplete responses
    for i, msg in enumerate(messages):
        if msg.get("role") != "assistant" or not msg.get("tool_calls"):
            continue
        all_responded = all(tc.get("id") in response_ids for tc in msg["tool_calls"])
        if not all_responded:
            removed.add(i)
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id")
                if tc_id:
                    for j, m2 in enumerate(messages):
                        if m2.get("role") == "tool" and m2.get("tool_call_id") == tc_id:
                            removed.add(j)

    # Rule 2: remove orphaned tool messages
    for i, msg in enumerate(messages):
        if msg.get("role") == "tool" and msg.get("tool_call_id"):
            if msg["tool_call_id"] not in call_id_to_assistant:
                removed.add(i)

    return [m for i, m in enumerate(messages) if i not in removed]


def validate_messages(messages: list[dict[str, Any]]) -> ValidationResult:
    """Check message integrity without modifying anything."""
    issues: list[ValidationIssue] = []

    valid_call_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id")
                if tc_id:
                    valid_call_ids.add(tc_id)

    response_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "tool" and msg.get("tool_call_id"):
            response_ids.add(msg["tool_call_id"])

    # Missing tool responses
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id")
                if tc_id and tc_id not in response_ids:
                    fn_name = tc.get("function", {}).get("name", "unknown")
                    issues.append(ValidationIssue(
                        type="missing_tool_response",
                        detail=f"tool_call {tc_id} ({fn_name}) has no matching tool response",
                    ))

    # Orphaned tool messages
    for msg in messages:
        if msg.get("role") == "tool" and msg.get("tool_call_id"):
            if msg["tool_call_id"] not in valid_call_ids:
                issues.append(ValidationIssue(
                    type="orphaned_tool_message",
                    detail=f"tool response {msg['tool_call_id']} has no matching assistant tool_call",
                ))

    return ValidationResult(valid=len(issues) == 0, issues=issues)
