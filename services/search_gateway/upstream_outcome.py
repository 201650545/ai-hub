# -*- coding: utf-8 -*-
"""上游失败归一化（Phase 1）—— 把各渠道五花八门的失败信号统一成枚举类型。

路由决策只认 outcome 类型，不认具体错误字符串。每个类型决定 failover 行为：
- SUCCESS            → 提交，停止 failover
- RATE_LIMIT / QUOTA → 熔断（指数退避），继续 failover
- AUTH               → 渠道级 key 失效，熔断，继续 failover
- OVERLOADED         → 上游过载，熔断，继续 failover
- MODEL_UNAVAILABLE  → 该渠道该模型不可用，记录但不熔断，继续 failover
- PROTOCOL_ERROR     → 空壳/畸形响应，记录但不熔断，继续 failover
- TIMEOUT            → 网络超时，记录但不熔断，继续 failover

BREAKER_TYPES 触发限流熔断（合成 429 → try_acquire 提前跳过该渠道）；
NON_BREAKER_TYPES 只记录错误、继续下一候选，不惩罚该渠道。
"""
from enum import Enum
import json


class Outcome(str, Enum):
    SUCCESS = "success"
    RATE_LIMIT = "rate_limit"
    QUOTA = "quota"
    AUTH = "auth"
    MODEL_UNAVAILABLE = "model_unavailable"
    OVERLOADED = "overloaded"
    PROTOCOL_ERROR = "protocol_error"
    TIMEOUT = "timeout"


BREAKER_TYPES = {Outcome.RATE_LIMIT, Outcome.QUOTA, Outcome.AUTH, Outcome.OVERLOADED}
NON_BREAKER_TYPES = {Outcome.MODEL_UNAVAILABLE, Outcome.PROTOCOL_ERROR, Outcome.TIMEOUT}

# 归一化失败 → 限流台账用的合成状态码（熔断走 429 指数退避）
BREAKER_STATUS = 429

# 高置信短语（语义明确，可触发熔断）——裸词 limit/key/token 过宽，已在 2026-08-27 GPT
# Extended 评审后移除："context length limit exceeded" 曾因 limit 误判 QUOTA → 错误熔断健康渠道。
_QUOTA_HINTS = ("quota", "insufficient_quota", "insufficient credits", "quota exceeded",
                "额度", "余额不足", "次数用完", "用完", "exhaust", "credits")
_AUTH_HINTS = ("unauthorized", "forbidden", "invalid api key", "invalid_api_key",
               "authentication failed", "鉴权失败", "密钥无效", "401", "403")
_MODEL_HINTS = ("model not found", "not found", "model_not", "不存在", "no model",
                "unknown model", "unavailable model")
_OVERLOAD_HINTS = ("overloaded", "overload", "server busy", "service unavailable",
                   "繁忙", "过载", "try again later", "temporarily", "502", "503", "504")
# 请求级/协议级错误显式排除：命中即 PROTOCOL_ERROR，不进 QUOTA/AUTH 熔断
# （context length / max token 是请求本身超限，渠道本身健康，熔断会误杀好渠道）
_REQUEST_LEVEL_HINTS = ("context length", "maximum context", "max token",
                        "tokenizer", "token limit", "invalid request", "请求参数")


def classify_http_status(code, body_text=""):
    """按 HTTP 状态码 + 响应体归一化失败类型（非 2xx 的调用入口）。"""
    if 200 <= code < 300:
        return Outcome.SUCCESS
    if code == 429:
        return Outcome.RATE_LIMIT
    if code in (401, 403):
        return Outcome.AUTH
    if code == 404:
        return Outcome.MODEL_UNAVAILABLE
    if code in (502, 503, 504):
        return Outcome.OVERLOADED
    # 其他 4xx/5xx：尝试从 body 关键词进一步区分
    return _classify_text(body_text) or Outcome.PROTOCOL_ERROR


def classify_shell(body):
    """HTTP 200 但空壳/错误载荷的归一化（choices 为空、带 error 字段、非 JSON）。"""
    if not body:
        return Outcome.PROTOCOL_ERROR
    try:
        d = _json_loads(body)
    except Exception:  # noqa: BLE001
        return Outcome.PROTOCOL_ERROR  # 非 JSON 的 200 不可信
    if not isinstance(d, dict):
        return Outcome.PROTOCOL_ERROR
    if d.get("choices"):
        return Outcome.SUCCESS  # 有有效 choices 不算壳
    # 提取错误文本（error 可能是 dict 或 str）
    err = d.get("error")
    text = ""
    if isinstance(err, dict):
        text = " ".join(str(v) for v in err.values())
    elif err:
        text = str(err)
    text = (text + " " + json.dumps(d, ensure_ascii=False)).lower()
    return _classify_text(text) or Outcome.PROTOCOL_ERROR


def classify_exception(exc):
    """网络/本地异常归一化（HTTPError 之外的调用入口）。"""
    name = type(exc).__name__.lower()
    if any(t in name for t in ("timeout", "timedout", "timed out")):
        return Outcome.TIMEOUT
    if any(t in name for t in ("connection", "socket", "refused", "reset", "unreachable")):
        return Outcome.TIMEOUT
    return Outcome.PROTOCOL_ERROR


def _classify_text(text):
    """关键词匹配失败类型（小写文本）。三层：
    1) 请求级错误显式排除（context length / max token 等 → PROTOCOL_ERROR，不熔断）；
    2) 高置信短语分类（quota/unauthorized 等语义明确的才进熔断）；
    3) 判不出 → None（由调用方兜底 PROTOCOL_ERROR）。
    注意：RATE_LIMIT 只来自 HTTP 429（classify_http_status），文本不判定 rate_limit，
    避免 "token limit" 之类误触发。"""
    t = (text or "").lower()
    if any(h in t for h in _REQUEST_LEVEL_HINTS):
        return Outcome.PROTOCOL_ERROR
    if any(h in t for h in _QUOTA_HINTS):
        return Outcome.QUOTA
    if any(h in t for h in _AUTH_HINTS):
        return Outcome.AUTH
    if any(h in t for h in _OVERLOAD_HINTS):
        return Outcome.OVERLOADED
    if any(h in t for h in _MODEL_HINTS):
        return Outcome.MODEL_UNAVAILABLE
    return None


def _json_loads(body):
    return json.loads(body.decode("utf-8", "ignore"))


def is_breaker(outcome):
    return outcome in BREAKER_TYPES
