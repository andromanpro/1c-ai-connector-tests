"""Deterministic model replies plus a real HTTP 503 target for 1C reproduction."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import os
import threading
import base64

PORT = 18845
PREFIX = "Доступные базы для инструментов:\n"
UNAVAILABLE = "Не удалось подключиться к базе 11_5_new_fixture. Проверьте доступность сервиса."


def markup(identifier, ascii_pipes=False):
    pipe = "|" if ascii_pipes else "｜"
    prefix = "<" + pipe + "DSML" + pipe
    ending = "</" + pipe + "DSML" + pipe
    calls = [prefix + "function_calls>"]
    for name in ("test_a", "test_b"):
        calls.extend([
            prefix + 'invoke name="execute_query">',
            prefix + 'parameter name="database_id" string="true">' + identifier + ending + "parameter>",
            prefix + 'parameter name="query_id" string="true">' + name + ending + "parameter>",
            prefix + 'parameter name="query_text" string="true">ВЫБРАТЬ ПЕРВЫЕ 5 Регистратор ИЗ '
            + "РегистрНакопления.ВыручкаИСебестоимостьПродаж" + ending + "parameter>",
            ending + "invoke>",
        ])
    calls.append(ending + "function_calls>")
    return "\n".join(calls)


def completion(content, calls=None):
    message = {"role": "assistant", "content": content}
    if calls is not None:
        message["tool_calls"] = calls
    return {"id": "synthetic-dsml-reproduction", "object": "chat.completion",
            "model": "fixture-dsml", "choices": [{"index": 0, "message": message,
            "finish_reason": "tool_calls" if calls is not None else "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


@contextmanager
def local_reproduction_fixture(folder, enabled=True):
    if not enabled:
        yield []
        return
    events = []
    lock = threading.Lock()
    verified_targets = set()

    def save():
        target = Path(folder) / "dsml-fixture-events.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, target)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            event = {"path": self.path, "request": body, "checks": []}

            def check(value, label):
                event["checks"].append({"label": label, "passed": bool(value)})
                if not value:
                    raise AssertionError(label)

            try:
                if self.path.startswith("/unavailable/"):
                    event["kind"] = "target_database"
                    check(body.get("jsonrpc") == "2.0", "real_mcp_request")
                    method = body.get("method")
                    if self.path in verified_targets:
                        event["phase"] = "after_native_verification"
                        status, response = 503, {"error": "Synthetic maintenance: target service unavailable"}
                    else:
                        event["phase"] = "native_verification"
                        expected = "Basic " + base64.b64encode(b"reader-a:123456").decode()
                        accepted = self.headers.get("Authorization") == expected
                        event["authorization_accepted"] = accepted
                        if not accepted:
                            status, response = 401, {"error": "Authentication required"}
                        elif method == "initialize":
                            status, response = 200, {"jsonrpc": "2.0", "id": body["id"], "result": {
                                "protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                                "serverInfo": {"name": "synthetic-mcp", "version": "1"}}}
                        elif method == "notifications/initialized":
                            status, response = 202, {}
                        elif method == "tools/call" and body.get("params", {}).get("name") == "get_configuration_info":
                            data = {"session_user": "reader-a", "connection_protocol": 1,
                                    "database_id": "11111111-1111-1111-1111-111111111111",
                                    "configuration_name": "SyntheticTarget", "configuration_version": "1"}
                            result = {"ok": True, "tool": "get_configuration_info", "isError": False,
                                      "content": [{"type": "text", "text": json.dumps(data)}], "structuredContent": data}
                            status, response = 200, {"jsonrpc": "2.0", "id": body["id"], "result": result}
                            verified_targets.add(self.path)
                        else:
                            raise AssertionError("unexpected_native_verification_request")
                else:
                    event["kind"] = "model"
                    scenario = self.path.strip("/").split("/")[0]
                    event["scenario"] = scenario
                    check(str(body.get("model", "")).startswith("expert-test-"), "synthetic_model_only")
                    messages = body.get("messages", [])
                    catalogs = [json.loads(m["content"][len(PREFIX):].split("\n\n", 1)[0])
                                for m in messages if m.get("role") == "system"
                                and isinstance(m.get("content"), str) and m["content"].startswith(PREFIX)]
                    check(len(catalogs) == 1 and len(catalogs[0]) == 1, "one_selected_database")
                    database = catalogs[0][0]
                    identifier = database["database_id"]
                    check("reader-a" not in json.dumps(body) and "123456" not in json.dumps(body),
                          "no_target_credentials_in_model_context")
                    check("execute_query" in [t["function"]["name"] for t in body.get("tools", [])],
                          "query_tool_was_advertised")
                    results = [m for m in messages if m.get("role") == "tool"]
                    if scenario == "dsml-direct":
                        check(not results, "no_tool_result_before_raw_commands")
                        response = completion(markup(identifier))
                    elif scenario == "dsml-leading-space":
                        response = completion(" \n\t" + markup(identifier, ascii_pipes=True))
                    elif scenario == "dsml-inline-quote":
                        response = completion("Маркер `<|DSML|function_calls>` обозначает блок вызовов.")
                    elif scenario == "dsml-structured":
                        if not results:
                            response = completion(markup(identifier), [{"id": "structured-call", "type": "function", "function": {
                                "name": "get_configuration_info", "arguments": json.dumps({"database_id": identifier})}}])
                        else:
                            check(len(results) == 1 and results[0]["tool_call_id"] == "structured-call", "structured_call_has_result")
                            result = json.loads(results[-1]["content"])
                            check(result["success"] is True, "structured_call_succeeded")
                            response = completion("STRUCTURED_OK")
                    elif scenario == "dsml-plain":
                        check(not results, "plain_answer_needs_no_tool")
                        response = completion("PLAIN_OK")
                    elif scenario == "dsml-quoted":
                        check(not results, "quoted_example_needs_no_tool")
                        response = completion("Пример служебной разметки, которую вы просили объяснить:\n```text\n"
                                              + markup(identifier) + "\n```\nЭто пример, запрос не выполнялся.")
                    elif scenario in ("dsml-after-unavailable", "dsml-unavailable-plain", "dsml-unavailable-silent", "dsml-unavailable-repeat"):
                        check(database["database_name"] == "11_5_new_fixture" and identifier != "local",
                              "selected_remote_database")
                        if not results:
                            arguments = {"database_id": identifier, "query_id": "dsml-target-probe",
                                         "query_text": "ВЫБРАТЬ 1 КАК КонтрольноеЗначение", "limit": 5, "params": {}}
                            response = completion(None, [{"id": "dsml-real-call", "type": "function", "function": {
                                "name": "execute_query", "arguments": json.dumps(arguments, ensure_ascii=False)}}])
                        else:
                            check((len(results) == 1 or scenario == "dsml-unavailable-repeat") and results[0]["tool_call_id"] == "dsml-real-call",
                                  "exactly_one_real_tool_attempt")
                            result = json.loads(results[-1]["content"])
                            check(result["success"] is False and result["database_id"] == identifier
                                  and result["database_name"] == "11_5_new_fixture", "safe_failure_preserves_source")
                            check("Не удалось выполнить инструмент" in result["data"], "failure_reached_model")
                            if scenario == "dsml-unavailable-repeat" and len(results) == 1:
                                arguments = {"database_id": identifier, "query_id": "repeat-failure",
                                             "query_text": "ВЫБРАТЬ 1 КАК КонтрольноеЗначение", "limit": 5, "params": {}}
                                response = completion(None, [{"id": "dsml-repeat-call", "type": "function", "function": {
                                    "name": "execute_query", "arguments": json.dumps(arguments, ensure_ascii=False)}}])
                            elif scenario in ("dsml-unavailable-silent", "dsml-unavailable-repeat"):
                                response = completion("PLAIN_OK")
                            else:
                                response = completion(markup(identifier, ascii_pipes=True)
                                                      if scenario == "dsml-after-unavailable" else UNAVAILABLE)
                    else:
                        raise AssertionError("unexpected_reproduction_scenario")
                    status = 200
            except Exception as error:
                status, response = 500, {"error": {"message": str(error)}}
                event["fixture_error"] = str(error)
            event.update(response_status=status, response=response)
            with lock:
                events.append(event)
                save()
            raw = json.dumps(response, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            if status == 401:
                self.send_header("WWW-Authenticate", 'Basic realm="synthetic-1c"')
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="dsml-reproduction")
    thread.start()
    try:
        yield events
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        if thread.is_alive():
            raise RuntimeError("Reproduction HTTP server did not stop")
        save()


def require_clean_dsml_events(events):
    if any(event.get("fixture_error") for event in events):
        raise AssertionError("DSML fixture rejected a real request; inspect dsml-fixture-events.json")
    if not all(check["passed"] for event in events for check in event["checks"]):
        raise AssertionError("DSML fixture contract failed")
