"""Synthetic loopback model for expert tool-cycle integration tests."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import json

@contextmanager
def local_expert_fixture():
    events=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send_json(self,code,data):
            raw=json.dumps(data,ensure_ascii=False).encode("utf-8")
            self.send_response(code);self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_POST(self):
            payload=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))))
            scenario=self.path.strip("/").split("/")[0]
            event={"scenario":scenario,"body":payload,"checks":[]}
            events.append(event)
            def check(value,label):
                event["checks"].append({"label":label,"passed":bool(value)})
                if not value:raise AssertionError(label)
            try:
                check(str(payload.get("model","")).startswith("expert-test-"),"synthetic_model_only")
                messages=payload.get("messages",[])
                tools=payload.get("tools",[])
                results=[x for x in messages if x.get("role")=="tool"]
                if scenario == "monitor-limit":
                    if tools:
                        names = {item["function"]["name"] for item in tools}
                        check(names == {"get_configuration_info", "get_object_structure", "get_metadata_tree"},
                              "monitoring_metadata_only_tools")
                        if results:
                            check(results[-1]["tool_call_id"] == "monitor-" + str(len(results) - 1),
                                  "monitoring_result_matches_call")
                            check(bool(results[-1].get("content")), "monitoring_result_is_nonempty")
                        message = {"role": "assistant", "content": None, "tool_calls": [
                            {"id": "monitor-" + str(len(results)), "type": "function",
                             "function": {"name": "get_configuration_info", "arguments": "{}"}}]}
                        finish = "tool_calls"
                    else:
                        check(bool(results), "monitoring_final_has_tool_result")
                        message = {"role": "assistant", "content": "LIMIT_OK"}
                        finish = "stop"
                    self.send_json(200, {"choices": [{"message": message, "finish_reason": finish}],
                                         "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}})
                    return
                if scenario in {"cost-loop", "cost-partial"}:
                    usage = {"prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200,
                             "prompt_tokens_details": {"cached_tokens": 400}, "cost": 0.111}
                    if not results:
                        message = {"role": "assistant", "content": None, "tool_calls": [
                            {"id": "cost-call", "type": "function", "function": {"name": "get_configuration_info", "arguments": "{}"}}]}
                        data = {"choices": [{"message": message, "finish_reason": "tool_calls"}]}
                        if scenario == "cost-loop":
                            data["usage"] = usage
                    else:
                        check(results[-1]["tool_call_id"] == "cost-call", "cost_result_matches_public_call")
                        data = {"choices": [{"message": {"role": "assistant", "content": "COST_OK"}, "finish_reason": "stop"}],
                                "usage": {"prompt_tokens": 2000, "completion_tokens": 300, "total_tokens": 2300,
                                          "prompt_tokens_details": {"cached_tokens": 500}, "cost": 0.222}}
                    self.send_json(200, data)
                    return
                if scenario == "pagination":
                    schema = next(t["function"]["parameters"] for t in tools if t["function"]["name"] == "get_metadata_tree")
                    check({"offset", "limit"} <= set(schema["properties"]), "pagination_schema_advertised")
                    if results:
                        pages = [json.loads(item["content"]) for item in results]
                        for page, item in zip(pages, results):
                            check(page.get("paged") is True and "preview" not in page, "whole_page_reaches_model")
                            check(len(item["content"]) <= 1500, "page_within_budget")
                            check(page["returned_count"] == len(page["objects"]) > 0, "page_has_whole_objects")
                            check(page["next_offset"] == page["offset"] + page["returned_count"], "cursor_matches_delivered_objects")
                        if len(pages) == 2:
                            check(pages[1]["offset"] == pages[0]["next_offset"], "continuation_has_no_gap")
                            first_refs = {x["canonical_ref"] for x in pages[0]["objects"]}
                            check(not first_refs.intersection(x["canonical_ref"] for x in pages[1]["objects"]), "pages_do_not_repeat")
                            self.send_json(200, {"choices": [{"message": {"role": "assistant", "content": "PAGINATION_OK"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}})
                            return
                        arguments = {"filter": "Catalog.*", "offset": pages[-1]["next_offset"], "limit": 20}
                    else:
                        arguments = {"filter": "Catalog.*"}
                    self.send_json(200, {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{"id": "metadata-" + str(len(results)), "type": "function", "function": {"name": "get_metadata_tree", "arguments": json.dumps(arguments)}}]}, "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}})
                    return
                if scenario.startswith("chat-context-"):
                    if scenario == "chat-context-error":
                        self.send_json(400,{"error":{"message":"synthetic chat context failure"}});return
                    from chat_context_fixture import reply
                    self.send_json(200,reply(payload,scenario,check));return
                if scenario.startswith("model-set-"):
                    from model_tools_fixture import reply
                    self.send_json(200,reply(payload,scenario,check));return
                if scenario.startswith("database-"):
                    from agent_database_model_fixture import database_reply
                    self.send_json(200,database_reply(payload,scenario,check));return
                if scenario=="plain":
                    check(not tools,"ordinary_route_has_no_tools")
                    text="PLAIN_OK"
                else:
                    check(scenario!="must-not-send","unsupported_model_does_not_reach_http")
                    if scenario!="limit" or not results:
                        check({t["function"]["name"] for t in tools}=={"get_metadata_tree","get_object_structure","get_configuration_info","execute_query"},"four_builtin_tools")
                    if scenario=="rounds":
                        check([m["role"] for m in messages[:4]]==["system","user","assistant","user"],"history_role_order")
                        check([m["content"] for m in messages[:4]]==["инструкция","первый вопрос","первый ответ","уточнение"],"history_content")
                    if scenario=="attachment":
                        user=next(m for m in messages if m.get("role")=="user")
                        check(isinstance(user["content"],list),"attachment_is_array")
                        check(user["content"][0]["text"]=="посмотри изображение","attachment_prompt_text")
                        check(user["content"][1]["image_url"]["url"]=="https://example.test/image.png","attachment_url_preserved")
                    if scenario=="masked":
                        check("tools.person@example.org" not in json.dumps(payload,ensure_ascii=False),"original_email_absent_in_all_rounds")
                    if not results:
                        name="drop_table" if scenario=="denied" else "get_configuration_info"
                        data={"id":"fixture-round-1","object":"chat.completion","model":"fixture-expert-tools",
                              "choices":[{"index":0,"message":{"role":"assistant","content":None,
                               "tool_calls":[{"id":"call_config","type":"function","function":{"name":name,"arguments":"{}"}}]},
                               "finish_reason":"tool_calls"}],"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}
                        self.send_json(200,data);return
                    check(results[-1]["tool_call_id"]=="call_config","tool_response_matches_call")
                    check(bool(results[-1].get("content")),"tool_result_is_nonempty")
                    if scenario=="denied":
                        check("не разрешен" in results[-1]["content"],"unknown_tool_refused")
                        text="DENIED_OK"
                    elif scenario=="failure":
                        self.send_json(400,{"error":{"message":"synthetic second-round failure"}});return
                    elif scenario=="limit":
                        check(not tools,"final_round_has_no_tools")
                        text="LIMIT_OK"
                    elif scenario=="masked":
                        text=next(m["content"] for m in messages if m.get("role")=="user")
                    else:text="TOOLS_OK"
                data={"id":"fixture-round-2","object":"chat.completion","model":"fixture-expert-tools",
                      "choices":[{"index":0,"message":{"role":"assistant","content":text},"finish_reason":"stop"}],
                      "usage":{"prompt_tokens":20,"completion_tokens":7,"total_tokens":27}}
                self.send_json(200,data)
            except Exception as exc:
                event["fixture_error"]=str(exc)
                self.send_json(400,{"error":{"message":"fixture: "+str(exc)}})
    server=ThreadingHTTPServer(("127.0.0.1",18770),Handler)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield events
    finally:server.shutdown();server.server_close();thread.join(5)

