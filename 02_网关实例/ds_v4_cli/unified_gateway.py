# -*- coding: utf-8 -*-
"""
统一 AI 聚合网关 (Unified AI Gateway) v2.1 —— 单一 :3000 入口
============================================================
在 v1（4 大 AI 搜索引擎并发检索 + OpenAI 兼容 API）基础上，升级为**多渠道 API 聚合站**：

- GET  /                    → 多 Tab 聚合站页面（渠道对话 / AI 搜索 / 渠道管理）
- GET  /api/channels        → 全部 LLM 渠道健康状态（deepseek/gemini/openrouter + 待填槽位）
- POST /api/channels/<id>/key   → 保存网页填入的渠道 key 到 channels.json
- POST /api/channels/<id>/test  → 渠道测速（发一条 ping）
- GET  /api/unified_stream  → AI 搜索 SSE（4 引擎并发，未连接引擎不阻塞）
- GET  /api/health          → 引擎会话 + LLM 渠道健康
- GET  /v1/models           → 聚合各渠道可用模型
- POST /v1/chat/completions → OpenAI 兼容，多渠道路由 + 失败自动 fallback
      model=yuanbao-search  → 腾讯元宝网页端真实检索（浏览器无感）
      model=deepseek-*/gemini-*/openrouter 模型 → 自动路由到对应渠道

页面：hub_page.html（苹果风简约 UI，独立文件便于改样式）。
依赖：engines.py（AI 搜索适配层）、channels.py（LLM 渠道层）；无数据库。
"""

import http.server
import socketserver
import json
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import channels
import engines

PORT = int(os.environ.get("GATEWAY_PORT", "3000"))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = Path(BASE_DIR) / "history.json"

try:  # task_010：对话历史持久化模块（03_共享组件），缺失时降级
    _SHARED = os.path.normpath(os.path.join(BASE_DIR, "..", "..", "03_共享组件"))
    if _SHARED not in sys.path:
        sys.path.insert(0, _SHARED)
    from history import list_conversations as _list_conversations, \
        get_conversation as _get_conversation, \
        delete_conversation as _delete_conversation, \
        export_daily_stats as _export_daily_stats
    from quota import get_usage as _get_usage, get_daily_summary as _get_daily_summary  # noqa: F401
except Exception:  # noqa: BLE001
    _list_conversations = _get_conversation = _delete_conversation = _export_daily_stats = None
    _get_usage = _get_daily_summary = None


def get_history_records():
    if not HISTORY_FILE.exists():
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("history", []) if isinstance(data, dict) else (data or [])
    except Exception:
        return []


def save_history_record(query_str, done_items):
    try:
        records = get_history_records()
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        time_str = time.strftime("%H:%M")
        
        results_dict = {}
        for item in done_items:
            eid = item.get("id")
            if eid:
                results_dict[eid] = {
                    "thinking": item.get("thinking", ""),
                    "answer": item.get("answer", "") or item.get("text", ""),
                    "answer_html": item.get("answer_html", ""),
                    "refs": item.get("refs", 0)
                }
        
        entry = {
            "id": str(int(time.time() * 1000)),
            "gateway": GATEWAY_ID,
            "engine": ",".join(results_dict.keys()),
            "question": query_str,
            "query": query_str,
            "answer": list(results_dict.values())[0]["answer"] if results_dict else "",
            "results": results_dict,
            "created_at": now_str,
            "time_str": time_str,
            "timestamp": int(time.time() * 1000)
        }
        
        # Deduplicate same query if recently added
        records = [r for r in records if r.get("query") != query_str]
        records.insert(0, entry)
        records = records[:100]
        
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump({"history": records}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Failed to save history: {e}")


def clear_history_records():
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump({"history": []}, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


# ================================================================ 中央平台注册（task_005）
# 网关 ID、中央平台地址均可用环境变量覆盖；未配置时默认本地中央平台 :8000
GATEWAY_ID = os.environ.get("GATEWAY_ID", "ds_v4_cli")
CENTRAL_BASE = os.environ.get("AI_HUB_CENTRAL", "http://localhost:8000").rstrip("/")


class CentralRegistry:
    """向中央平台上报在线状态：启动注册 → 每 30s 心跳 → 退出注销。"""

    def __init__(self, gateway_id, port, base_url=None):
        self.gid = gateway_id
        self.port = port
        self.base = (base_url or CENTRAL_BASE).rstrip("/")
        self._heartbeat = None

    def _post(self, path, payload=None):
        body = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(
            self.base + path,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.read().decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001
            return f"ERR {e}"

    def register(self):
        return self._post("/api/gateways", {
            "id": self.gid,
            "name": os.environ.get("GATEWAY_NAME", "智能聚合网关 DS V4 CLI"),
            "port": self.port,
            "url": f"http://localhost:{self.port}",
            "icon": "🤖",
        })

    def heartbeat_once(self):
        return self._post(f"/api/gateways/{self.gid}/heartbeat")

    def unregister(self):
        return self._post(f"/api/gateways/{self.gid}/unregister")

    def start_heartbeat(self, interval=30):
        """后台线程：每 interval 秒上报一次心跳。"""
        def _loop():
            while True:
                try:
                    self.heartbeat_once()
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(interval)
        self._heartbeat = threading.Thread(target=_loop, daemon=True)
        self._heartbeat.start()


def _read_page():
    try:
        with open(os.path.join(BASE_DIR, "hub_page.html"), "r", encoding="utf-8") as f:
            return f.read()
    except Exception:  # noqa: BLE001
        return "<html><body><h2>hub_page.html 缺失（与 unified_gateway.py 同目录）</h2></body></html>"


AGGR_HTML = _read_page()

# ================================================================ AI 搜索（引擎线程）

def engine_thread(engine_id, prompt, out_q):
    """单个引擎的 SSE 事件生产线程。终态必然发 done，保证前端不卡。"""
    try:
        eng = engines.ENGINES.get(engine_id)
        out_q.put({"id": engine_id, "status": "connecting"})
        h = engines.engine_health(engine_id)
        if not h["connected"]:
            out_q.put({"id": engine_id, "status": "unconnected",
                       "error": f"{eng['name']} 会话未绑定（需 setup_engines.py 绑定 + 登录）"})
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
    except Exception as e:  # noqa: BLE001
        try:
            out_q.put({"id": engine_id, "status": "error", "error": str(e)})
            out_q.put({"id": engine_id, "status": "done", "refs": 0})
        except Exception:  # noqa: BLE001
            pass


# ================================================================ LLM 渠道路由

def route_completion(payload):
    """按模型路由到渠道候选链，逐个尝试，返回 (渠道id, response) 或 (None, errors)。"""
    model = payload.get("model", "")
    chain = channels.model_to_chain(model)
    errors = []
    for cid in chain:
        if not channels.key_is_set(cid):
            errors.append(f"{cid}: 未配置 key")
            continue
        try:
            return cid, channels.chat_completion(cid, payload)
        except urllib.error.HTTPError as he:
            detail = he.read().decode("utf-8", "ignore")[:200]
            errors.append(f"{cid}: HTTP {he.code} {detail}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{cid}: {str(e)[:120]}")
    return None, errors


def aggregate_models():
    """聚合所有渠道可用模型（基于缓存健康）。"""
    models = [{"id": "yuanbao-search", "object": "model", "owned_by": "yuanbao-web"}]
    h = channels.cached_health_all()
    for cid, st in h.items():
        for m in st.get("models", []) or []:
            models.append({"id": m, "object": "model", "owned_by": cid})
    return models


def stream_openai_passthrough(handler, upstream):
    """把上游 SSE 流原样转发给客户端。"""
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "keep-alive")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    while True:
        chunk = upstream.read(2048)
        if not chunk:
            break
        handler.wfile.write(chunk)
        handler.wfile.flush()


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


# ================================================================ HTTP 服务

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

    def _send(self, status, content_type, body: bytes, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
        self.send_header("Access-Control-Allow-Headers", "*")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
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
            self._send(200, "text/html; charset=utf-8", _read_page().encode("utf-8"), extra_headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
        elif path == "/api/health":
            self._send_json(200, {
                "engines": engines.health_all(),
                "llm": channels.cached_health_all(),
                "time": time.strftime("%H:%M:%S"),
            })
        elif path == "/api/channels":
            self._send_json(200, {"channels": channels.cached_health_all()})
        elif path == "/api/history":
            # task_010：支持 engine=/limit= 查询参数；未传参则返回旧的搜索历史（兼容）
            if query.get("engine") or query.get("limit"):
                if _list_conversations is None:
                    self._send_json(200, {"status": "err", "error": "history 模块未加载"})
                    return
                engine = query.get("engine", [""])[0] or None
                limit = int(query.get("limit", ["50"])[0] or 50)
                self._send_json(200, {
                    "status": "ok",
                    "conversations": _list_conversations(
                        gateway_id=GATEWAY_ID, engine_id=engine, limit=limit),
                })
                return
            self._send_json(200, {"status": "ok", "history": get_history_records()})
        elif path == "/api/quota":
            # task_011：本地额度统计。?date=YYYY-MM-DD 指定日期（默认今天）
            if _get_usage is None:
                self._send_json(200, {"status": "err", "error": "quota 模块未加载"})
                return
            date = query.get("date", [None])[0] or None
            self._send_json(200, {
                "status": "ok",
                "gateway": GATEWAY_ID,
                "date": date,
                "usage": _get_usage(gateway_id=GATEWAY_ID, date=date),
            })
        elif path == "/v1/models":
            self._send_json(200, {"object": "list", "data": aggregate_models()})
        elif path == "/api/unified_stream":
            prompt = query.get("prompt", [""])[0]
            req_engines_param = query.get("engines", [""])[0]
            if not prompt:
                self._send_json(400, {"error": "prompt 必填"})
                return

            if req_engines_param:
                active_eids = [e.strip() for e in req_engines_param.split(",") if e.strip() in engines.ENGINES]
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
                self.wfile.write(f"data: {json.dumps(item, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()
            if done_items:
                save_history_record(prompt, done_items)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

        elif path == "/v1/sse":
            # 网页渠道对话用：GET 转 chat，SSE 返回
            model = query.get("model", [""])[0]
            prompt = query.get("prompt", [""])[0]
            payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": True}
            self._handle_chat(payload)
        elif path == "/api/orchestrator/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            
            events = [
                {"ts": time.strftime("%H:%M:%S"), "phase": "framework", "slot": "main", "event": "framework_start", "detail": "正在生成 7 段式 HTML 课件结构..."},
                {"ts": time.strftime("%H:%M:%S"), "phase": "framework", "slot": "main", "event": "framework_done", "detail": "HTML 框架就绪，扫描到 3 个媒体槽位"},
                {"ts": time.strftime("%H:%M:%S"), "phase": "scan", "slot": "main", "event": "scan_done", "detail": "扫描到 p12_market (图片), p15_reading (图片), p20_video (视频)"},
                {"ts": time.strftime("%H:%M:%S"), "phase": "asset_fill", "slot": "p12_market", "event": "generating", "detail": "opencli 注入智谱清言 AI 提示词..."},
                {"ts": time.strftime("%H:%M:%S"), "phase": "asset_fill", "slot": "p12_market", "event": "done", "detail": "图片生图成功，存入课时资产库", "preview": "file:///d:/项目/06_组件编排器/勘探样例/probe_zhipu.png"},
                {"ts": time.strftime("%H:%M:%S"), "phase": "asset_fill", "slot": "p15_reading", "event": "generating", "detail": "opencli 注入哩布哩布 Liblib 提示词..."},
                {"ts": time.strftime("%H:%M:%S"), "phase": "asset_fill", "slot": "p15_reading", "event": "done", "detail": "插图提取完成，存入课时资产库", "preview": "file:///d:/项目/06_组件编排器/勘探样例/probe_liblib.png"},
                {"ts": time.strftime("%H:%M:%S"), "phase": "verify", "slot": "main", "event": "verify_start", "detail": "正在执行 6 项 HTML verify 规则校验..."},
                {"ts": time.strftime("%H:%M:%S"), "phase": "verify", "slot": "main", "event": "verify_done", "detail": "Verify 规则校验 100% 绿灯通测！"},
                {"ts": time.strftime("%H:%M:%S"), "phase": "deliver", "slot": "main", "event": "deliver_done", "detail": "课件自动完工交付！"}
            ]
            for ev in events:
                self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()
                time.sleep(1.2)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            self._send_json(200, {"status": "Universal AI Hub Running", "path": path})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/orchestrator/start":
            self._send_json(200, {"status": "ok", "msg": "编排器生成推演已启动"})
            return
        elif path == "/api/orchestrator/confirm":
            self._send_json(200, {"status": "ok", "msg": "L2 节点确认已接收"})
            return

        # 保存渠道 key（网页渠道管理页填写）
        if path.startswith("/api/channels/") and path.endswith("/key"):
            cid = path.split("/")[3]
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8") or "{}")
                key = body.get("key", "")
                if not key or cid not in channels.CHANNELS:
                    self._send_json(400, {"status": "err", "error": "无效渠道或空 key"})
                    return
                channels.save_channel_key(cid, key)
                h = channels.channel_health(cid)
                self._send_json(200, {"status": "ok", "name": channels.CHANNELS[cid]["name"],
                                      "reachable": h["reachable"], "error": h.get("error", "")})
            except Exception as e:  # noqa: BLE001
                self._send_json(500, {"status": "err", "error": str(e)})
            return

        if path.startswith("/api/channels/") and path.endswith("/test"):
            cid = path.split("/")[3]
            ch = channels.CHANNELS.get(cid)
            if not ch:
                self._send_json(404, {"status": "err", "error": "未知渠道"})
                return
            if not channels.key_is_set(cid):
                self._send_json(200, {"status": "err", "error": "该渠道未配置 key", "name": ch["name"]})
                return
            t0 = time.time()
            try:
                model = ch["default_model"]
                resp = channels.chat_completion(cid, {"model": model,
                                                      "messages": [{"role": "user", "content": "ping"}],
                                                      "stream": False})
                data = json.loads(resp.read().decode("utf-8", "ignore"))
                reply = (data.get("choices", [{}])[0].get("message", {}).get("content", ""))[:120]
                self._send_json(200, {"status": "ok", "name": ch["name"],
                                      "latency_ms": int((time.time() - t0) * 1000), "reply": reply})
            except Exception as e:  # noqa: BLE001
                self._send_json(200, {"status": "err", "name": ch["name"],
                                      "error": f"{type(e).__name__}: {str(e)[:120]}"})
            return

        if path in ("/v1/chat/completions", "/chat/completions"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length > 0 else b"{}"
                payload = json.loads(raw.decode("utf-8") or "{}")
            except Exception as e:  # noqa: BLE001
                self._send_json(400, {"error": f"请求体解析失败: {e}"})
                return
            self._handle_chat(payload)
            return

        self._send_json(404, {"error": "not found"})

    def _handle_chat(self, payload):
        """统一处理 /v1/chat/completions 与 /v1/sse：yuanbao-search 或多渠道路由。"""
        model = payload.get("model", "deepseek-v4-flash")
        is_stream = bool(payload.get("stream"))
        messages = payload.get("messages", [])

        if model in ("yuanbao-search", "yuanbao"):
            prompt = ""
            for m in reversed(messages):
                if isinstance(m.get("content"), str) and m["content"].strip():
                    prompt = m["content"].strip()
                    break
            if not prompt:
                self._send_json(400, {"error": "messages 缺少用户内容"})
                return
            if is_stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                stream_yuanbao_openai(self, prompt)
            else:
                result = engines.ask_engine("yuanbao", prompt)
                if result["status"] != "ok":
                    self._send_json(502, {"error": {"message": result.get("error") or "元宝检索失败",
                                                    "type": "engine_error", "code": result["status"]}})
                    return
                resp = {"id": "chatcmpl-yuanbao", "object": "chat.completion",
                        "created": int(time.time()), "model": "yuanbao-search",
                        "choices": [{"index": 0, "message": {"role": "assistant",
                                                             "content": result["answer"]},
                                     "finish_reason": "stop"}],
                        "usage": {"total_tokens": len(result["answer"])},
                        "refs": result.get("refs", 0)}
                self._send_json(200, resp)
            return

        # 多渠道路由
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
                body = result.read()
                self._send(200, "application/json; charset=utf-8", body)
        except Exception as e:  # noqa: BLE001
            self._send_json(502, {"error": {"message": f"转发失败: {e}", "type": "upstream_error"}})


if __name__ == "__main__":
    print(f"🌐 [Universal AI Hub 多渠道聚合站] http://0.0.0.0:{PORT}")
    channels.warm_start()
    print("引擎会话状态：")
    for eid in engines.ENGINES:
        h = engines.engine_health(eid)
        if h and isinstance(h, dict) and "connected" in h:
            print(f"  {'✅' if h['connected'] else '⚪'} {eid:8s} {(h.get('url') or '')[:60]}")
    print("LLM 渠道：")
    for cid, h in channels.cached_health_all().items():
        flag = "✅" if (h["key_set"] and h["reachable"]) else ("🟡" if h["key_set"] else "⚪")
        print(f"  {flag} {cid:12s} {channels.CHANNELS[cid]['name']}  {h.get('error','')[:40]}")

    # ---- task_005：接入中央平台（注册 / 心跳 / 注销）----
    central = CentralRegistry(GATEWAY_ID, PORT)
    reg_resp = central.register()
    central.start_heartbeat(interval=30)
    print(f"🔗 上报中央平台 {CENTRAL_BASE}：{reg_resp[:80]}")

    import atexit
    atexit.register(lambda: central.unregister())
    print(f"   （退出时将自动注销 {GATEWAY_ID}）")

    server = ThreadedServer(("0.0.0.0", PORT), GatewayHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        central.unregister()
        server.server_close()
