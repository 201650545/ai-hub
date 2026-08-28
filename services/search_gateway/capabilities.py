# -*- coding: utf-8 -*-
"""模型能力静态声明与请求硬需求推导（PR #2 / Phase 1.5，GPT Extended 设计 2026-08-27）。

核心原则：
- capability filter 发生在任何上游访问之前（比 blocked local-skip 更前置）；
- route_completion 与 build_route_plan 共用同一套判定，不允许双逻辑；
- tri-state 语义锁死：False=已知不支持→本地 skip；True=支持；None/缺失=未知→默认放行尝试；
- 禁止按模型名 substring 猜能力，禁止动态探测/自动学习；能力只来自静态配置。
"""
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAP_FILE = os.environ.get("MODEL_CAPABILITIES_FILE") or os.path.normpath(
    os.path.join(BASE_DIR, "..", "..", "data", "search_gateway", "model_capabilities.json"))

CAP_CHAT = "chat"
CAP_STREAM = "stream"
CAP_TOOLS = "tools"
CAP_VISION = "vision"
CAP_JSON_OBJECT = "json_object"
CAP_JSON_SCHEMA = "json_schema"

ALL_CAPABILITIES = frozenset({
    CAP_CHAT, CAP_STREAM, CAP_TOOLS, CAP_VISION, CAP_JSON_OBJECT, CAP_JSON_SCHEMA,
})

_cache = {"mtime": None, "data": {"version": 1, "channels": {}}}


def load_model_capabilities():
    """mtime-aware 读取 model_capabilities.json；读取/解析失败返回空配置。"""
    try:
        mtime = os.path.getmtime(CAP_FILE)
    except OSError:
        _cache["mtime"] = None
        _cache["data"] = {"version": 1, "channels": {}}
        return _cache["data"]
    if _cache["mtime"] == mtime:
        return _cache["data"]
    try:
        with open(CAP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("not a dict")
        data.setdefault("channels", {})
    except Exception:  # noqa: BLE001
        data = {"version": 1, "channels": {}}
    _cache["mtime"] = mtime
    _cache["data"] = data
    return data


def _messages_contain_images(messages):
    """兼容 OpenAI content-array 形状的图像检测。"""
    if not isinstance(messages, list):
        return False
    for m in messages:
        content = (m or {}).get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") in ("image_url", "image", "input_image"):
                return True
    return False


def required_capabilities(payload):
    """从 OpenAI-compatible /v1/chat/completions payload 推导硬性能力需求。

    返回 frozenset[str] ⊆ ALL_CAPABILITIES。不做名字猜测。
    """
    payload = payload or {}
    required = {CAP_CHAT}
    if payload.get("stream") is True:
        required.add(CAP_STREAM)
    if payload.get("tools"):
        required.add(CAP_TOOLS)
    if payload.get("tool_choice") not in (None, "none"):
        required.add(CAP_TOOLS)
    if _messages_contain_images(payload.get("messages")):
        required.add(CAP_VISION)
    rf = payload.get("response_format") or {}
    rtype = rf.get("type") if isinstance(rf, dict) else None
    if rtype == "json_object":
        required.add(CAP_JSON_OBJECT)
    elif rtype == "json_schema":
        required.add(CAP_JSON_SCHEMA)
    return frozenset(required & ALL_CAPABILITIES)


def model_capabilities(channel_id, model):
    """返回某 channel + upstream model 的能力声明。

    解析优先级：channels[cid].models[exact model] 缺字段 → channels[cid].defaults → None(未声明)。
    返回 {"known": bool, "capabilities": {cap: True|False|None}, "source": str}。
    None = 未声明，不等同 False。
    """
    cfg = load_model_capabilities()
    caps = {c: None for c in ALL_CAPABILITIES}
    source = "unknown"
    chan = (cfg.get("channels") or {}).get(channel_id) or {}
    defaults = chan.get("defaults") or {}
    declared = False
    for c in ALL_CAPABILITIES:
        if c in defaults:
            caps[c] = defaults[c]
            declared = True
    if declared:
        source = "channel_default"
    models = chan.get("models") or {}
    m = models.get(model)
    if isinstance(m, dict):
        for c in ALL_CAPABILITIES:
            if c in m:
                caps[c] = m[c]
                declared = True
        source = "model"
    known = declared
    return {"known": known, "capabilities": caps, "source": source if known else "unknown"}


def capability_mismatch(channel_id, model, required):
    """返回明确不兼容能力列表。

    只有 capability 被明确声明为 False 才进入 mismatch；未知默认不阻断（向后兼容）。
    """
    info = model_capabilities(channel_id, model)
    caps = info["capabilities"]
    return sorted(c for c in required if caps.get(c) is False)


def check_candidate(channel_id, model, payload):
    """一次完成 request requirements + candidate capability 检查。

    返回 {"required": [...], "mismatch": [...], "eligible": bool,
          "unknown": [...], "known": bool, "source": str}
    """
    required = required_capabilities(payload)
    mismatch = capability_mismatch(channel_id, model, required)
    info = model_capabilities(channel_id, model)
    caps = info["capabilities"]
    unknown = sorted(c for c in required if caps.get(c) is None)
    return {
        "required": sorted(required),
        "mismatch": mismatch,
        "eligible": not mismatch,
        "unknown": unknown,
        "known": info["known"],
        "source": info["source"],
    }
