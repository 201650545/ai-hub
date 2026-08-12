# -*- coding: utf-8 -*-
"""
渠道层 (channel registry) —— 聚合「我的 API + 网上免费 API」，OpenAI 兼容转发。

已接入真实渠道（key 已验证，2026-08-04）：
  deepseek  官方 API        （env DEEPSEEK_API_KEY）
  gemini    Google Gemini   （env GOOGLE_API_KEY，走 OpenAI 兼容端点）
  openrouter 20+ 免费模型聚合（env OPENROUTER_API_KEY）

可填 key 槽位（网页渠道管理页填入，存本地 channels.json，填了才生效）：
  groq / siliconflow / dashscope / zhipu

key 优先级：环境变量 > channels.json（网页填写）。
不编造假 key；未填的槽位 health.key_set=False，路由会自动跳过。
"""

import json
import os
import threading
import time
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 数据与代码分离：渠道配置统一在 仓库根/data/search_gateway/
DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), "data", "search_gateway")
CHANNELS_JSON = os.path.join(DATA_DIR, "channels.json")

# ---------------------------------------------------------------- 渠道注册表

# ---------------------------------------------------------------- 渠道注册表

CHANNELS = {
    "deepseek": {
        "name": "DeepSeek 官方 API",
        "provider": "DeepSeek 官方 (api.deepseek.com)",
        "billing_type": "paid",
        "billing_tag": "🔴 付费扣费 (按量充值)",
        "icon": "🧠",
        "base_url": "https://api.deepseek.com/v1",
        "env_key": "DEEPSEEK_API_KEY",
        "free": False,
        "default_model": "deepseek-v4-flash",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-reasoner"],
        "note": "使用官方 Key 扣除充值余额，请关注余额。",
    },
    "gemini": {
        "name": "Google Gemini 官方",
        "provider": "Google (generativelanguage.googleapis.com)",
        "billing_type": "free_quota",
        "billing_tag": "🟢 免费配额 (1500次/天)",
        "icon": "✨",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "env_key": "GOOGLE_API_KEY",
        "free": True,
        "default_model": "gemini-2.5-flash",
        "models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash", "gemini-2.0-flash-lite"],
        "note": "谷歌官方免费配额，超限即停，0 欠费风险。",
    },
    "openrouter": {
        "name": "OpenRouter 免费模型池",
        "provider": "OpenRouter (openrouter.ai)",
        "billing_type": "free",
        "billing_tag": "🟢 0 扣费 (仅免费模型)",
        "icon": "🛰️",
        "base_url": "https://openrouter.ai/api/v1",
        "env_key": "OPENROUTER_API_KEY",
        "free": True,
        "default_model": "meta-llama/llama-3.3-70b-instruct:free",
        "models": [],  # 启动/健康检查时动态拉取免费模型
        "note": "自动筛选 :free 节点，0 扣费风险。",
    },
    "groq": {
        "name": "Groq 极速 API",
        "provider": "Groq (api.groq.com)",
        "billing_type": "free_quota",
        "billing_tag": "🟢 免费配额 (1000次/天)",
        "icon": "⚡",
        "base_url": "https://api.groq.com/openai/v1",
        "env_key": "",
        "free": True,
        "default_model": "gpt-oss-120b",
        "models": ["gpt-oss-120b", "gpt-oss-20b", "qwen3.6-27b", "compound-mini"],
        "note": "LPU 硬件加速，免费配额，0 欠费风险。",
    },
    "siliconflow": {
        "name": "硅基流动 SiliconFlow",
        "provider": "硅基流动 (api.siliconflow.cn)",
        "billing_type": "free_quota",
        "billing_tag": "🟢 赠送额度 + 免费模型",
        "icon": "💎",
        "base_url": "https://api.siliconflow.cn/v1",
        "env_key": "",
        "free": True,
        "default_model": "deepseek-ai/DeepSeek-V3",
        "models": ["deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-7B-Instruct", "THUDM/glm-4-9b-chat"],
        "note": "注册赠送 ￥14 额度，含免费开箱模型。",
    },
    "dashscope": {
        "name": "阿里通义千问 DashScope",
        "provider": "阿里云 (dashscope.aliyuncs.com)",
        "billing_type": "free_quota",
        "billing_tag": "🟢 新用户赠送 Tokens",
        "icon": "🎈",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "env_key": "",
        "free": True,
        "default_model": "qwen-plus",
        "models": ["qwen-plus", "qwen-turbo", "qwen-max"],
        "note": "注册赠送数千万 Tokens 试用。",
    },
    "zhipu": {
        "name": "智谱 GLM BigModel",
        "provider": "智谱 AI (open.bigmodel.cn)",
        "billing_type": "free",
        "billing_tag": "🟢 0 扣费 (Flash免费模型)",
        "icon": "🌀",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "env_key": "",
        "free": True,
        "default_model": "glm-4-flash",
        "models": ["glm-4-flash", "glm-4.5-flash", "glm-4-air"],
        "note": "GLM-4-Flash 永久免费，0 欠费风险。",
    },
}

CHANNEL_ORDER = ["deepseek", "gemini", "openrouter", "groq", "siliconflow", "dashscope", "zhipu"]

# fallback 链（前端模型未匹配时按此顺序路由）
DEFAULT_CHAIN = ["deepseek", "openrouter", "gemini", "groq", "siliconflow", "dashscope", "zhipu"]

_config_cache = None


# ---------------------------------------------------------------- 配置读写

def _load_config():
    """读 channels.json（网页填的 key）。"""
    global _config_cache
    if _config_cache is None:
        try:
            with open(CHANNELS_JSON, "r", encoding="utf-8") as f:
                _config_cache = json.load(f)
        except Exception:  # noqa: BLE001
            _config_cache = {}
    return _config_cache


def save_channel_key(channel_id, key):
    """把网页填的 key 存进 channels.json（明文本机）。"""
    global _config_cache
    cfg = _load_config()
    cfg.setdefault("keys", {})[channel_id] = key.strip()
    with open(CHANNELS_JSON, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    _config_cache = cfg


def get_key(channel_id):
    """渠道 key：环境变量优先，其次 channels.json。"""
    ch = CHANNELS.get(channel_id)
    if not ch:
        return ""
    env_name = ch.get("env_key", "")
    if env_name:
        v = os.environ.get(env_name, "")
        if v:
            return v
    return _load_config().get("keys", {}).get(channel_id, "")


def key_is_set(channel_id):
    return bool(get_key(channel_id))


# ---------------------------------------------------------------- 健康检查与余额查询

def get_balance(channel_id, key):
    """查询指定渠道的充值余额/免费额度，避免用户欠费顾虑。"""
    if not key:
        return "未配置 Key"
    try:
        if channel_id == "deepseek":
            req = urllib.request.Request("https://api.deepseek.com/user/balance", headers={
                "Authorization": f"Bearer {key}",
                "User-Agent": "unified-ai-gateway/1.0"
            })
            with urllib.request.urlopen(req, timeout=5) as resp:
                d = json.loads(resp.read().decode("utf-8", "ignore"))
                if d.get("is_available") and d.get("balance_infos"):
                    info = d["balance_infos"][0]
                    total = info.get("total_balance", "0")
                    currency = info.get("currency", "CNY")
                    symbol = "￥" if currency == "CNY" else "$"
                    return f"余额: {symbol}{total} {currency} (按量扣费)"
                return "余额透支或未激活"
        elif channel_id == "siliconflow":
            req = urllib.request.Request("https://api.siliconflow.cn/v1/user/info", headers={
                "Authorization": f"Bearer {key}",
                "User-Agent": "unified-ai-gateway/1.0"
            })
            with urllib.request.urlopen(req, timeout=5) as resp:
                d = json.loads(resp.read().decode("utf-8", "ignore"))
                if d.get("code") == 20000 and "data" in d:
                    bal = d["data"].get("totalBalance", "0")
                    return f"余额: ￥{bal} CNY (含赠送)"
        elif channel_id == "openrouter":
            req = urllib.request.Request("https://openrouter.ai/api/v1/credits", headers={
                "Authorization": f"Bearer {key}",
                "User-Agent": "unified-ai-gateway/1.0"
            })
            with urllib.request.urlopen(req, timeout=5) as resp:
                d = json.loads(resp.read().decode("utf-8", "ignore"))
                if "data" in d and "total_credits" in d["data"]:
                    return f"额度: ${d['data']['total_credits']:.2f} (0扣费风险)"
    except Exception:  # noqa: BLE001
        pass

    ch = CHANNELS.get(channel_id, {})
    if ch.get("billing_type") == "paid":
        return "充值扣费账户 (请关注余额)"
    return "免费额度/配额 (0 欠费风险)"


def _get_json(url, key, timeout=8):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key}",
        "User-Agent": "unified-ai-gateway/1.0",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def channel_health(channel_id):
    """轻量探测：是否有 key + 模型端点可达 + 余额检测。返回 {id,name,icon,key_set,reachable,models,error,can_fill,provider,billing_tag,balance}"""
    ch = CHANNELS.get(channel_id)
    if not ch:
        return {"id": channel_id, "name": channel_id, "icon": "🤖", "key_set": False, "reachable": False, "models": [],
                "error": "未知渠道", "can_fill": True, "provider": "", "billing_tag": "", "balance": "未知"}
    can_fill = not bool(ch.get("env_key"))  # 环境变量渠道不用网页填 key
    key = get_key(channel_id)
    name = ch.get("name", channel_id)
    icon = ch.get("icon", "🤖")
    provider = ch.get("provider", name)
    billing_tag = ch.get("billing_tag", "免费")
    billing_type = ch.get("billing_type", "free")

    if not key:
        return {"id": channel_id, "name": name, "icon": icon, "key_set": False, "reachable": False, "models": [],
                "error": "待填 key（网页渠道管理页填入）", "can_fill": can_fill,
                "provider": provider, "billing_tag": billing_tag, "billing_type": billing_type,
                "balance": "未配置 Key"}

    balance = get_balance(channel_id, key)
    base = ch["base_url"].rstrip("/")
    try:
        if channel_id == "openrouter":
            data = _get_json(base + "/models", key, timeout=8)
            models = [m["id"] for m in data.get("data", [])
                      if m.get("id", "").endswith(":free") or m.get("is_free")]
            models = sorted(models)[:40]
            return {"id": channel_id, "name": name, "icon": icon, "key_set": True, "reachable": True, "models": models,
                    "error": "", "can_fill": can_fill, "provider": provider,
                    "billing_tag": billing_tag, "billing_type": billing_type, "balance": balance}
        data = _get_json(base + "/models", key, timeout=8)
        models = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
        if channel_id == "deepseek":
            models = [m for m in models if m in ("deepseek-v4-flash", "deepseek-v4-pro", "deepseek-reasoner", "deepseek-chat")]
        elif channel_id == "gemini":
            models = [m.split("/", 1)[-1] for m in models]  # 去掉 models/ 前缀
        models = (models or ch.get("models", []))[:20]
        return {"id": channel_id, "name": name, "icon": icon, "key_set": True, "reachable": True, "models": models,
                "error": "", "can_fill": can_fill, "provider": provider,
                "billing_tag": billing_tag, "billing_type": billing_type, "balance": balance}
    except urllib.error.HTTPError as e:
        return {"id": channel_id, "name": name, "icon": icon, "key_set": True, "reachable": False, "models": [],
                "error": f"HTTP {e.code}", "can_fill": can_fill, "provider": provider,
                "billing_tag": billing_tag, "billing_type": billing_type, "balance": balance}
    except Exception as e:  # noqa: BLE001
        return {"id": channel_id, "name": name, "icon": icon, "key_set": True, "reachable": False, "models": [],
                "error": str(e)[:120], "can_fill": can_fill, "provider": provider,
                "billing_tag": billing_tag, "billing_type": billing_type, "balance": balance}


def health_all():
    return {cid: channel_health(cid) for cid in CHANNEL_ORDER}


# ---------------------------------------------------------------- 健康缓存（避免每次请求都打 7 家 API）

_health_cache = {}
_cache_lock = threading.Lock()


def cached_health_all(ttl=60):
    """带 TTL 的渠道健康缓存；过期渠道并发惰性刷新，避免串行网络探测阻塞启动。"""
    now = time.time()
    out = {}
    stale = []
    with _cache_lock:
        for cid in CHANNEL_ORDER:
            hit = _health_cache.get(cid)
            if hit and now - hit[0] < ttl:
                out[cid] = hit[1]
            else:
                stale.append(cid)
    if stale:
        # 并发探测各渠道，互不阻塞
        results = {}
        def _probe(cid):
            try:
                results[cid] = channel_health(cid)
            except Exception:  # noqa: BLE001
                results[cid] = {"id": cid, "name": cid, "icon": "🤖", "key_set": False,
                                "reachable": False, "models": [], "error": "探测异常",
                                "can_fill": True, "provider": "", "billing_tag": "", "balance": "未知"}
        threads = [threading.Thread(target=_probe, args=(cid,), daemon=True) for cid in stale]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        with _cache_lock:
            for cid in stale:
                r = results.get(cid)
                if r is not None:
                    _health_cache[cid] = (time.time(), r)
                    out[cid] = r
    return out


def warm_start():
    """后台线程预热并周期刷新缓存，让 /api/channels、/v1/models 首次即快。"""
    def _run():
        while True:
            try:
                cached_health_all(ttl=0)  # 强制刷新
            except Exception:  # noqa: BLE001
                pass
            time.sleep(120)
    t = threading.Thread(target=_run, daemon=True)
    t.start()


# ---------------------------------------------------------------- 转发

def chat_completion(channel_id, payload):
    """转发 chat/completions 到指定渠道。返回 urllib response（流式/非流式透传）。"""
    ch = CHANNELS[channel_id]
    key = get_key(channel_id)
    if not key:
        raise RuntimeError(f"{ch['name']} 未配置 key")
    req_payload = dict(payload)
    # developer 角色 → system（部分渠道不认 developer）
    for m in req_payload.get("messages", []):
        if m.get("role") == "developer":
            m["role"] = "system"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "User-Agent": "unified-ai-gateway/1.0",
    }
    if req_payload.get("stream"):
        headers["Accept"] = "text/event-stream"
    url = ch["base_url"].rstrip("/") + "/chat/completions"
    req = urllib.request.Request(url, data=json.dumps(req_payload).encode("utf-8"),
                                 headers=headers, method="POST")
    return urllib.request.urlopen(req, timeout=120)


def model_to_chain(model):
    """模型名 → 渠道候选链（第一个命中优先）。"""
    if model.startswith("deepseek-"):
        return ["deepseek"]
    if model.startswith("gemini-"):
        return ["gemini"]
    if "/" in model:  # openrouter 风格模型名
        return ["openrouter"]
    m = model.lower()
    for cid in ["groq", "siliconflow", "dashscope", "zhipu", "openrouter"]:
        if m in [x.lower() for x in CHANNELS[cid].get("models", [])]:
            return [cid]
    return DEFAULT_CHAIN
