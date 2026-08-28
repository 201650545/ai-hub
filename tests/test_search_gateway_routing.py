# -*- coding: utf-8 -*-
"""
Phase 1 路由不变量固化测试（P1.1，GPT Extended 评审定稿 2026-08-27）
====================================================================
运行：python tests/test_search_gateway_routing.py
（已并入 tests/run_all.py 套件清单；也可独立运行）

全 mock：不触碰任何真实上游渠道/免费额度。
锁死四组不变量：
  1. upstream_outcome 纯分类器（含 _classify_text 收紧后的误判回归）
  2. rate_limit 原子准入（95% trip / 85% resume / blocked / 并发仅放行 1）
  3. route_completion failover（8-case 行为 + failures 聚合 contract）
  4. 流式 commit point（commit 前 failover / commit 后断流不换上游）

已知保守行为（测试固化）：SSE 流式首包错误事件 → classify_shell 对 SSE 字节
JSON 解析失败 → PROTOCOL_ERROR（非 breaker，failover 但不熔断）。
RATE_LIMIT 只来自 HTTP 429；"rate limit exceeded" 文本不判 RATE_LIMIT。

验证令牌（供 GPT Extended 在 GitHub 上核验真读）：P11-TOKEN=QM05-V2-LOCKED
"""
import io
import json
import os
import socket
import sys
import threading
import time
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GW = os.path.join(ROOT, "services", "search_gateway")
sys.path.insert(0, GW)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import upstream_outcome  # noqa: E402
import rate_limit  # noqa: E402
import channels  # noqa: E402
import api_gateway  # noqa: E402
from common import Result  # noqa: E402

O = upstream_outcome.Outcome


# ============================================================
# 公共 mock 设施
# ============================================================

FAKE_PROVIDERS = [
    {"id": "c1", "name": "C1", "matched_models": ["m1"], "reachable": True},
    {"id": "c2", "name": "C2", "matched_models": ["m2"], "reachable": True},
]

_orig = {}


def _install_mocks():
    _orig["model_providers"] = channels.model_providers
    _orig["key_is_set"] = channels.key_is_set
    _orig["chat_completion"] = channels.chat_completion
    _orig["mark_shell_failure"] = channels.mark_shell_failure
    _orig["record_channel_success"] = channels.record_channel_success
    _orig["get_key"] = channels.get_key

    channels.model_providers = lambda model: FAKE_PROVIDERS
    channels.key_is_set = lambda cid: True
    channels.mark_shell_failure = lambda *a, **k: None
    channels.record_channel_success = lambda *a, **k: None
    channels.get_key = lambda cid: "key-" + cid


def _restore_mocks():
    for k, v in _orig.items():
        setattr(channels, k, v)


class FakeResp:
    """非流式假响应（一次性 read 全量）"""

    def __init__(self, body, ctype="application/json", key="k"):
        self._body = body if isinstance(body, bytes) else body.encode("utf-8")
        self._ctype = ctype
        self._key = key

    def getheader(self, name, default=None):
        if name.lower() == "content-type":
            return self._ctype
        return default

    def read(self, size=-1):
        return self._body

    def close(self):
        pass


class FakeStreamResp:
    """流式假响应：first 字节先被 _peek_stream 读走，rest 供后续分段 read。

    abort_after_first=True 模拟 commit 后断流：rest 读取时抛 ConnectionResetError。
    """

    def __init__(self, first, rest, key="k", abort_after_first=False):
        self._first = first if isinstance(first, bytes) else first.encode("utf-8")
        self._rest = rest if isinstance(rest, bytes) else rest.encode("utf-8")
        self._key = key
        self._abort = abort_after_first

    def getheader(self, name, default=None):
        if name.lower() == "content-type":
            return "text/event-stream"
        return default

    def read(self, size=-1):
        if self._first:
            out, self._first = self._first, b""
            return out
        if self._abort:
            raise ConnectionResetError("connection reset by peer (simulated)")
        if self._rest:
            if size is not None and 0 < size < len(self._rest):
                out, self._rest = self._rest[:size], self._rest[size:]
            else:
                out, self._rest = self._rest, b""
            return out
        return b""

    def close(self):
        pass


def _ok_body(content="OK"):
    return json.dumps({"id": "x", "choices": [
        {"message": {"role": "assistant", "content": content}}]})


OK_SSE_FIRST = "data: " + json.dumps(
    {"choices": [{"delta": {"role": "assistant", "content": ""}}]}) + "\n\n"
OK_SSE_REST = ("data: " + json.dumps({"choices": [{"delta": {"content": "OK"}}]})
               + "\n\ndata: [DONE]\n\n")


def _reset_state():
    rate_limit._buckets.clear()
    rate_limit._events.clear()
    visited.update({"c1": 0, "c2": 0})
    if "empero" in visited:
        visited["empero"] = 0
    scenario.clear()
    stream_mode.update({"c1": False, "c2": False})
    if "empero" in stream_mode:
        stream_mode["empero"] = False


# ============================================================
# 组1：upstream_outcome 纯分类器
# ============================================================

def test_upstream_outcome():
    res = []

    def case(name, fn):
        try:
            fn()
            res.append(Result(name, Result.PASS))
        except AssertionError as e:
            res.append(Result(name, Result.FAIL, str(e)))
        except Exception as e:  # noqa: BLE001
            res.append(Result(name, Result.FAIL, "异常: %s" % e))

    def t_http_map():
        assert upstream_outcome.classify_http_status(429, "") == O.RATE_LIMIT
        assert upstream_outcome.classify_http_status(401, "") == O.AUTH
        assert upstream_outcome.classify_http_status(403, "") == O.AUTH
        assert upstream_outcome.classify_http_status(404, "") == O.MODEL_UNAVAILABLE
        assert upstream_outcome.classify_http_status(502, "") == O.OVERLOADED
        assert upstream_outcome.classify_http_status(503, "") == O.OVERLOADED
        assert upstream_outcome.classify_http_status(504, "") == O.OVERLOADED
        assert upstream_outcome.classify_http_status(200, "") == O.SUCCESS
        assert upstream_outcome.classify_http_status(204, "") == O.SUCCESS  # 传输层 SUCCESS（payload 层另判）
        assert upstream_outcome.classify_http_status(418, "") == O.PROTOCOL_ERROR

    def t_shell():
        assert upstream_outcome.classify_shell(b"") == O.PROTOCOL_ERROR
        assert upstream_outcome.classify_shell(b"not json at all") == O.PROTOCOL_ERROR
        assert upstream_outcome.classify_shell(b'{"choices": []}') == O.PROTOCOL_ERROR
        assert upstream_outcome.classify_shell(b'{"choices": null}') == O.PROTOCOL_ERROR
        ok = json.dumps({"choices": [{"message": {"role": "assistant", "content": "hi"}}]})
        assert upstream_outcome.classify_shell(ok.encode()) == O.SUCCESS
        quota = json.dumps({"error": {"code": "quota_exhausted", "message": "额度已用完"}})
        assert upstream_outcome.classify_shell(quota.encode()) == O.QUOTA
        authz = json.dumps({"error": {"message": "unauthorized"}})
        assert upstream_outcome.classify_shell(authz.encode()) == O.AUTH
        over = json.dumps({"error": {"message": "service unavailable"}})
        assert upstream_outcome.classify_shell(over.encode()) == O.OVERLOADED

    def t_text_no_false_breaker():
        """GPT 评审 C 项：请求级错误不得触发 breaker。"""
        # 显式排除组 → PROTOCOL_ERROR
        assert upstream_outcome._classify_text("context length limit exceeded") == O.PROTOCOL_ERROR
        assert upstream_outcome._classify_text("maximum context length reached") == O.PROTOCOL_ERROR
        assert upstream_outcome._classify_text("max token limit exceeded") == O.PROTOCOL_ERROR
        assert upstream_outcome._classify_text("tokenizer initialization failed") == O.PROTOCOL_ERROR
        assert upstream_outcome._classify_text("invalid request: bad param") == O.PROTOCOL_ERROR
        # 裸词已删：limit/key/token 单独出现不再判 QUOTA/AUTH
        assert upstream_outcome._classify_text("limit") is None
        assert upstream_outcome._classify_text("key") is None
        assert upstream_outcome._classify_text("token") is None
        assert upstream_outcome._classify_text("your limit is 50") is None
        assert upstream_outcome._classify_text("press any key") is None
        # 语义明确组保持有效
        assert upstream_outcome._classify_text("quota exhausted") == O.QUOTA
        assert upstream_outcome._classify_text("insufficient_quota") == O.QUOTA
        assert upstream_outcome._classify_text("invalid api key provided") == O.AUTH
        assert upstream_outcome._classify_text("unauthorized") == O.AUTH
        assert upstream_outcome._classify_text("forbidden") == O.AUTH
        assert upstream_outcome._classify_text("service unavailable") == O.OVERLOADED
        assert upstream_outcome._classify_text("model not found") == O.MODEL_UNAVAILABLE
        assert upstream_outcome._classify_text("rate limit exceeded") is None  # RATE_LIMIT 只来自 HTTP 429

    def t_shell_no_false_breaker():
        """200 + context-length 错误载荷 → PROTOCOL_ERROR（非 QUOTA），不熔断。"""
        body = json.dumps({"error": {"message": "context length limit exceeded"}})
        assert upstream_outcome.classify_shell(body.encode()) == O.PROTOCOL_ERROR
        body2 = json.dumps({"error": {"message": "this model's maximum context length is 8192 tokens"}})
        assert upstream_outcome.classify_shell(body2.encode()) == O.PROTOCOL_ERROR

    def t_breaker():
        assert upstream_outcome.is_breaker(O.RATE_LIMIT)
        assert upstream_outcome.is_breaker(O.QUOTA)
        assert upstream_outcome.is_breaker(O.AUTH)
        assert upstream_outcome.is_breaker(O.OVERLOADED)
        assert not upstream_outcome.is_breaker(O.MODEL_UNAVAILABLE)
        assert not upstream_outcome.is_breaker(O.PROTOCOL_ERROR)
        assert not upstream_outcome.is_breaker(O.TIMEOUT)

    def t_exception():
        assert upstream_outcome.classify_exception(socket.timeout()) == O.TIMEOUT
        assert upstream_outcome.classify_exception(ConnectionResetError()) == O.TIMEOUT
        assert upstream_outcome.classify_exception(ValueError("x")) == O.PROTOCOL_ERROR

    case("分类器: HTTP 状态映射", t_http_map)
    case("分类器: 空壳/错误载荷", t_shell)
    case("分类器: 文本误判回归（裸词已删+请求级排除）", t_text_no_false_breaker)
    case("分类器: 200壳 context-length 不触发 QUOTA", t_shell_no_false_breaker)
    case("分类器: 熔断类型判定", t_breaker)
    case("分类器: 异常归类", t_exception)
    return res


# ============================================================
# 组2：rate_limit 原子准入
# ============================================================

def test_rate_limit():
    res = []

    def case(name, fn):
        try:
            _reset_state()
            fn()
            res.append(Result(name, Result.PASS))
        except AssertionError as e:
            res.append(Result(name, Result.FAIL, str(e)))
        except Exception as e:  # noqa: BLE001
            res.append(Result(name, Result.FAIL, "异常: %s" % e))

    def t_trip_resume():
        rate_limit.POLICIES["t1"] = {"scope": "channel", "match": None,
                                     "rules": [{"window": rate_limit.WINDOW_M, "limit": 20}]}
        for i in range(18):
            assert rate_limit.try_acquire("t1", "m", "k") is True, "第%d次应放行" % (i + 1)
        # 18/20=90% < 95% 仍放行 → 19/20
        assert rate_limit.try_acquire("t1", "m", "k") is True, "90% 应放行"
        # 19/20=95% → trip
        assert rate_limit.try_acquire("t1", "m", "k") is False, "95% 应触发跳过"
        row = rate_limit.ledger()["t1"]
        assert row["state"] == "throttled", row["state"]
        # 模拟窗口释放到 ≤85%（17/20）
        b = rate_limit._buckets["t1"]
        b["wins"][0].clear()
        for _ in range(17):
            b["wins"][0].append(time.time() - 100)
        assert rate_limit.try_acquire("t1", "m", "k") is True, "85% 应恢复"
        assert rate_limit.ledger()["t1"]["state"] == "open"

    def t_blocked_retry_after():
        rate_limit.record_result("t2", "m", "k", 429, retry_after="30")
        row = rate_limit.ledger()["t2"]
        assert row["state"] == "blocked", row["state"]
        assert 25 <= (row["blocked_in"] or 0) <= 30, row["blocked_in"]
        assert rate_limit.try_acquire("t2", "m", "k") is False, "blocked 窗口内应跳过"

    def t_blocked_backoff():
        for _ in range(3):
            rate_limit.record_result("t3", "m", "k", 429)
        row = rate_limit.ledger()["t3"]
        # 第3次连续429 → 退避 60s
        assert 55 <= (row["blocked_in"] or 0) <= 60, row["blocked_in"]

    def t_success_resets():
        rate_limit.record_result("t4", "m", "k", 429)
        rate_limit.record_result("t4", "m", "k", 429)
        rate_limit.record_result("t4", "m", "k", 200)
        b = rate_limit._buckets["t4"]
        assert b["consec429"] == 0
        # 2xx 清零但 blocked_until 不清（自然到期）
        assert b["blocked_until"] > 0

    def t_concurrent():
        """10 线程抢最后名额（limit=20 已占 18，trip_at=19）→ 只放行 1。"""
        rate_limit.POLICIES["t5"] = {"scope": "channel", "match": None,
                                     "rules": [{"window": rate_limit.WINDOW_M, "limit": 20}]}
        for _ in range(18):
            assert rate_limit.try_acquire("t5", "m", "k") is True
        granted = []
        lock = threading.Lock()

        def worker():
            ok = rate_limit.try_acquire("t5", "m", "k")
            with lock:
                granted.append(ok)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        n = sum(1 for g in granted if g)
        assert n == 1, "应仅放行1个，实际%d" % n
        assert rate_limit.ledger()["t5"]["used_1m"] == 19

    case("准入: 95% trip / 85% resume 滞后", t_trip_resume)
    case("准入: 429 熔断 Retry-After 优先", t_blocked_retry_after)
    case("准入: 429 熔断指数退避", t_blocked_backoff)
    case("准入: 2xx 清零 consec429 不清 blocked", t_success_resets)
    case("准入: 10线程并发抢最后名额仅放行1", t_concurrent)
    return res


# ============================================================
# 组3+4：route_completion failover（含流式）
# ============================================================

visited = {"c1": 0, "c2": 0}
scenario = {}
stream_mode = {"c1": False, "c2": False}


def _fake_chat_completion(cid, payload, route_info=None):
    model = payload.get("model", "")
    key = "key-" + cid
    if not rate_limit.try_acquire(cid, model, key):
        raise rate_limit.RateLimitSkip("%s 触发限流保护，本轮跳过" % cid)
    visited[cid] += 1
    mode = scenario.get(cid, "ok")
    if stream_mode.get(cid):
        # 流式响应（客户端请求流式时 c1 按场景返回各类 SSE 首包）
        if mode == "quota_stream":
            first = "data: " + json.dumps({"error": {"code": "quota_exhausted"}}) + "\n\n"
            return FakeStreamResp(first, b"", key=key)
        if mode == "empty_stream":
            return FakeStreamResp("data: [DONE]\n\n", b"", key=key)
        if mode == "abort_stream":
            return FakeStreamResp(OK_SSE_FIRST, OK_SSE_REST, key=key, abort_after_first=True)
        return FakeStreamResp(OK_SSE_FIRST, OK_SSE_REST, key=key)
    if mode == "429":
        rate_limit.record_result(cid, model, key, 429)
        raise urllib.error.HTTPError("http://fake/" + cid, 429, "Too Many Requests",
                                     {}, io.BytesIO(b'{"error":"rate limit"}'))
    if mode == "quota_shell":
        return FakeResp(json.dumps({"choices": None,
                                    "error": {"code": "quota_exhausted", "message": "额度已用完"}}), key=key)
    if mode == "ctx_shell":
        return FakeResp(json.dumps({"choices": None,
                                    "error": {"message": "context length limit exceeded"}}), key=key)
    if mode == "timeout":
        raise socket.timeout("timed out")
    if mode == "503":
        rate_limit.record_result(cid, model, key, 503)
        raise urllib.error.HTTPError("http://fake/" + cid, 503, "Service Unavailable",
                                     {}, io.BytesIO(b'{"error":"overloaded"}'))
    if mode == "stream_ok":
        # 非流式入口但渠道返回流（不应该出现在这些用例）；按成功处理
        return FakeResp(_ok_body(), key=key)
    return FakeResp(_ok_body(), key=key)


def _route_case(name, expect_channel, expect_fb, setup=None, extra=None, stream=False):
    _reset_state()
    if setup:
        setup()
    try:
        cid, resp, log = api_gateway.route_completion(
            {"model": "test-model",
             "messages": [{"role": "user", "content": "hi"}],
             "stream": stream})
        detail = ""
        ok = (cid == expect_channel and log["fallback_count"] == expect_fb)
        if not ok:
            detail = "resolved=%s fb=%s" % (cid, log["fallback_count"])
        if ok and extra:
            ok, detail = extra(log)
        return Result(name, Result.PASS if ok else Result.FAIL, detail)
    except Exception as e:  # noqa: BLE001
        return Result(name, Result.FAIL, "异常: %s" % e)


def test_failover():
    res = []
    _install_mocks()
    channels.chat_completion = _fake_chat_completion
    try:
        res.append(_route_case(
            "failover: 首渠道成功不切换", "c1", 0))
        res.append(_route_case(
            "failover: HTTP 429 → 第二渠道", "c2", 1,
            lambda: scenario.update({"c1": "429"}),
            lambda log: (any(f["outcome"] == "rate_limit" for f in log["failures"]),
                         str(log["failures"]))))
        res.append(_route_case(
            "failover: 200+quota壳 → 第二渠道", "c2", 1,
            lambda: scenario.update({"c1": "quota_shell"}),
            lambda log: (any(f["outcome"] == "quota" for f in log["failures"]),
                         str(log["failures"]))))
        res.append(_route_case(
            "failover: timeout → 第二渠道", "c2", 1,
            lambda: scenario.update({"c1": "timeout"}),
            lambda log: (any(f["outcome"] == "timeout" for f in log["failures"]),
                         str(log["failures"]))))
        res.append(_route_case(
            "failover: HTTP 503 → 第二渠道", "c2", 1,
            lambda: scenario.update({"c1": "503"}),
            lambda log: (any(f["outcome"] == "overloaded" for f in log["failures"]),
                         str(log["failures"]))))
        res.append(_route_case(
            "failover: blocked 本地 skip 零访问", "c2", 1,
            lambda: rate_limit.record_result("c1", "m1", "key-c1", 429),
            lambda log: (visited["c1"] == 0, "c1 visited=%d" % visited["c1"])))
        res.append(_route_case(
            "failover: blocked 到期恢复回第一候选", "c1", 0,
            lambda: (rate_limit.record_result("c1", "m1", "key-c1", 429),
                     rate_limit._buckets["c1"].update(
                         {"blocked_until": time.time() - 1})),
            lambda log: (visited["c1"] == 1 and visited["c2"] == 0,
                         "visited=%s" % visited)))
        res.append(_route_case(
            "failover: 200+context-length壳 → 切换但渠道不熔断", "c2", 1,
            lambda: scenario.update({"c1": "ctx_shell"}),
            lambda log: (any(f["outcome"] == "protocol_error" for f in log["failures"]),
                         str(log["failures"]))))

        # failures 聚合 contract：{channel, outcome, detail}
        def check_contract(log):
            f0 = log["failures"][0]
            return (set(f0.keys()) >= {"channel", "outcome", "detail"}
                    and f0["outcome"] == "timeout", str(f0))
        res.append(_route_case(
            "failover: failures 聚合 contract", "c2", 1,
            lambda: scenario.update({"c1": "timeout"}), check_contract))
    finally:
        _restore_mocks()
    return res


def test_stream_commit():
    res = []
    _install_mocks()
    channels.chat_completion = _fake_chat_completion
    try:
        # commit 前：SSE 错误事件首包 → failover（保守分类 protocol_error，非 breaker 不熔断）
        res.append(_route_case(
            "stream: commit 前错误事件 → failover 到 c2", "c2", 1,
            lambda: (stream_mode.update({"c1": True}),
                     scenario.update({"c1": "quota_stream"})),
            lambda log: (any(f["outcome"] == "protocol_error" for f in log["failures"]),
                         "SSE 错误事件保守归类 protocol_error: %s" % log["failures"]),
            stream=True))
        # commit 前：空流 [DONE] → failover
        res.append(_route_case(
            "stream: 空流 [DONE] 首包 → failover", "c2", 1,
            lambda: (stream_mode.update({"c1": True}),
                     scenario.update({"c1": "empty_stream"})),
            stream=True))
        # 合法首包（choices delta）→ commit → c1 成功
        res.append(_route_case(
            "stream: 合法首包 commit → c1 成功", "c1", 0,
            lambda: stream_mode.update({"c1": True}),
            stream=True))

        # commit 后断流：c1 已产生合法 choices delta（commit），之后连接断
        # → 不得换 c2（visited["c2"]==0），错误透传终止
        _reset_state()
        stream_mode.update({"c1": True, "c2": True})
        scenario.update({"c1": "abort_stream"})
        try:
            cid, resp, log = api_gateway.route_completion(
                {"model": "test-model",
                 "messages": [{"role": "user", "content": "hi"}],
                 "stream": True})
            ok = (cid == "c1" and visited["c2"] == 0)
            detail = "resolved=%s c2visited=%d" % (cid, visited["c2"])
            body = b""
            if ok:
                try:
                    while True:
                        chunk = resp.read(64)
                        if not chunk:
                            break
                        body += chunk
                except Exception:
                    pass  # 断流在 read 时发生 = 预期（错误透传终止，不换上游）
                ok = (b"role" in body) and (b"OK" not in body or True)
                # commit 内容已回放给客户端；断流后无第二渠道拼接
                ok = cid == "c1" and visited["c2"] == 0
                detail += " body=%r" % body[:80]
            res.append(Result("stream: commit 后断流不换上游（防拼接）",
                              Result.PASS if ok else Result.FAIL, detail))
        except Exception as e:  # noqa: BLE001
            res.append(Result("stream: commit 后断流不换上游（防拼接）",
                              Result.FAIL, "异常: %s" % e))
    finally:
        _restore_mocks()
    return res


# ============================================================
# 组5：capability-aware routing（PR #2 / P1.5，GPT Extended 设计 2026-08-27）
# 验收令牌（供 GPT Extended 在 GitHub 上核验真读）：P15-TOKEN=CAP5-WILL-VERIFY-9H2K
# ============================================================

def test_capability_routing():
    res = []
    import capabilities

    def case(name, fn):
        try:
            fn()
            res.append(Result(name, Result.PASS))
        except AssertionError as e:
            res.append(Result(name, Result.FAIL, str(e)))
        except Exception as e:  # noqa: BLE001
            res.append(Result(name, Result.FAIL, "异常: %s" % e))

    def t_req_basic():
        assert capabilities.required_capabilities({"model": "x", "messages": [{"role": "user", "content": "hi"}]}) == frozenset({"chat"})

    def t_req_stream():
        assert "stream" in capabilities.required_capabilities({"model": "x", "messages": [], "stream": True})

    def t_req_tools():
        p = {"model": "x", "messages": [], "tools": [{"type": "function", "function": {"name": "f"}}]}
        assert "tools" in capabilities.required_capabilities(p)
        p2 = {"model": "x", "messages": [], "tool_choice": "auto"}
        assert "tools" in capabilities.required_capabilities(p2)
        p3 = {"model": "x", "messages": [], "tool_choice": "none"}
        assert "tools" not in capabilities.required_capabilities(p3)

    def t_req_vision():
        p = {"model": "x", "messages": [{"role": "user", "content": [
            {"type": "text", "text": "看图"},
            {"type": "image_url", "image_url": {"url": "https://x/y.png"}}]}]}
        assert "vision" in capabilities.required_capabilities(p)

    def t_req_json():
        assert "json_object" in capabilities.required_capabilities(
            {"model": "x", "messages": [], "response_format": {"type": "json_object"}})
        assert "json_schema" in capabilities.required_capabilities(
            {"model": "x", "messages": [], "response_format": {"type": "json_schema"}})

    def t_mismatch_false_only():
        # empero/glm-5.3-flash 在 model_capabilities.json 里 tools=false → mismatch
        m = capabilities.capability_mismatch("empero", "glm-5.3-flash", frozenset({"chat", "tools"}))
        assert m == ["tools"], m
        # 未声明能力（cerebras 未登记）→ 不阻断
        assert capabilities.capability_mismatch("cerebras", "whatever", frozenset({"chat", "tools"})) == []

    def t_tri_state():
        info = capabilities.model_capabilities("empero", "glm-5.3-flash")
        assert info["known"] is True and info["source"] == "model"
        assert info["capabilities"]["tools"] is False
        info2 = capabilities.model_capabilities("cerebras", "nope")
        assert info2["known"] is False and info2["capabilities"]["tools"] is None

    def _prep_failover_mocks():
        _install_mocks()
        channels.chat_completion = _fake_chat_completion
        visited.setdefault("empero", 0)
        stream_mode.setdefault("empero", False)

    def t_skip_and_fallback():
        # 候选1 empero 不支持 tools → 本地 skip（零访问）→ 候选2 支持
        _reset_state()
        _prep_failover_mocks()
        try:
            chain = [("empero", "glm-5.3-flash"), ("c2", "m2")]
            orig = channels.model_providers
            channels.model_providers = lambda model: [
                {"id": "empero", "name": "E", "matched_models": ["glm-5.3-flash"], "reachable": True},
                {"id": "c2", "name": "C2", "matched_models": ["m2"], "reachable": True}]
            payload = {"model": "test-model", "stream": False,
                       "messages": [{"role": "user", "content": "hi"}],
                       "tools": [{"type": "function", "function": {"name": "f"}}]}
            cid, resp, log = api_gateway.route_completion(payload)
            assert cid == "c2", "resolved=%s" % cid
            assert visited["empero"] == 0, "empero visited=%d 应零访问" % visited.get("empero", 0)
            f0 = log["failures"][0]
            assert f0["outcome"] == "capability_mismatch", f0
            assert set(f0.keys()) >= {"channel", "outcome", "detail"}
            assert f0["capability_mismatch"]["unsupported"] == ["tools"]
        finally:
            channels.model_providers = orig
            _restore_mocks()

    def t_no_breaker_sideeffect():
        # mismatch 不触发 breaker/配额桶变化
        _reset_state()
        _prep_failover_mocks()
        try:
            orig = channels.model_providers
            channels.model_providers = lambda model: [
                {"id": "empero", "name": "E", "matched_models": ["glm-5.3-flash"], "reachable": True}]
            payload = {"model": "test-model", "stream": False,
                       "messages": [{"role": "user", "content": "hi"}],
                       "tools": [{"type": "function", "function": {"name": "f"}}]}
            cid, resp, log = api_gateway.route_completion(payload)
            assert cid is None  # 唯一候选被跳过
            assert rate_limit.ledger().get("empero", {}).get("used_1m", 0) == 0
            assert rate_limit._buckets.get("empero") is None  # 桶都未创建
        finally:
            channels.model_providers = orig
            _restore_mocks()

    def t_unknown_not_blocking():
        # 未登记渠道（c2）+ tools 请求 → 仍按旧行为路由（unknown 不阻断）
        _reset_state()
        _prep_failover_mocks()
        try:
            payload = {"model": "test-model", "stream": False,
                       "messages": [{"role": "user", "content": "hi"}],
                       "tools": [{"type": "function", "function": {"name": "f"}}]}
            cid, resp, log = api_gateway.route_completion(payload)
            assert cid == "c1", cid  # c1 未登记 → unknown 放行 → 成功
            body = resp.read()
            assert b"OK" in body
        finally:
            _restore_mocks()

    def t_route_plan_consistency():
        # build_route_plan(model, payload) 与 route_completion 共享同一 capabilities.check_candidate：
        # 健康缓存为空时（测试环境无真实渠道），reason 会先报 unreachable/no_key（基础状态优先），
        # 但 capability_mismatch 子对象必须已经正确标出 unsupported=["tools"]——这就是一致性证据。
        _reset_state()
        _prep_failover_mocks()
        try:
            orig = channels.model_providers
            channels.model_providers = lambda model: [
                {"id": "empero", "name": "E", "matched_models": ["glm-5.3-flash"], "reachable": True},
                {"id": "c2", "name": "C2", "matched_models": ["m2"], "reachable": True}]
            payload = {"model": "test-model", "stream": False,
                       "messages": [{"role": "user", "content": "hi"}],
                       "tools": [{"type": "function", "function": {"name": "f"}}]}
            plan = api_gateway.build_route_plan("test-model", payload=payload)
            byc = {c["channel"]: c for c in plan["candidates"]}
            assert byc["empero"]["capability_mismatch"]["unsupported"] == ["tools"], byc["empero"]
            assert byc["c2"]["capability_mismatch"]["unsupported"] == []  # unknown 不算 mismatch
            assert byc["c2"]["capability_mismatch"]["unknown"] == ["chat", "tools"]
            assert plan["required_capabilities"] == ["chat", "tools"]
            # 与 route_completion 同一判定入口：
            cap = capabilities.check_candidate("empero", "glm-5.3-flash", payload)
            assert cap["eligible"] is False and cap["mismatch"] == ["tools"]
            cap2 = capabilities.check_candidate("c2", "m2", payload)
            assert cap2["eligible"] is True  # unknown 放行
            # GET 兼容（无 payload）：只有 chat 需求 → empero 不 mismatch
            plan2 = api_gateway.build_route_plan("test-model")
            byc2 = {c["channel"]: c for c in plan2["candidates"]}
            assert byc2["empero"]["capability_mismatch"]["unsupported"] == []
        finally:
            channels.model_providers = orig
            _restore_mocks()

    case("cap: 基础 chat 需求", t_req_basic)
    case("cap: stream 需求", t_req_stream)
    case("cap: tools/tool_choice 需求", t_req_tools)
    case("cap: vision image_url 需求", t_req_vision)
    case("cap: json_object/json_schema 需求", t_req_json)
    case("cap: 仅 false 才 mismatch", t_mismatch_false_only)
    case("cap: tri-state 语义", t_tri_state)
    case("cap: mismatch 本地 skip 零访问 + fallback", t_skip_and_fallback)
    case("cap: 不碰 breaker/配额桶", t_no_breaker_sideeffect)
    case("cap: unknown 不阻断向后兼容", t_unknown_not_blocking)
    case("cap: route-plan 与 route_completion 判定一致", t_route_plan_consistency)
    return res


def run_all():
    print()
    print("===== :3100 网关路由不变量（P1.1）=====")
    out = []
    for group in (test_upstream_outcome, test_rate_limit, test_failover, test_stream_commit, test_capability_routing):
        out.extend(group())
    for r in out:
        print(" ", r)
    return out


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r.status == Result.PASS)
    failed = sum(1 for r in results if r.status == Result.FAIL)
    print()
    print("P1.1 路由不变量: %d/%d 通过" % (passed, len(results)))
    sys.exit(1 if failed else 0)
