# -*- coding: utf-8 -*-
"""
API 转发网关 (API Gateway) v1 —— 不同厂商 API 聚合转发，独立于 AI 搜索网关
============================================================
- GET  /api/channels          → 全部 LLM 渠道健康状态
- POST /api/channels/<id>/key → 保存渠道 key 到 channels.json
- POST /api/channels/<id>/test→ 渠道测速
- GET  /v1/models             → 聚合各渠道可用模型
- POST /v1/chat/completions   → OpenAI 兼容，多渠道路由 + fallback
- GET  /api/health            → 渠道健康

端口：3100（AI 搜索网关在 3000，两者独立）
依赖：channels.py（LLM 渠道层）
"""
import http.server
import socketserver
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

import channels

PORT = int(os.environ.get("API_GATEWAY_PORT", "3100"))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def route_completion(payload):
    """按模型路由到渠道候选链，逐个尝试，返回 (渠道id, response) 或 (None, errors)。"""
    model = payload.get("model", "")
    chain = channels.model_to_chain(model)
    errors = []
    for cid in chain:
        if not channels.key_is_set(cid):
            errors.append(cid + ": 未配置 key")
            continue
        try:
            return cid, channels.chat_completion(cid, payload)
        except urllib.error.HTTPError as he:
            detail = he.read().decode("utf-8", "ignore")[:200]
            errors.append(cid + ": HTTP " + str(he.code) + " " + detail)
        except Exception as e:  # noqa: BLE001
            errors.append(cid + ": " + str(e)[:120])
    return None, errors


def aggregate_models():
    """聚合所有渠道可用模型。"""
    models = []
    h = channels.cached_health_all()
    for cid, st in h.items():
        for m in st.get("models", []) or []:
            models.append({"id": m, "object": "model", "owned_by": cid})
    return models


def stream_openai_passthrough(handler, upstream):
    """把上游 SSE 流原样转发给客户端。收到 [DONE] 即结束（防上游 keep-alive 挂起）。"""
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "close")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    tail = b""
    while True:
        try:
            chunk = upstream.read(2048)
        except Exception:  # noqa: BLE001
            break
        if not chunk:
            break
        handler.wfile.write(chunk)
        handler.wfile.flush()
        tail = (tail + chunk)[-8192:]
        if b"[DONE]" in tail:
            break


class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class GatewayHandler(http.server.BaseHTTPRequestHandler):
    server_version = "API-Gateway/1.0"

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
        elif path == "/api/health":
            self._send_json(200, {"llm": channels.cached_health_all(), "time": time_str()})
        elif path == "/api/channels":
            self._send_json(200, {"channels": channels.cached_health_all()})
        elif path == "/v1/models":
            self._send_json(200, {"object": "list", "data": aggregate_models()})
        elif path == "/v1/sse":
            model = query.get("model", [""])[0]
            prompt = query.get("prompt", [""])[0]
            payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": True}
            self._handle_chat(payload)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        if path.startswith("/api/channels/") and path.endswith("/key"):
            cid = path[len("/api/channels/"):-len("/key")]
            try:
                data = json.loads(body.decode("utf-8") or "{}")
                key = data.get("key", "")
                if key:
                    channels.save_channel_key(cid, key)
                    self._send_json(200, {"status": "ok", "channel": cid})
                else:
                    self._send_json(400, {"error": "key 必填"})
            except Exception as e:  # noqa: BLE001
                self._send_json(500, {"error": str(e)[:120]})
            return
        if path.startswith("/api/channels/") and path.endswith("/test"):
            cid = path[len("/api/channels/"):-len("/test")]
            key = channels.get_key(cid)
            if not key:
                self._send_json(200, {"channel": cid, "reachable": False, "error": "未配置 key"})
                return
            try:
                st = channels.channel_health(cid)
                self._send_json(200, {"channel": cid, "reachable": st.get("reachable", False), "error": st.get("error", "")})
            except Exception as e:  # noqa: BLE001
                self._send_json(200, {"channel": cid, "reachable": False, "error": str(e)[:120]})
            return
        if path in ("/v1/chat/completions", "/chat/completions"):
            self._handle_chat(json.loads(body.decode("utf-8") or "{}"))
            return
        self._send_json(404, {"error": "not found"})

    def _handle_chat(self, payload):
        is_stream = bool(payload.get("stream"))
        cid, result = route_completion(payload)
        if cid is None:
            self._send_json(502, {"error": {"message": "所有渠道均不可用：" + " | ".join(result),
                                            "type": "upstream_error"}})
            return
        try:
            ctype = result.getheader("Content-Type", "application/json")
            if is_stream or "text/event-stream" in ctype:
                stream_openai_passthrough(self, result)
            else:
                self._send(200, "application/json; charset=utf-8", result.read())
        except Exception as e:  # noqa: BLE001
            self._send_json(502, {"error": {"message": "转发失败: " + str(e), "type": "upstream_error"}})

    def log_message(self, *args):  # noqa: D401
        pass


def _read_page(name="api_page.html"):
    try:
        with open(os.path.join(BASE_DIR, "web", name), "r", encoding="utf-8") as f:
            return f.read()
    except Exception:  # noqa: BLE001
        return "<html><body><h2>" + name + " 缺失</h2></body></html>"


def time_str():
    import time
    return time.strftime("%H:%M:%S")


if __name__ == "__main__":
    import time
    print("🌐 [API 转发网关] http://0.0.0.0:" + str(PORT))
    channels.warm_start()
    print("LLM 渠道：")
    for cid, h in channels.cached_health_all().items():
        flag = "✅" if (h["key_set"] and h["reachable"]) else ("🟡" if h["key_set"] else "⚪")
        print("  " + flag + " " + cid + " " + channels.CHANNELS[cid]["name"] + " " + (h.get("error", "") or "")[:40])
    try:
        import heartbeat
        heartbeat.start_heartbeat(
            gateway_id="api_gateway", name="API 转发网关", icon="⚡",
            description="多厂商 LLM 聚合转发（opencode 第一优先）OpenAI 兼容",
            port=PORT)
        print("❤️  心跳上报已启动 (central " + heartbeat.CENTRAL_URL + ")")
    except Exception as e:  # noqa: BLE001
        print("⚠️  心跳上报未启动: " + str(e)[:80])
    server = ThreadedServer(("0.0.0.0", PORT), GatewayHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
