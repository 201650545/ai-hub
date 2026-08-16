# -*- coding: utf-8 -*-
"""
AI 搜索网关 (Search Gateway) v1 —— 多 AI 搜索引擎聚合，独立于 API 转发网关
============================================================
- GET  /aggregate            → 动态交互页（转圈动画 + 引擎状态 + 查看报告）
- GET  /reports/<run_id>/report.html → 报告文件服务
- GET  /api/search_aggregate → 多引擎搜索 → 内容池(JSONL) → LLM 整理 → HTML 报告
- GET  /api/unified_stream   → AI 搜索 SSE（4 引擎并发）
- GET  /api/health           → 引擎会话健康
- GET  /api/history          → 搜索历史
- GET  /api/quota            → 本地额度统计

端口：3000（API 转发网关在 3100，两者独立）
依赖：engines.py（引擎适配层）、content_pool.py（内容聚合）、history.py/quota.py（可降级）
"""
import http.server
import socketserver
import json
import os
import queue
import sys
import threading
import time
import urllib.parse
from pathlib import Path

import engines

PORT = int(os.environ.get("SEARCH_GATEWAY_PORT", "3000"))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.normpath(os.path.join(os.path.dirname(BASE_DIR), "..", "data", "search_gateway"))
HISTORY_FILE = Path(DATA_DIR) / "history.json"

try:  # task_010：对话历史持久化模块（03_共享组件），缺失时降级
    _SHARED = os.path.normpath(os.path.join(BASE_DIR, "..", "..", "03_共享组件"))
    if _SHARED not in sys.path:
        sys.path.insert(0, _SHARED)
    from history import list_conversations as _list_conversations  # noqa: F401
    from quota import get_usage as _get_usage  # noqa: F401
except Exception:  # noqa: BLE001
    _list_conversations = _get_usage = None


def get_history_records():
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def save_history_record(query_str, done_items):
    try:
        recs = get_history_records()
        recs.append({"q": query_str, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                     "items": done_items})
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def clear_history_records():
    if HISTORY_FILE.exists():
        HISTORY_FILE.write_text("[]", encoding="utf-8")


def _read_page(name="hub_page.html"):
    try:
        with open(os.path.join(BASE_DIR, "web", name), "r", encoding="utf-8") as f:
            return f.read()
    except Exception:  # noqa: BLE001
        return "<html><body><h2>" + name + " 缺失</h2></body></html>"


def engine_thread(engine_id, prompt, out_q):
    """单引擎搜索线程：结果放入 out_q。"""
    try:
        result = engines.ask_engine(engine_id, prompt)
        item = {"id": engine_id, "status": result.get("status", "error"),
                "name": engines.ENGINES.get(engine_id, {}).get("name", engine_id),
                "thinking": result.get("thinking", ""), "answer": result.get("answer", ""),
                "refs": result.get("refs", 0), "elapsed": result.get("elapsed", 0),
                "error": result.get("error", "")}
    except Exception as e:  # noqa: BLE001
        item = {"id": engine_id, "status": "error", "name": engine_id,
                "thinking": "", "answer": "", "refs": 0, "elapsed": 0, "error": str(e)[:120]}
    out_q.put(item)
    out_q.put({"id": engine_id, "status": "done"})


def stream_yuanbao_openai(handler, prompt):
    """yuanbao-search 真实检索，以 OpenAI SSE delta 格式回放。"""
    handler.wfile.write(b'data: {"id":"chatcmpl-yuanbao","object":"chat.completion.chunk",'
                        b'"created":%d,"model":"yuanbao-search","choices":[{"index":0,"delta":'
                        b'{"role":"assistant"},"finish_reason":null}]}\n\n' % int(time.time()))
    handler.wfile.flush()
    result = engines.ask_engine("yuanbao", prompt)
    if result["status"] != "ok" or not result["answer"]:
        handler.wfile.write(('data: {"choices":[{"index":0,"delta":{"content":"【元宝检索失败】%s"},"finish_reason":null}]}\n\n'
                             % (result.get("error") or "未知错误")).encode("utf-8"))
    else:
        answer = result["answer"]
        for i in range(0, len(answer), 24):
            delta = json.dumps({"choices": [{"index": 0, "delta": {"content": answer[i:i + 24]},
                                             "finish_reason": None}]}, ensure_ascii=False)
            handler.wfile.write(("data: " + delta + "\n\n").encode("utf-8"))
            handler.wfile.flush()
            time.sleep(0.1)
    handler.wfile.write(b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n')
    handler.wfile.write(b"data: [DONE]\n\n")
    handler.wfile.flush()


class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class GatewayHandler(http.server.BaseHTTPRequestHandler):
    server_version = "Search-Gateway/1.0"

    def _send(self, status, content_type, body: bytes, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status, obj):
        self._send(status, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query)
        if path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", _read_page().encode("utf-8"),
                       extra_headers={"Cache-Control": "no-cache"})
        elif path == "/aggregate":
            self._send(200, "text/html; charset=utf-8", _read_page("aggregate.html").encode("utf-8"))
        elif path.startswith("/reports/"):
            rel = path[len("/reports/"):]
            rp = os.path.normpath(os.path.join(BASE_DIR, "runs", rel))
            if rp.startswith(os.path.normpath(os.path.join(BASE_DIR, "runs"))) and os.path.exists(rp):
                with open(rp, "r", encoding="utf-8") as _f:
                    self._send(200, "text/html; charset=utf-8", _f.read().encode("utf-8"))
            else:
                self._send(404, "text/plain; charset=utf-8", b"report not found")
        elif path == "/health":
            self._send_json(200, {"status": "ok", "service": "search_gateway", "version": "1.0"})
        elif path == "/api/health":
            self._send_json(200, {"engines": engines.health_all(), "time": time.strftime("%H:%M:%S")})
        elif path == "/api/search_aggregate":
            import content_pool
            q = query.get("q", [""])[0] or query.get("prompt", [""])[0]
            if not q:
                self._send_json(400, {"error": "q 必填"})
                return
            req_e = query.get("engines", [""])[0]
            eids = [e.strip() for e in req_e.split(",") if e.strip()] if req_e else None
            try:
                run_id, report_path, records = content_pool.run_search(q, engine_ids=eids)
                self._send_json(200, {
                    "status": "ok", "run_id": run_id, "report": report_path,
                    "engines": [{"provider": r["provider"], "status": r["status"],
                                 "elapsed": round(r.get("elapsed", 0), 1)} for r in records],
                })
            except Exception as ex:  # noqa: BLE001
                self._send_json(500, {"status": "err", "error": str(ex)[:200]})
        elif path == "/api/history":
            if query.get("limit"):
                try:
                    lim = int(query.get("limit", ["20"])[0])
                    self._send_json(200, {"status": "ok", "history": get_history_records()[-lim:]})
                    return
                except Exception:  # noqa: BLE001
                    pass
            self._send_json(200, {"status": "ok", "history": get_history_records()})
        elif path == "/api/quota":
            if _get_usage is None:
                self._send_json(200, {"status": "err", "error": "quota 模块未加载"})
                return
            date = query.get("date", [None])[0] or None
            self._send_json(200, {"status": "ok", "date": date, "usage": _get_usage(date=date)})
        elif path == "/api/unified_stream":
            prompt = query.get("prompt", [""])[0]
            if not prompt:
                self._send_json(400, {"error": "prompt 必填"})
                return
            req_engines = query.get("engines", [""])[0]
            if req_engines:
                active_eids = [e.strip() for e in req_engines.split(",") if e.strip() in engines.ENGINES]
            else:
                active_eids = list(engines.ENGINE_ORDER)
            if not active_eids:
                active_eids = list(engines.ENGINE_ORDER)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            out_q = queue.Queue()
            for idx, eid in enumerate(active_eids):
                def _delayed_launch(e_id, delay):
                    if delay > 0:
                        time.sleep(delay)
                    engine_thread(e_id, prompt, out_q)
                threading.Thread(target=_delayed_launch, args=(eid, idx * 1.5), daemon=True).start()
            remaining = set(active_eids)
            done_items = []
            while remaining:
                try:
                    item = out_q.get(timeout=10)
                except queue.Empty:
                    continue
                eid = item.get("id")
                if item.get("status") == "done":
                    remaining.discard(eid)
                    done_items.append(item)
                self.wfile.write(("data: " + json.dumps(item, ensure_ascii=False) + "\n\n").encode("utf-8"))
                self.wfile.flush()
            if done_items:
                save_history_record(prompt, done_items)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        if path in ("/v1/chat/completions", "/chat/completions"):
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except Exception:  # noqa: BLE001
                payload = {}
            if payload.get("model") == "yuanbao-search":
                prompt = ""
                for m in payload.get("messages", []):
                    if m.get("role") == "user":
                        prompt += (m.get("content") or "")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                stream_yuanbao_openai(self, prompt)
                return
            self._send_json(400, {"error": "search gateway 仅支持 yuanbao-search 模型；LLM 转发请用 API 网关 :3100"})
            return
        self._send_json(404, {"error": "not found"})

    def log_message(self, *args):  # noqa: D401
        pass


if __name__ == "__main__":
    print("🔍 [AI 搜索网关] http://0.0.0.0:" + str(PORT))
    print("引擎会话状态：")
    for eid in engines.ENGINES:
        h = engines.engine_health(eid)
        if h and isinstance(h, dict) and "connected" in h:
            print("  " + ("✅" if h["connected"] else "⚪") + " " + eid)
    server = ThreadedServer(("0.0.0.0", PORT), GatewayHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
