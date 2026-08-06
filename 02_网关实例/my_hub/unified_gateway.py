# -*- coding: utf-8 -*-
"""
统一 AI 聚合网关 (Unified AI Gateway) — 实例代码
"""

import http.server
import socketserver
import json
import os
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import channels
import engines

PORT = 3001
GATEWAY_NAME = "my_hub"
DESCRIPTION = "测试 AI 网关"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _read_page():
    try:
        with open(os.path.join(BASE_DIR, "hub_page.html"), "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "<html><body><h2>hub_page.html 缺失</h2></body></html>"


def register_to_central_platform():
    """向中央平台自动注册本网关。"""
    try:
        data = json.dumps({
            "id": GATEWAY_NAME,
            "name": GATEWAY_NAME,
            "port": PORT,
            "description": DESCRIPTION,
            "url": f"http://localhost:{PORT}"
        }).encode("utf-8")
        req = urllib.request.Request(
            "http://localhost:8000/api/gateways",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            print(f"✅ 已成功向中央平台注册网关: {GATEWAY_NAME} (端口 {PORT})")
    except Exception as e:
        print(f"⚠️ 中央平台自动注册提示: {e} (如中央平台未启动可忽略)")


def engine_thread(engine_id, prompt, out_q):
    try:
        eng = engines.ENGINES.get(engine_id)
        out_q.put({"id": engine_id, "status": "connecting"})
        h = engines.engine_health(engine_id)
        if not h["connected"]:
            out_q.put({"id": engine_id, "status": "unconnected",
                       "error": f"{eng['name']} 会话未绑定"})
            out_q.put({"id": engine_id, "status": "done", "refs": 0})
            return
        result = engines.ask_engine(engine_id, prompt, progress=lambda m: out_q.put(
            {"id": engine_id, "status": "progress", "msg": m}))
        if result["status"] != "ok" or not result["answer"]:
            out_q.put({"id": engine_id, "status": "error", "error": result.get("error") or "检索失败"})
            out_q.put({"id": engine_id, "status": "done", "refs": 0})
            return
        answer = result["answer"]
        for i in range(0, len(answer), 30):
            out_q.put({"id": engine_id, "status": "stream", "chunk": answer[i:i + 30]})
            time.sleep(0.12)
        out_q.put({
            "id": engine_id,
            "status": "done",
            "thinking": result.get("thinking", ""),
            "answer": result.get("answer", ""),
            "answer_html": result.get("answer_html", ""),
            "refs": result.get("refs", 0)
        })
    except Exception as e:
        try:
            out_q.put({"id": engine_id, "status": "error", "error": str(e)})
            out_q.put({"id": engine_id, "status": "done", "refs": 0})
        except Exception:
            pass


class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class GatewayHandler(http.server.BaseHTTPRequestHandler):
    server_version = "UnifiedAI/2.1"

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass

    def _send(self, status, content_type, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status, obj):
        self._send(status, "application/json; charset=utf-8",
                   json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", _read_page().encode("utf-8"))
        elif path == "/api/health":
            self._send_json(200, {
                "gateway": GATEWAY_NAME,
                "port": PORT,
                "engines": engines.health_all(),
                "llm": channels.cached_health_all(),
                "time": time.strftime("%H:%M:%S"),
            })
        elif path == "/api/unified_stream":
            prompt = query.get("prompt", [""])[0]
            if not prompt:
                self._send_json(400, {"error": "prompt 必填"})
                return
            active_eids = list(engines.ENGINE_ORDER)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            out_q = queue.Queue()
            for eid in active_eids:
                threading.Thread(target=engine_thread, args=(eid, prompt, out_q), daemon=True).start()
            remaining = set(active_eids)
            while remaining:
                try:
                    item = out_q.get(timeout=10)
                except queue.Empty:
                    continue
                eid = item.get("id")
                if item.get("status") == "done":
                    remaining.discard(eid)
                self.wfile.write(f"data: {json.dumps(item, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            self._send_json(200, {"status": f"Gateway {GATEWAY_NAME} Running", "port": PORT})


if __name__ == "__main__":
    print(f"🌐 [{GATEWAY_NAME}] 网关服务启动中: http://0.0.0.0:{PORT}")
    register_to_central_platform()
    channels.warm_start()
    server = ThreadedServer(("0.0.0.0", PORT), GatewayHandler)
    server.serve_forever()
