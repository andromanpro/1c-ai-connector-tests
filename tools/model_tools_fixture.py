"""Checks the actual advertised model tool set and rejected tool responses."""
import json

ALL = {"get_metadata_tree", "get_object_structure", "get_configuration_info", "execute_query"}
EXPECTED = {
    "model-set-one": {"get_configuration_info"},
    "model-set-empty": set(),
    "model-set-denied": {"get_configuration_info"},
    "model-set-caller": {"get_configuration_info"},
    "model-set-legacy": ALL,
}


def reply(payload, scenario, check):
    tools = payload.get("tools", [])
    names = [tool["function"]["name"] for tool in tools]
    check(set(names) == EXPECTED[scenario] and len(names) == len(set(names)), "exact_model_tool_catalog")
    if not names:
        check("tool_choice" not in payload, "empty_catalog_has_no_tool_choice")
    messages = payload.get("messages", [])
    results = {message["tool_call_id"]: message for message in messages if message.get("role") == "tool"}
    if not results:
        calls = []
        if scenario == "model-set-empty":
            calls.append(("forbidden", "get_configuration_info", {}))
        elif scenario == "model-set-denied":
            calls.extend([("forbidden", "execute_query", {"query_id": "should_not_run", "query_text": "ВЫБРАТЬ 123 КАК МаркерНедопустимогоВыполнения", "limit": 1, "params": {}}),
                          ("allowed", "get_configuration_info", {})])
        elif scenario == "model-set-caller":
            calls.extend([("forbidden", "get_metadata_tree", {"filter": "Catalog"}),
                          ("allowed", "get_configuration_info", {})])
        else:
            calls.append(("allowed", "get_configuration_info", {}))
        return {"id": "fixture-model-set-call", "object": "chat.completion", "model": "fixture-model-set",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": None,
                    "tool_calls": [{"id": uid, "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}} for uid, name, args in calls]},
                    "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
    expected_ids = {"forbidden"} if scenario == "model-set-empty" else ({"forbidden", "allowed"} if scenario in {"model-set-denied", "model-set-caller"} else {"allowed"})
    check(set(results) == expected_ids, "all_calls_have_exact_matching_responses")
    if "forbidden" in results:
        text = results["forbidden"]["content"]
        check("не разрешен" in text, "unadvertised_call_refused")
        check("configuration_name" not in text and "МаркерНедопустимогоВыполнения" not in text, "forbidden_call_has_no_execution_result")
    if "allowed" in results:
        value = json.loads(results["allowed"]["content"])
        check(bool(value.get("configuration_name")), "selected_tool_really_executed")
    return {"id": "fixture-model-set-answer", "object": "chat.completion", "model": "fixture-model-set",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": scenario.upper().replace("-", "_") + "_OK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 7, "total_tokens": 27}}
