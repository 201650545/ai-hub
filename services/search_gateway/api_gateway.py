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
- GET  /api/routing           → 读取全部手动路由规则
- PUT  /api/routing           → 设置某模型的手动渠道顺序（"搭积木"）
- DELETE /api/routing?model=  → 清除某模型规则，恢复自动排序
- GET  /api/switch            → 读取总开关状态（enabled）
- PUT  /api/switch            → 开/关总开关（关闭后 /v1/chat 返回 503）
- PUT  /api/channels/<id>/enabled → 渠道启用/停用（停用后路由与模型列表全部跳过）
- GET  /api/gateway-info      → 接入信息（本机/局域网地址、鉴权方式）
- GET  /img/<name>            → web/img/ 静态图片（页面配图）
- GET  /api/usage             → 今日 + 累计用量（按渠道 calls/tokens/errors）
- GET  /api/model-overrides   → 自定义模型 + 隐藏模型配置
- POST /api/model-overrides/custom   → 新增自定义模型 {name, channel, model}
- DELETE /api/model-overrides/custom?name= → 删除自定义模型
- PUT  /api/model-overrides/hidden  → 设置隐藏模型列表 {hidden: [...]}

端口：3100（AI 搜索网关在 3000，两者独立）
依赖：channels.py（LLM 渠道层）、quota.py（本地额度统计）
"""
import http.server
import socketserver
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import re

# :3100 独立记账，与 :3000 搜索网关的 quota 分开（在 import channels 前设环境变量）
os.environ.setdefault("GATEWAY_ID", "api_gateway")

import channels

try:
    from quota import get_usage as _get_usage
except Exception:  # noqa: BLE001
    _get_usage = None

try:
    from rate_limit import ledger as _rate_ledger, events as _rate_events, RateLimitSkip
except Exception:  # noqa: BLE001
    _rate_ledger = None
    _rate_events = None

    class RateLimitSkip(Exception):
        """占位：rate_limit 模块不可用时保持 except 分支可解析。"""

PORT = int(os.environ.get("API_GATEWAY_PORT", "3100"))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_JSON = os.path.join(channels.DATA_DIR, "api_state.json")
EXPIRY_JSON = os.path.join(channels.DATA_DIR, "channel_expiry.json")


def load_state():
    """读取总开关状态。默认开启。"""
    try:
        with open(STATE_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {"enabled": True}


def _write_state(st):
    with open(STATE_JSON, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


def save_state(enabled):
    # 合并写：保留 api_key 等其他字段，避免开关切换把 key 抹掉
    st = load_state()
    st["enabled"] = bool(enabled)
    _write_state(st)


def is_enabled():
    return bool(load_state().get("enabled", True))


# ---------------------------------------------------------------- 网关 API key 鉴权
def get_api_key():
    """网关级 API key（空串 = 未启用鉴权，保持内网全通的旧行为）。"""
    return (load_state().get("api_key") or "").strip()


def save_api_key(key):
    st = load_state()
    st["api_key"] = key
    _write_state(st)


def load_expiry():
    """读取渠道/模型有效期标注。"""
    try:
        with open(EXPIRY_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def save_expiry(data):
    with open(EXPIRY_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _needs_auth(path):
    # 页面本体与静态图不保护；/api/* 与 /v1/* 全部纳入鉴权范围
    if path in ("/", "/index.html"):
        return False
    if path.startswith("/img/"):
        return False
    return True


def usage_summary():
    """今日 + 累计用量。返回 today/today_usage/total/by_channel。"""
    import time as _t
    today = _t.strftime("%Y-%m-%d")
    today_usage = _get_usage(gateway_id="api_gateway", date=today) if _get_usage else {}
    total = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "errors": 0}
    by_channel = {}
    try:
        with open(os.path.join(channels.DATA_DIR, "api_gateway", "quota.json"),
                  "r", encoding="utf-8") as f:
            data = json.load(f)
        for day, chs in (data or {}).items():
            for cid, v in (chs or {}).items():
                v = v or {}
                for k in total:
                    total[k] += int(v.get(k, 0))
                b = by_channel.setdefault(cid, {"calls": 0, "input_tokens": 0,
                                                 "output_tokens": 0, "errors": 0})
                for k in b:
                    b[k] += int(v.get(k, 0))
    except Exception:  # noqa: BLE001
        pass
    return {"today": today, "today_usage": today_usage,
            "total": total, "by_channel": by_channel}


# ---------------------------------------------------------------- 路由日志（线程安全）
_ROUTE_LOG = []
_ROUTE_LOG_LOCK = threading.Lock()
_ROUTE_LOG_MAX = 50  # 最多保留 50 条


def _log_route(entry):
    """记录一次路由决策（调用方填好 entry 后再锁）。"""
    with _ROUTE_LOG_LOCK:
        _ROUTE_LOG.append(entry)
        if len(_ROUTE_LOG) > _ROUTE_LOG_MAX:
            del _ROUTE_LOG[:len(_ROUTE_LOG) - _ROUTE_LOG_MAX]


class _BufferedResponse:
    """已读入内存的上游响应替身（与 HTTPResponse 同形：getheader/read）。"""

    def __init__(self, raw, ctype):
        self._raw, self._ctype = raw, ctype

    def getheader(self, name, default=None):
        return self._ctype if (name or "").lower() == "content-type" else default

    def read(self):
        return self._raw


def _looks_like_shell(raw):
    """空壳响应检测：HTTP 200 但 JSON 无有效 choices（或带 error）→ 该渠道视为失败。"""
    try:
        d = json.loads(raw.decode("utf-8", "ignore"))
    except Exception:  # noqa: BLE001
        return True  # 非 JSON 的 200 也不可信
    return not d.get("choices") or bool(d.get("error"))


def _peek_stream(resp, limit=4096):
    """流式首包验证：读出首批字节检查是否空壳/错误事件。
    返回 (是否通过, 已读字节)。判定保守——半包 JSON / 心跳注释等无法判定时一律放行；
    但「扫完首批、解析出了完整事件、却没有一个事件带 choices」视为错误载荷：
    小红书等渠道把额度耗尽包在非 OpenAI 形状的 200 流里，旧逻辑兜底放行会把它当成功，
    导致统一组每次重试都停在第一个成员上不切换（2026-08-26 fast 组故障转移 bug 根因）。"""
    try:
        buf = resp.read(limit)
    except Exception:  # noqa: BLE001
        return False, b""
    if not buf:
        return False, buf
    text = buf.decode("utf-8", "ignore")
    saw_choices = False
    saw_event = False
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data:
            continue
        if data == "[DONE]":
            if saw_choices:
                continue  # 内容已出现后正常收尾，继续看后续行
            return False, buf  # 首个事件即结束 = 空流
        try:
            obj = json.loads(data)
        except Exception:  # noqa: BLE001
            continue  # 半包判不了 → 看下一行
        if not isinstance(obj, dict):
            continue
        saw_event = True
        if obj.get("error"):
            return False, buf
        if obj.get("choices"):
            return True, buf
    if saw_event and not saw_choices:
        return False, buf  # 完整事件但全无 choices → 错误/控制载荷（如额度尽提示）
    return True, buf


class _PrependResponse:
    """把首包验证时读掉的字节回放、再接续上游的响应包装（配额记录仍走原 _QuotaResponse）。"""

    def __init__(self, head, resp):
        self._head, self._resp = head, resp

    def getheader(self, name, default=None):
        return self._resp.getheader(name, default)

    def read(self, size=-1):
        if self._head:
            if size is None or size < 0:
                out, self._head = self._head + self._resp.read(), b""
                return out
            out, self._head = self._head[:size], self._head[size:]
            return out
        return self._resp.read(size)

    def close(self):
        try:
            self._resp.close()
        except Exception:  # noqa: BLE001
            pass

    def force_finalize(self):
        """透传兜底记账到内层 _QuotaResponse（客户端提前断开时 read 循环不再触发记录）。"""
        f = getattr(self._resp, "force_finalize", None)
        if f:
            try:
                f()
            except Exception:  # noqa: BLE001
                pass


def route_completion(payload):
    """按模型路由到渠道候选链，逐个尝试，返回 (渠道id, response, log_entry) 或 (None, errors, log_entry)。
    模型名自动映射：用户请求 deepseek-v4-flash，转发到 modelscope 时改为
    deepseek-ai/DeepSeek-V4-Flash-0731（该渠道实际模型名），保证上游能识别。"""
    model = payload.get("model", "")
    # 候选链 + 每个渠道对应的实际模型名
    providers = channels.model_providers(model)
    if providers:
        chain = [(p["id"], (p.get("matched_models") or [model])[0]) for p in providers if p.get("reachable")]
    else:
        chain = [(cid, model) for cid in channels.model_to_chain(model)]
    if not chain:  # 规则 pin 的渠道全不可达/未配 key → 兜底 DEFAULT_CHAIN（跳过停用渠道），避免空链 502
        chain = [(cid, channels.CHANNELS[cid].get("default_model", model))
                 for cid in channels.DEFAULT_CHAIN if channels.get_channel_enabled(cid)]

    # 构建路由日志入口（记录 attempted 和 resolved，稍后补 full 信息）
    attempted = [cid for cid, _ in chain]
    log_entry = {
        "ts": time.strftime("%H:%M:%S"),
        "client_model": model,
        "attempted": attempted,
        "resolved_channel": None,
        "resolved_model": None,
        "fallback_count": 0,
        "errors": [],
    }

    errors = []
    for i, (cid, real_model) in enumerate(chain):
        if not channels.key_is_set(cid):
            errors.append(cid + ": 未配置 key")
            continue
        try:
            p2 = dict(payload)
            p2["model"] = real_model  # 映射为该渠道实际模型名
            log_entry["resolved_channel"] = cid
            log_entry["resolved_model"] = real_model
            log_entry["fallback_count"] = i
            resp = channels.chat_completion(cid, p2, route_info=dict(log_entry))
            used_key = getattr(resp, '_key', '')  # P0-2：保存实际使用的 key，避免后续 reassign 丢失
            if not p2.get("stream"):
                # 非流式：读入内存并做空壳检测（如 modelscope 返回 200+choices:null），
                # 壳响应视为该渠道失败，继续尝试下一渠道
                ctype = resp.getheader("Content-Type", "application/json") or "application/json"
                raw = resp.read()
                if _looks_like_shell(raw):
                    channels.mark_shell_failure(cid, real_model, used_key)  # 合成 429 → 熔断提前跳过
                    errors.append(cid + ": 空壳响应（choices 为空），已跳过")
                    log_entry["errors"] = list(errors)
                    continue
                resp = _BufferedResponse(raw, ctype)
                # 验证通过后记录成功（P0-1：延迟到 shell 检测后，避免 200 提前清零 consec429）
                channels.record_channel_success(cid, real_model, used_key)
            else:
                # 流式：首包验证（空流/错误事件 → 换下一渠道），通过则回放包装后透传
                ok, head = _peek_stream(resp)
                if not ok:
                    channels.mark_shell_failure(cid, real_model, used_key)  # 合成 429 → 熔断提前跳过
                    errors.append(cid + ": 流式首包为空壳/错误事件，已跳过")
                    log_entry["errors"] = list(errors)
                    try:
                        resp.close()
                    except Exception:  # noqa: BLE001
                        pass
                    continue
                resp = _PrependResponse(head, resp)
                # 验证通过后记录成功（P0-1：延迟到 peek 后，避免 200 提前清零 consec429）
                channels.record_channel_success(cid, real_model, used_key)
            with _ROUTE_LOG_LOCK:
                _ROUTE_LOG.append(dict(log_entry))
                if len(_ROUTE_LOG) > _ROUTE_LOG_MAX:
                    del _ROUTE_LOG[:len(_ROUTE_LOG) - _ROUTE_LOG_MAX]
            return cid, resp, log_entry
        except urllib.error.HTTPError as he:
            detail = he.read().decode("utf-8", "ignore")[:200]
            errors.append(cid + ": HTTP " + str(he.code) + " " + detail)
        except RateLimitSkip as rle:
            # 95% 提前切换（task_045）：该渠道配额桶满/熔断，走用户顺序里的下一渠道
            errors.append(cid + ": " + str(rle))
            log_entry["errors"] = list(errors)
        except Exception as e:  # noqa: BLE001
            errors.append(cid + ": " + str(e)[:120])

    log_entry["errors"] = errors
    with _ROUTE_LOG_LOCK:
        _ROUTE_LOG.append(dict(log_entry))
        if len(_ROUTE_LOG) > _ROUTE_LOG_MAX:
            del _ROUTE_LOG[:len(_ROUTE_LOG) - _ROUTE_LOG_MAX]
    return None, errors, log_entry


def aggregate_models():
    """聚合所有渠道可用模型（OpenAI 格式）。
    统一走 channels.all_models()：自定义模型别名会加入、隐藏模型会被剔除，
    与前端 /api/models 单一真源一致。owned_by = 支持渠道 id 列表。"""
    return [{"id": m["name"], "object": "model",
             "owned_by": ",".join(p["id"] for p in m["providers"])}
            for m in channels.all_models()]


def stream_openai_passthrough(handler, upstream):
    """把上游 SSE 流原样转发给客户端。收到 [DONE] 即结束（防上游 keep-alive 挂起）；
    上游中途断开（未见 [DONE]）时补发 error 事件 + [DONE]，避免客户端无声截断。"""
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "close")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    tail = b""
    done = False
    while True:
        try:
            chunk = upstream.read(2048)
        except Exception:  # noqa: BLE001
            break
        if not chunk:
            break
        try:
            handler.wfile.write(chunk)
            handler.wfile.flush()
        except Exception:  # noqa: BLE001
            # 客户端提前断开：退出前兜底记账，否则这次调用永远不进用量
            break
        tail = (tail + chunk)[-8192:]
        if b"[DONE]" in tail:
            done = True
            break
    # 兜底记账（幂等）：正常 EOF 已由 read() 记过；中断路径在这里补记
    f = getattr(upstream, "force_finalize", None)
    if f:
        try:
            f()
        except Exception:  # noqa: BLE001
            pass
    if not done:
        try:
            handler.wfile.write(b'data: {"error": {"message": "upstream stream interrupted", "type": "upstream_error"}}\n\n')
            handler.wfile.write(b"data: [DONE]\n\n")
            handler.wfile.flush()
        except Exception:  # noqa: BLE001
            pass


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

    def _require_auth(self, path):
        """网关 API key 守卫：未配置 key（旧行为）或路径豁免 → 放行；
        已配置 key → 要求 Authorization: Bearer <key>，不符回 401。"""
        if not _needs_auth(path):
            return True
        key = get_api_key()
        if not key:
            return True
        if (self.headers.get("Authorization") or "") == "Bearer " + key:
            return True
        self._send_json(401, {"error": {"message": "未授权：此网关已启用 API key，"
                                        "请在请求头携带 Authorization: Bearer <key>",
                                        "type": "unauthorized"}})
        return False

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if not self._require_auth(path):
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        if path == "/api/gateway-key":
            # 设置/变更/关闭网关 API key。已启用 key 时本接口同样受守卫保护（须持旧 key）；
            # 未启用时允许直接设置（首次引导）。key 传空串 = 关闭鉴权。
            try:
                data = json.loads(body.decode("utf-8") or "{}")
            except Exception:  # noqa: BLE001
                self._send_json(400, {"error": "请求体不是合法 JSON"})
                return
            key = data.get("key")
            if key is None or not isinstance(key, str):
                self._send_json(400, {"error": "key 必填（字符串；空串 = 关闭鉴权）"})
                return
            key = key.strip()
            if key and not (8 <= len(key) <= 128):
                self._send_json(400, {"error": "key 长度须为 8–128 字符（或传空串关闭）"})
                return
            save_api_key(key)
            self._send_json(200, {"status": "ok", "auth_required": bool(key)})
            return
        if path == "/api/routing":
            try:
                data = json.loads(body.decode("utf-8") or "{}")
            except Exception:  # noqa: BLE001
                self._send_json(400, {"error": "请求体不是合法 JSON"})
                return
            model = (data.get("model") or "").strip()
            if not model:
                self._send_json(400, {"error": "model 必填"})
                return
            order = data.get("order", [])
            disabled = data.get("disabled", [])
            if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
                self._send_json(400, {"error": "order 必须是字符串数组"})
                return
            if not isinstance(disabled, list) or not all(isinstance(x, str) for x in disabled):
                self._send_json(400, {"error": "disabled 必须是字符串数组"})
                return
            unknown = [c for c in order + disabled if c not in channels.CHANNELS]
            if unknown:
                self._send_json(400, {"error": "未知渠道: " + ", ".join(unknown)})
                return
            # order 与 disabled 均空 → 清除规则（避免存无意义空规则）
            if not order and not disabled:
                channels.save_routing(model, None)
            else:
                channels.save_routing(model, order, disabled)
            self._send_json(200, {"status": "ok", "model": model,
                                  "effective_order": channels.effective_order(model)})
            return
        if path.startswith("/api/channels/") and path.endswith("/enabled"):
            cid = path[len("/api/channels/"):-len("/enabled")]
            if cid not in channels.CHANNELS:
                self._send_json(400, {"error": "未知渠道: " + cid})
                return
            try:
                data = json.loads(body.decode("utf-8") or "{}")
            except Exception:  # noqa: BLE001
                self._send_json(400, {"error": "请求体不是合法 JSON"})
                return
            enabled = bool(data.get("enabled", True))
            channels.set_channel_enabled(cid, enabled)
            channels.invalidate_channel_cache(cid)
            self._send_json(200, {"channel": cid, "enabled": enabled})
            return
        if path.startswith("/api/channels/") and path.endswith("/hidden"):
            cid = path[len("/api/channels/"):-len("/hidden")]
            if cid not in channels.CHANNELS:
                self._send_json(400, {"error": "未知渠道: " + cid})
                return
            try:
                data = json.loads(body.decode("utf-8") or "{}")
            except Exception:  # noqa: BLE001
                self._send_json(400, {"error": "请求体不是合法 JSON"})
                return
            hidden = bool(data.get("hidden", True))
            channels.set_hidden_channel(cid, hidden)
            self._send_json(200, {"channel": cid, "hidden": hidden})
            return
        if path.startswith("/api/channels/") and path.endswith("/models"):
            cid = path[len("/api/channels/"):-len("/models")]
            if cid not in channels.CHANNELS:
                self._send_json(404, {"error": "未知渠道: " + cid})
                return
            try:
                data = json.loads(body.decode("utf-8-sig") or "{}")
            except Exception:  # noqa: BLE001
                self._send_json(400, {"error": "请求体不是合法 JSON"})
                return
            sel = data.get("selected")
            if not isinstance(sel, list) or not all(isinstance(x, str) for x in sel):
                self._send_json(400, {"error": "selected 必须是字符串数组"})
                return
            clean = channels.set_channel_selection(cid, sel)
            self._send_json(200, {"status": "ok", "channel": cid,
                                  "selected": clean, "curated": bool(clean)})
            return
        if path == "/api/switch":
            try:
                data = json.loads(body.decode("utf-8") or "{}")
            except Exception:  # noqa: BLE001
                self._send_json(400, {"error": "请求体不是合法 JSON"})
                return
            if "enabled" not in data:
                self._send_json(400, {"error": "enabled 必填"})
                return
            save_state(bool(data["enabled"]))
            self._send_json(200, {"enabled": is_enabled()})
            return
        if path == "/api/model-overrides/hidden":
            try:
                data = json.loads(body.decode("utf-8") or "{}")
            except Exception:  # noqa: BLE001
                self._send_json(400, {"error": "请求体不是合法 JSON"})
                return
            hidden = data.get("hidden", [])
            if not isinstance(hidden, list) or not all(isinstance(x, str) for x in hidden):
                self._send_json(400, {"error": "hidden 必须是字符串数组"})
                return
            channels.set_hidden_models(hidden)
            self._send_json(200, {"status": "ok", "hidden": channels.load_model_overrides().get("hidden") or []})
            return
        if path == "/api/expiry":
            try:
                data = json.loads(body.decode("utf-8") or "{}")
            except Exception:  # noqa: BLE001
                self._send_json(400, {"error": "请求体不是合法 JSON"})
                return
            # 合并写入：保留原有不在本次提交中的字段
            existing = load_expiry()
            existing.update(data)
            save_expiry(existing)
            self._send_json(200, {"status": "ok", "expiry": load_expiry()})
            return
        self._send_json(404, {"error": "not found"})

    def _handle_images(self, payload):
        """生图转发：/v1/images/generations。模型→渠道路由：
        seedream/seededit → ark（火山方舟）；sensenova-u1* → sensetime（商汤日日新）。"""
        model = (payload.get("model") or "").strip()
        if not model:
            self._send_json(400, {"error": "model 必填"})
            return
        m = model.lower()
        if "seedream" in m or "seededit" in m:
            cid = "ark"
        elif m.startswith("sensenova-u1"):
            cid = "sensetime"
        else:
            self._send_json(400, {"error": "未支持的生图模型: " + model +
                                          "（当前支持 seedream*/seededit*→ark，sensenova-u1*→sensetime）"})
            return
        key = channels.get_key(cid)
        if not key:
            self._send_json(400, {"error": "渠道 " + cid + " 未配置 key"})
            return
        url = channels.CHANNELS[cid]["base_url"].rstrip("/") + "/images/generations"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + key,
                     "User-Agent": channels.CHANNELS[cid].get("ua", "unified-ai-gateway/1.0")},
            method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=300)
            raw = resp.read()
            self.send_response(resp.status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("X-Resolved-Channel", cid)
            self.send_header("X-Resolved-Model", model)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            try:
                quota.record_call("api_gateway", cid, model, 0, 0, True)
            except Exception:  # noqa: BLE001
                pass
        except urllib.error.HTTPError as he:
            try:
                body = json.loads(he.read().decode("utf-8", "ignore") or "{}")
            except Exception:  # noqa: BLE001
                body = {"error": {"message": "upstream HTTP " + str(he.code)}}
            self._send_json(he.code, body)
        except Exception as e:  # noqa: BLE001
            self._send_json(502, {"error": str(e)[:200]})

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query)
        if not self._require_auth(path):
            return
        if path.startswith("/api/channels/") and path.count("/") == 3:
            cid = path[len("/api/channels/"):]
            ok = channels.delete_custom_channel(cid)
            if not ok:
                self._send_json(400, {"error": "只能删除自定义渠道（内置渠道不可删）: " + cid})
                return
            self._send_json(200, {"status": "deleted", "channel": cid})
            return
        if path == "/api/routing":
            model = (query.get("model", [""])[0] or "").strip()
            if not model:
                self._send_json(400, {"error": "model 必填"})
                return
            channels.save_routing(model, None)
            self._send_json(200, {"status": "cleared", "model": model,
                                  "effective_order": channels.effective_order(model)})
            return
        if path == "/api/model-overrides/custom":
            name = (query.get("name", [""])[0] or "").strip()
            if not name:
                self._send_json(400, {"error": "name 必填"})
                return
            channels.remove_custom_model(name)
            self._send_json(200, {"status": "removed", "name": name})
            return
        if path == "/api/unified":
            name = (query.get("name", [""])[0] or "").strip()
            if not name:
                self._send_json(400, {"error": "name 必填"})
                return
            channels.delete_unified_model(name)
            # 顺手清掉该模型的编排规则，避免残留孤儿规则
            channels.save_routing(channels.normalize_model_name(name), None)
            self._send_json(200, {"status": "removed", "name": channels.normalize_model_name(name)})
            return
        self._send_json(404, {"error": "not found"})

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query)
        if not self._require_auth(path):
            return
        if path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", _read_page().encode("utf-8"),
                       extra_headers={"Cache-Control": "no-cache"})
        elif path == "/api/health":
            self._send_json(200, {"llm": channels.cached_health_all(),
                                  "hidden": channels.hidden_channels_meta(),
                                  "time": time_str()})
        elif path == "/api/channels":
            self._send_json(200, {"channels": channels.cached_health_all()})
        elif path.startswith("/api/channels/") and path.endswith("/models"):
            cid = path[len("/api/channels/"):-len("/models")]
            if cid not in channels.CHANNELS:
                self._send_json(404, {"error": "未知渠道: " + cid})
                return
            ch = channels.CHANNELS.get(cid, {})
            st = channels.cached_health_all().get(cid, {})
            catalog = sorted(st.get("models") or [])
            sel = channels.get_channel_selection(cid) or []
            sset = set(sel)
            self._send_json(200, {
                "channel": cid,
                "name": ch.get("name", cid),
                "icon": ch.get("icon", "🤖"),
                "billing_tag": ch.get("billing_tag", ""),
                "enabled": st.get("enabled", True),
                "reachable": st.get("reachable", False),
                "selected": sel,
                "all": catalog,
                "unselected": [m for m in catalog if m not in sset],
            })
        elif path == "/v1/models":
            self._send_json(200, {"object": "list", "data": aggregate_models()})
        elif path == "/api/models":
            self._send_json(200, {"models": channels.all_models()})
        elif path == "/api/model_providers":
            model = query.get("model", [""])[0]
            full = query.get("full", ["0"])[0] in ("1", "true", "yes")
            self._send_json(200, {"model": model, "providers": channels.model_providers(model, full=full)})
        elif path == "/api/routing":
            self._send_json(200, {"routing": channels.load_routing().get("routing", {})})
        elif path == "/api/switch":
            self._send_json(200, {"enabled": is_enabled()})
        elif path == "/api/model-overrides":
            ov = channels.load_model_overrides()
            self._send_json(200, {"custom": ov.get("custom") or [],
                                  "hidden": ov.get("hidden") or []})
        elif path == "/api/unified":
            self._send_json(200, {"unified": channels.load_unified()})
        elif path == "/api/unified/suggest":
            q = query.get("q", [""])[0]
            self._send_json(200, {"q": q, "suggest": channels.unified_suggest(q)})
        elif path == "/api/usage":
            if _get_usage is None:
                self._send_json(503, {"error": "quota 模块不可用"})
            else:
                self._send_json(200, usage_summary())
        elif path == "/api/rate-limits":
            # 渠道限流准入台账（task_045 v2）：调研上限 + 实测 + 状态机 + 翻转事件
            if _rate_ledger is None:
                self._send_json(503, {"error": "rate_limit 模块不可用"})
            else:
                self._send_json(200, {"channels": _rate_ledger(),
                                      "events": (_rate_events() or []) if _rate_events else []})
        elif path == "/api/expiry":
            self._send_json(200, load_expiry())
        elif path == "/api/gateway-info":
            self._send_json(200, gateway_info())
        elif path.startswith("/img/"):
            _serve_img(self, path)
        elif path == "/api/route-log":
            with _ROUTE_LOG_LOCK:
                self._send_json(200, {"log": list(_ROUTE_LOG)})
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
        if not self._require_auth(path):
            return
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
            if cid in channels.NO_TEST_CHANNELS:
                self._send_json(200, {"channel": cid, "reachable": True, "error": "禁测（贵）· 不发起测试", "no_test": True})
                return
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
        if path == "/api/model-overrides/custom":
            try:
                data = json.loads(body.decode("utf-8") or "{}")
            except Exception:  # noqa: BLE001
                self._send_json(400, {"error": "请求体不是合法 JSON"})
                return
            name = (data.get("name") or "").strip()
            cid = (data.get("channel") or "").strip()
            model = (data.get("model") or "").strip()
            if not name or not model:
                self._send_json(400, {"error": "name 与 model 必填"})
                return
            if cid not in channels.CHANNELS:
                self._send_json(400, {"error": "未知渠道: " + cid})
                return
            if not channels.key_is_set(cid):
                self._send_json(400, {"error": "该渠道未配置 key，请先到渠道管理配置"})
                return
            channels.add_custom_model(name, cid, model)
            self._send_json(200, {"status": "ok", "name": name, "channel": cid, "model": model})
            return
        if path in ("/v1/chat/completions", "/chat/completions"):
            try:
                self._handle_chat(json.loads(body.decode("utf-8-sig") or "{}"))
            except Exception:  # noqa: BLE001
                self._send_json(400, {"error": "请求体不是合法 JSON"})
            return
        if path in ("/v1/images/generations", "/images/generations"):
            try:
                self._handle_images(json.loads(body.decode("utf-8-sig") or "{}"))
            except Exception:  # noqa: BLE001
                self._send_json(400, {"error": "请求体不是合法 JSON"})
            return
        if path == "/api/unified":
            try:
                data = json.loads(body.decode("utf-8") or "{}")
            except Exception:  # noqa: BLE001
                self._send_json(400, {"error": "请求体不是合法 JSON"})
                return
            name = (data.get("name") or "").strip()
            members = data.get("members")
            display = (data.get("display") or "").strip() or None
            if not name:
                self._send_json(400, {"error": "name 必填"})
                return
            if not isinstance(members, dict) or not all(
                    isinstance(k, str) and isinstance(v, str) for k, v in members.items()):
                self._send_json(400, {"error": "members 必须是 {渠道id: 上游模型名} 对象"})
                return
            unknown = [c for c in members if c not in channels.CHANNELS]
            if unknown:
                self._send_json(400, {"error": "未知渠道: " + ", ".join(unknown)})
                return
            try:
                entry = channels.set_unified_model(name, members, display)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, {"status": "ok", "name": channels.normalize_model_name(name),
                                  "entry": entry})
            return
        if path == "/api/channels":
            # 新增自定义渠道：写 channels.json custom_channels，免改代码、免重启
            try:
                data = json.loads(body.decode("utf-8") or "{}")
            except Exception:  # noqa: BLE001
                self._send_json(400, {"error": "请求体不是合法 JSON"})
                return
            cid = (data.get("id") or "").strip().lower()
            base = (data.get("base_url") or "").strip().rstrip("/")
            name = (data.get("name") or "").strip() or cid
            billing_type = data.get("billing_type") or "free"
            if not cid or not base:
                self._send_json(400, {"error": "id 与 base_url 必填"})
                return
            if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", cid):
                self._send_json(400, {"error": "id 只能用小写字母/数字/点/杠/下划线，且以字母或数字开头"})
                return
            if cid in channels.CHANNELS:
                self._send_json(400, {"error": "渠道 id 已存在: " + cid})
                return
            models = data.get("models")
            if models is not None and (not isinstance(models, list) or not all(isinstance(m, str) for m in models)):
                self._send_json(400, {"error": "models 必须是字符串数组"})
                return
            definition = {
                "name": name,
                "provider": (data.get("provider") or "").strip() or name,
                "billing_type": billing_type,
                "billing_tag": (data.get("billing_tag") or "").strip()
                               or ("🟢 免费" if billing_type != "paid" else "🔴 付费扣费"),
                "icon": (data.get("icon") or "🤖").strip()[:8],
                "base_url": base,
                "env_key": (data.get("env_key") or "").strip(),
                "proxy": (data.get("proxy") or "").strip(),
                "free": billing_type != "paid",
                "speed": data.get("speed") or "medium",
                "default_model": (data.get("default_model") or "").strip(),
                "models": models if models is not None else [],
                "note": (data.get("note") or "").strip(),
            }
            mp = (data.get("models_path") or "").strip()
            if mp:
                definition["models_path"] = mp
            channels.save_custom_channel(cid, definition)
            key = (data.get("key") or "").strip()
            if key:
                channels.save_channel_key(cid, key)
            self._send_json(200, {"status": "ok", "channel": cid})
            return
        self._send_json(404, {"error": "not found"})

    def _handle_chat(self, payload):
        if not is_enabled():
            self._send_json(503, {"error": {"message": "API 转发网关已暂停（总开关关闭）",
                                            "type": "gateway_paused"}})
            return
        is_stream = bool(payload.get("stream"))
        cid, result, log_entry = route_completion(payload)
        if cid is None:
            self._send_json(502, {"error": {"message": "所有渠道均不可用：" + " | ".join(result),
                                            "type": "upstream_error"}})
            return
        try:
            ctype = result.getheader("Content-Type", "application/json")
            if is_stream or "text/event-stream" in ctype:
                stream_openai_passthrough(self, result)
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                # 路由透明头
                ri = log_entry or {}
                self.send_header("X-Routed-Channel", ri.get("resolved_channel", ""))
                self.send_header("X-Resolved-Model", ri.get("resolved_model", ""))
                self.send_header("X-Fallback-Count", str(ri.get("fallback_count", 0)))
                self.end_headers()
                self.wfile.write(result.read())
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


def _lan_ip():
    """局域网出口 IP（UDP connect 不发包，只取路由源地址）。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:  # noqa: BLE001
        return "127.0.0.1"
    finally:
        s.close()


def gateway_info():
    """接入信息：本机/局域网地址与鉴权方式。key 永不回显，只报告是否启用。"""
    need = bool(get_api_key())
    return {"port": PORT,
            "local_url": f"http://localhost:{PORT}",
            "lan_url": f"http://{_lan_ip()}:{PORT}",
            "chat_path": "/v1/chat/completions",
            "models_path": "/v1/models",
            "auth_required": need,
            "auth_header": "Authorization: Bearer <你的网关 key>" if need else "",
            "api_key": ""}


_IMG_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml"}


def _serve_img(self, path):
    """web/img/ 静态图片（允许 styles/ brand/ 等子目录；normpath + 前缀校验防目录穿越）。"""
    rel = urllib.parse.unquote(path[len("/img/"):]).replace("\\", "/").lstrip("/")
    base = os.path.normpath(os.path.join(BASE_DIR, "web", "img"))
    fp = os.path.normpath(os.path.join(base, rel))
    if not fp.startswith(base + os.sep) or not os.path.isfile(fp):
        self._send_json(404, {"error": "not found"})
        return
    ext = os.path.splitext(fp)[1].lower()
    with open(fp, "rb") as f:
        self._send(200, _IMG_TYPES.get(ext, "application/octet-stream"), f.read(),
                   extra_headers={"Cache-Control": "max-age=3600"})


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
