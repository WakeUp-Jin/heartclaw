"""Message sanitization.

Ensures tool_calls and tool responses are properly paired before sending
messages to the LLM API.  Unpaired messages cause API errors.
"""

from __future__ import annotations

from typing import Any


def sanitize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove incomplete tool call chains from a message sequence.

    Rules:
    1. An assistant message with ``tool_calls`` must have a matching tool
       response for *every* call id.  If any response is missing the
       assistant message **and** its partial responses are removed.
    2. A tool message whose ``tool_call_id`` does not appear in any preceding
       assistant ``tool_calls`` is removed.
    """
    removed_message_indices: set[int] = set()

    # Map every tool_call id -> index of the assistant message that owns it
    assistant_call_owner_by_id: dict[str, int] = {}
    for message_index, message in enumerate(messages):
        if message.get("role") == "assistant" and message.get("tool_calls"):
            for tool_call in message["tool_calls"]:
                tool_call_id = tool_call.get("id")
                if tool_call_id:
                    assistant_call_owner_by_id[tool_call_id] = message_index

    # Collect ids that have a tool response
    responded_call_ids: set[str] = set()
    tool_message_indices_by_call_id: dict[str, set[int]] = {}
    for message_index, message in enumerate(messages):
        if message.get("role") == "tool" and message.get("tool_call_id"):
            tool_call_id = message["tool_call_id"]
            responded_call_ids.add(tool_call_id)
            tool_message_indices_by_call_id.setdefault(tool_call_id, set()).add(message_index)

    # Rule 1: remove assistant messages with incomplete responses
    for message_index, message in enumerate(messages):
        if message.get("role") != "assistant" or not message.get("tool_calls"):
            continue
        all_responded = all(
            tool_call.get("id") in responded_call_ids
            for tool_call in message["tool_calls"]
        )
        if not all_responded:
            removed_message_indices.add(message_index)
            for tool_call in message["tool_calls"]:
                tool_call_id = tool_call.get("id")
                if tool_call_id:
                    # update的方法就是把另外一个set集合的元素添加到当前集合中，而不是替换
                    removed_message_indices.update(
                        tool_message_indices_by_call_id.get(tool_call_id, set())
                    )

    # Rule 2: remove orphaned tool messages
    for message_index, message in enumerate(messages):
        if message.get("role") == "tool" and message.get("tool_call_id"):
            if message["tool_call_id"] not in assistant_call_owner_by_id:
                removed_message_indices.add(message_index)

    # Rule 3: remove assistant messages with empty content and no tool_calls
    for message_index, message in enumerate(messages):
        if (
            message.get("role") == "assistant"
            and not message.get("tool_calls")
            and not (message.get("content") or "").strip()
        ):
            removed_message_indices.add(message_index)

    return [
        message
        for message_index, message in enumerate(messages)
        if message_index not in removed_message_indices
    ]
