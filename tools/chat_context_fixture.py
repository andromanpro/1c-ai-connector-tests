"""Echoes the actual model payload for independent preview and journal checks."""
import json


def reply(payload, scenario, check):
    messages = payload.get("messages", [])
    tools = payload.get("tools", [])
    check(bool(messages), "chat_context_has_messages")
    text = json.dumps(payload, ensure_ascii=False)
    check("APIКлюч" not in text and "Authorization" not in text, "no_connector_credentials_in_body")
    if scenario == "chat-context-masked":
        check("preview.person@example.org" not in text, "original_email_absent")
    if scenario == "chat-context-rounds" and not any(m.get("role") == "tool" for m in messages):
        check("get_configuration_info" in {t["function"]["name"] for t in tools}, "round_tool_advertised")
        message = {"role": "assistant", "content": None,
                   "tool_calls": [{"id": "chat-context-config", "type": "function",
                                   "function": {"name": "get_configuration_info", "arguments": "{}"}}]}
    else:
        if scenario == "chat-context-rounds":
            check(any(m.get("tool_call_id") == "chat-context-config" for m in messages), "round_tool_result_bound")
        message = {"role": "assistant", "content": json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False)}
    return {"id": "chat-context-fixture", "object": "chat.completion", "model": "expert-test-chat-context",
            "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if "tool_calls" in message else "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
