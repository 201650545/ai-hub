# -*- coding: utf-8 -*-
"""
渠道层 (channel registry) —— 聚合「我的 API + 网上免费 API」，OpenAI 兼容转发。

已接入真实渠道（key 已验证，2026-08-04）：
  deepseek  官方 API        （env DEEPSEEK_API_KEY）
  openrouter 20+ 免费模型聚合（env OPENROUTER_API_KEY，支持 channels.json key_pools 多账号轮换）

可填 key 槽位（网页渠道管理页填入，存本地 channels.json，填了才生效）：
  groq / siliconflow / dashscope / zhipu / xiaohongshu

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
DATA_DIR = os.path.normpath(os.path.join(os.path.dirname(BASE_DIR), "..", "data", "search_gateway"))
CHANNELS_JSON = os.path.join(DATA_DIR, "channels.json")
ROUTING_JSON = os.path.join(DATA_DIR, "routing.json")
MODEL_OVERRIDES_JSON = os.path.join(DATA_DIR, "model_overrides.json")
PROMOS_JSON = os.path.join(DATA_DIR, "promos.json")

# 本地额度统计（task_011）：调用成功后记录 quota.json，缺失时降级不记录
GATEWAY_ID = os.environ.get("GATEWAY_ID", "ds_v4_cli")
try:
    from quota import record_call as _record_call  # noqa: F401
except Exception:  # noqa: BLE001
    _record_call = None

# 渠道限流准入闸门（task_045，v2）：try_acquire 原子预占 + 429 熔断，触发即提前切换
try:
    import rate_limit as _rate_limit
except Exception:  # noqa: BLE001
    _rate_limit = None

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
        
        "speed": "fast",
        "default_model": "deepseek-v4-flash",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-reasoner"],
        "note": "使用官方 Key 扣除充值余额，请关注余额。",
    },
    # gemini 渠道已移除（用户 2026-08-23 拍板）：Google 按自有 IP 情报判定代理出口为
    # 不支持地区，稳定返回 400 FAILED_PRECONDITION，与公共 geo 库结论无关，无法修复。
    "openrouter": {
        "name": "OpenRouter 免费模型池",
        "provider": "OpenRouter (openrouter.ai)",
        "billing_type": "free",
        "billing_tag": "🟢 0 扣费 (仅免费模型)",
        "icon": "/img/brand/openrouter.png",
        "base_url": "https://openrouter.ai/api/v1",
        "env_key": "OPENROUTER_API_KEY",
        "free": True,
        
        "speed": "medium",
        "default_model": "meta-llama/llama-3.3-70b-instruct:free",
        "models": [],  # 启动/健康检查时动态拉取免费模型
        "note": "自动筛选 :free 节点，0 扣费风险。",
    },
    "groq": {
        "name": "Groq 极速 API",
        "provider": "Groq (api.groq.com)",
        "billing_type": "free_quota",
        "billing_tag": "🟢 免费配额 (1000次/天)",
        "icon": "/img/brand/groq.png",
        "base_url": "https://api.groq.com/openai/v1",
        "env_key": "",
        "free": True,
        
        "speed": "fast",
        "default_model": "openai/gpt-oss-120b",
        "models": ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b", "qwen/qwen3.8-27b", "groq/compound-mini"],
        "note": "LPU 硬件加速，免费配额，0 欠费风险。",
    },
    "siliconflow": {
        "name": "硅基流动 SiliconFlow",
        "provider": "硅基流动 (api.siliconflow.cn)",
        "billing_type": "free_quota",
        "billing_tag": "🟢 赠送额度 + 免费模型",
        "icon": "/img/brand/siliconflow.png",
        "base_url": "https://api.siliconflow.cn/v1",
        "env_key": "",
        "free": True,
        
        "speed": "fast",
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
        
        "speed": "medium",
        "default_model": "qwen3.8-flash",
        "models": ["qwen3.8-flash", "qwen-plus", "qwen-turbo", "qwen-max"],
        "note": "Qwen3.8-Flash 2026-08-26 首发：新用户每模型送 100 万 tokens（90 天，北京地域），推理价 ¥1/百万输入、¥3/百万输出",
        "promo": "Qwen3.8-Flash 首发（8/26 上线「千问办公」）：推理价每百万输入 tokens 仅 1 元、输出 3 元，为 DeepSeek-V4-Flash 的 1/3。阿里云百炼新用户每模型赠送 100 万 tokens 免费额度（90 天有效，仅华北2北京地域；未认证用户额度耗尽自动停止不扣费）。",
        "free_models": ["qwen3.8-flash"],
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
        
        "speed": "medium",
        "default_model": "glm-4-flash",
        "models": ["glm-4-flash", "glm-4.5-flash", "glm-4-air"],
        "note": "GLM-4-Flash 永久免费，0 欠费风险。",
    },
    "modelscope": {
        "name": "魔塔社区 ModelScope",
        "provider": "魔塔社区 (api-inference.modelscope.cn)",
        "billing_type": "free_quota",
        "billing_tag": "🟢 免费配额 (注册赠送)",
        "icon": "/img/brand/modelscope.png",
        "base_url": "https://api-inference.modelscope.cn/v1",
        "env_key": "",
        "free": True,
        
        "speed": "medium",
        "default_model": "deepseek-ai/DeepSeek-V4-Flash-0731",
        "models": ["deepseek-ai/DeepSeek-V4-Flash-0731", "deepseek-ai/DeepSeek-V4-Pro", "ZhipuAI/GLM-5.2"],
        "note": "魔塔社区 ModelScope（Cherry Studio 已配置 key，2026-08-16 收录）。",
    },
    "sensetime": {
        "name": "商汤日日新 SenseNova",
        "provider": "商汤 (token.sensenova.cn)",
        "billing_type": "free_quota",
        "billing_tag": "🟢 免费配额",
        "icon": "/img/brand/sensetime.png",
        "base_url": "https://token.sensenova.cn/v1",
        "env_key": "",
        "free": True,
        
        "speed": "medium",
        "default_model": "deepseek-v4-flash",
        "models": ["deepseek-v4-flash", "glm-5.2", "sensenova-6.8-flash-lite"],
        "note": "商汤日日新 SenseNova（Cherry Studio 已配置 key，2026-08-16 收录）。",
    },
    "ark": {
        "name": "火山方舟 ARK",
        "provider": "火山引擎方舟 (ark.cn-beijing.volces.com)",
        "billing_type": "free_quota",
        "billing_tag": "🟢 开通赠送额度（模型需在方舟开通管理开通）",
        "icon": "/img/brand/ark.png",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "env_key": "",
        "free": True,

        "speed": "fast",
        "default_model": "doubao-seed-2-0-lite-260428",
        "models": ["doubao-seedream-5-0-260128", "doubao-seedream-4-5-251128", "doubao-seed-2-0-lite-260428"],
        "note": "火山方舟 ARK（用户 2026-08-25 提供 key）：chat + /v1/images/generations 生图（seedream/seededit）；另有 Seedance 视频、Seed3D/Hyper3D 3D 资产、Seed-Character 角色一致性；模型目录动态拉取并过滤已下线。",
    },
    "agnes": {
        "name": "AGNES AI",
        "provider": "AGNES (apihub.agnes-ai.com)",
        "billing_type": "free_quota",
        "billing_tag": "🟢 免费配额",
        "icon": "/img/brand/agnes.png",
        "base_url": "https://apihub.agnes-ai.com/v1",
        "env_key": "",
        "free": True,
        
        "speed": "medium",
        "default_model": "agnes-2.5-flash",
        "models": ["agnes-2.5-flash", "agnes-image-2.1-flash", "agnes-video-v2.0"],
        "note": "AGNES AI（Cherry Studio 已配置 key，2026-08-16 收录）。",
    },
    "xiaohongshu": {
        "name": "小红书 Dots Note",
        "provider": "小红书 (note3-prev-api.askdiandian.com)",
        "billing_type": "free",
        "billing_tag": "🟢 免费 (内测 API)",
        "icon": "/img/brand/xiaohongshu.png",
        "base_url": "https://note3-prev-api.askdiandian.com/v1",
        "env_key": "",
        "free": True,

        "speed": "medium",
        "default_model": "dots3-note-prev",
        "models": ["dots3-note-prev"],
        "note": "小红书 dots3-note-preview 内测端点（key 与 Cherry Studio 同源，2026-08-23 收录）。",
    },
    "zscc": {
        "name": "ZSCC",
        "provider": "ZSCC (api.zscc.in)",
        "billing_type": "free_quota",
        "billing_tag": "🟢 免费配额",
        "icon": "/img/brand/zscc.png",
        "base_url": "https://api.zscc.in/v1",
        "models_path": "/models",  # base_url 已含 /v1,/models 即 /v1/models
        "env_key": "",
        "free": True,
        
        "speed": "medium",
        "default_model": "claude-sonnet-5",
        "models": ["claude-opus-4-8", "claude-sonnet-5", "gpt-5.6-sol"],
        "note": "ZSCC（Cherry Studio 已配置 key；模型清单 2026-08-23 对齐 Cherry Studio，禁测）。",
    },
    "opencode": {
        "name": "OpenCode Go",
        "provider": "OpenCode Go (opencode.ai/zen/go)",
        "billing_type": "paid",
        "billing_tag": "🔴 付费扣费",
        "icon": "/img/brand/opencode.png",
        "base_url": "https://opencode.ai/zen/go/v1",
        "env_key": "OPENCODE_API_KEY",
        "free": False,
        
        "speed": "fast",
        "default_model": "deepseek-v4-flash",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro", "hy3"],
        "note": "OpenCode Go 渠道（用户 2026-08-15 提供），优先转发 DeepSeek V4 Flash。",
        "ua": "openai-completions/pi-ai",  # Cloudflare 1010: 必须用该 UA 才放行
    },
}

CHANNEL_ORDER = ["opencode", "modelscope", "sensetime", "ark", "agnes", "xiaohongshu", "zscc", "deepseek", "openrouter", "groq", "siliconflow", "dashscope", "zhipu"]

# 禁测渠道（用户 2026-08-16 指定）：这些渠道很贵，禁止发起任何测试/探测请求。
# - zscc：用户明确「很贵，能用就行，禁止测试」
NO_TEST_CHANNELS = {"zscc"}

# fallback 链（前端模型未匹配时按此顺序路由）
DEFAULT_CHAIN = ["opencode", "modelscope", "sensetime", "agnes", "xiaohongshu", "zscc", "deepseek", "openrouter", "groq", "siliconflow", "dashscope", "zhipu"]

_json_mtime_cache = {}  # path -> {"mtime": float|None, "data": dict}


def _cached_json(path):
    """mtime 感知的 JSON 文件缓存：文件被外部改动后下次读取自动重载。
    （2026-08-26 修复编排条目显示旧数据的 bug——原先各 loader「首次读取永久缓存」，
    unified_models.json 被手改后运行中的网关永远看不到新增条目。）"""
    ent = _json_mtime_cache.get(path)
    try:
        mt = os.path.getmtime(path)
    except OSError:
        mt = None
    if ent is None or ent["mtime"] != mt:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:  # noqa: BLE001
            data = {}
        _json_mtime_cache[path] = {"mtime": mt, "data": data}
        return data
    return ent["data"]


_config_cache = None

# 多账号 key 池轮换状态（get_key 用；key 本体存 channels.json 的 key_pools 字段）
_POOL_IDX = {}
_POOL_LOCK = threading.Lock()


# ---------------------------------------------------------------- 配置读写

def _load_config():
    """读 channels.json（网页填的 key）。mtime 感知缓存，外部改动自动重载。"""
    return _cached_json(CHANNELS_JSON)


def save_channel_key(channel_id, key):
    """把网页填的 key 存进 channels.json（明文本机）。"""
    global _config_cache
    cfg = _load_config()
    cfg.setdefault("keys", {})[channel_id] = key.strip()
    with open(CHANNELS_JSON, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    _config_cache = cfg


def get_key(channel_id):
    """渠道 key：环境变量优先，其次 channels.json；配置了 key_pools 时在
    「主 key + 池内 key」之间轮询返回（多账号摊薄免费额度，2026-08-23）。"""
    ch = CHANNELS.get(channel_id)
    if not ch:
        return ""
    env_name = ch.get("env_key", "")
    primary = ""
    if env_name:
        primary = os.environ.get(env_name, "")
    if not primary:
        primary = _load_config().get("keys", {}).get(channel_id, "")
    pool = [k for k in _load_config().get("key_pools", {}).get(channel_id, []) if k]
    keys = ([primary] if primary else []) + pool
    if len(keys) <= 1:
        return primary
    with _POOL_LOCK:
        i = _POOL_IDX.get(channel_id, -1) + 1
        _POOL_IDX[channel_id] = i
    return keys[i % len(keys)]


def get_key_pool_size(channel_id):
    """该渠道参与轮换的 key 总数（主 key + 池），供健康页展示。"""
    ch = CHANNELS.get(channel_id)
    if not ch:
        return 0
    primary = ""
    env_name = ch.get("env_key", "")
    if env_name:
        primary = os.environ.get(env_name, "")
    if not primary:
        primary = _load_config().get("keys", {}).get(channel_id, "")
    pool = [k for k in _load_config().get("key_pools", {}).get(channel_id, []) if k]
    return len(pool) + (1 if primary else 0)


# ---------------------------------------------------------------- 渠道启停开关

def get_channel_enabled(channel_id):
    """渠道启停（channels.json channel_enabled，缺省启用）。停用后路由/模型列表全部跳过。"""
    return bool(_load_config().get("channel_enabled", {}).get(channel_id, True))


def set_channel_enabled(channel_id, enabled):
    """持久化启停。启用=删键（默认即启用，保持文件干净），停用=False。"""
    global _config_cache
    cfg = _load_config()
    m = cfg.setdefault("channel_enabled", {})
    if enabled:
        m.pop(channel_id, None)
    else:
        m[channel_id] = False
    if not m:
        cfg.pop("channel_enabled", None)
    with open(CHANNELS_JSON, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    _config_cache = cfg


def invalidate_channel_cache(channel_id=None):
    """启停/改 key 后清健康缓存，下次请求立即重探。"""
    with _cache_lock:
        if channel_id:
            _health_cache.pop(channel_id, None)
        else:
            _health_cache.clear()


def _save_config(cfg):
    """合并后的配置整体写回 channels.json（新渠道/隐藏/启停共用），并即时生效。"""
    global _config_cache
    with open(CHANNELS_JSON, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    _config_cache = cfg
    _merge_custom_into_globals()


# ---------------------------------------------------------------- 自定义渠道 + 隐藏渠道

def _custom_channels():
    """channels.json 里登记的自定义渠道（网页新增，免改代码、免重启）。"""
    return _load_config().get("custom_channels", {}) or {}


def _merge_custom_into_globals():
    """把自定义渠道并入运行时 CHANNELS / CHANNEL_ORDER（in-place，免重启生效）。
    硬编码渠道同名以硬编码为准；自定义只补新增渠道 id。"""
    for cid, d in _custom_channels().items():
        if not isinstance(d, dict) or not d.get("base_url"):
            continue
        CHANNELS.setdefault(cid, d)
        if cid not in CHANNEL_ORDER:
            CHANNEL_ORDER.append(cid)


def get_hidden_channels():
    """被隐藏的渠道 id 列表（隐藏≠删除，配置与 key 全保留，随时可恢复）。"""
    hs = _load_config().get("hidden_channels") or []
    return [c for c in hs if isinstance(c, str) and c]


def set_hidden_channel(channel_id, hidden):
    """隐藏/恢复渠道。隐藏后从列表/模型/路由聚合里消失；内置与自定义渠道均可隐藏。"""
    cfg = _load_config()
    hs = set(get_hidden_channels())
    if hidden:
        hs.add(channel_id)
    else:
        hs.discard(channel_id)
    if hs:
        cfg["hidden_channels"] = sorted(hs)
    else:
        cfg.pop("hidden_channels", None)
    _save_config(cfg)
    invalidate_channel_cache(channel_id)


def save_custom_channel(channel_id, definition):
    """新增/覆盖自定义渠道。definition 必含 base_url；其余字段按 CHANNELS 惯例。"""
    cfg = _load_config()
    cc = dict(cfg.get("custom_channels", {}) or {})
    cc[channel_id] = definition
    cfg["custom_channels"] = cc
    _save_config(cfg)


def delete_custom_channel(channel_id):
    """删除自定义渠道（内置渠道不可删）。返回 True=已删，False=不存在或属内置。"""
    cc = dict(_custom_channels())
    if channel_id not in cc:
        return False
    cfg = _load_config()
    newcc = {k: v for k, v in cc.items() if k != channel_id}
    if newcc:
        cfg["custom_channels"] = newcc
    else:
        cfg.pop("custom_channels", None)
    # 清掉该渠道的 key / key_pools / 启停 / 隐藏，避免残留
    for sec in ("keys", "key_pools", "channel_enabled"):
        if isinstance(cfg.get(sec), dict) and channel_id in cfg[sec]:
            del cfg[sec][channel_id]
    if channel_id in (cfg.get("hidden_channels") or []):
        cfg["hidden_channels"] = [x for x in cfg["hidden_channels"] if x != channel_id]
        if not cfg["hidden_channels"]:
            cfg.pop("hidden_channels", None)
    # 从运行时全局移除
    CHANNELS.pop(channel_id, None)
    if channel_id in CHANNEL_ORDER:
        CHANNEL_ORDER.remove(channel_id)
    _save_config(cfg)
    invalidate_channel_cache(channel_id)
    return True


def ordered_channels():
    """可见渠道展示顺序：硬编码顺序 + 自定义追加，剔除隐藏。"""
    hidden = set(get_hidden_channels())
    return [c for c in CHANNEL_ORDER if c not in hidden]


def hidden_channels_meta():
    """已隐藏渠道的轻量元数据（不探测、不碰网络），供前端「已隐藏」折叠区展示。"""
    return [{"id": cid, "name": CHANNELS.get(cid, {}).get("name", cid),
             "icon": CHANNELS.get(cid, {}).get("icon", "🤖")} for cid in get_hidden_channels()]


# ---------------------------------------------------------------- 手动路由编排（"搭积木"）

_routing_cache = None


def load_routing():
    """读取 routing.json（每模型手动渠道顺序）。mtime 感知缓存，外部改动自动重载。"""
    return _cached_json(ROUTING_JSON)


def save_routing(model, order=None, disabled=None):
    """持久化某模型的路由规则。order=None 时删除该模型规则（恢复自动排序）。
    只保存 CHANNELS 中已知渠道 id（API 层会严格校验，这里做防御）。"""
    global _routing_cache
    cfg = load_routing()
    rules = cfg.setdefault("routing", {})
    key = (model or "").strip().lower()
    if order is None:
        rules.pop(key, None)
    else:
        rules[key] = {
            "order": [c for c in (order or []) if c in CHANNELS],
            "disabled": [c for c in (disabled or []) if c in CHANNELS],
        }
    if not rules:
        cfg.pop("routing", None)
    with open(ROUTING_JSON, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    _routing_cache = cfg


def _routing_rule(model):
    """返回 (order 列表, disabled 集合) 给某模型；无规则/规则全空 → (None, None)。"""
    key = (model or "").strip().lower()
    rule = load_routing().get("routing", {}).get(key)
    if not rule or not isinstance(rule, dict):
        return None, None
    order = rule.get("order") or []
    disabled = set(rule.get("disabled") or [])
    if not order and not disabled:
        return None, None
    return order, disabled


def key_is_set(channel_id):
    return bool(get_key(channel_id))


# ---------------------------------------------------------------- 自定义可用模型（overrides）

_overrides_cache = None


def load_model_overrides():
    """读取 model_overrides.json：{custom:[{name,channel,model}], hidden:[模型名]}。
    custom = 自定义模型别名（公开模型名 → 指定渠道+上游实际模型名）；
    hidden = 从模型列表隐藏的自动发现模型（路由仍可用，只是不展示）。
    mtime 感知缓存，外部改动自动重载。"""
    return _cached_json(MODEL_OVERRIDES_JSON)


def save_model_overrides(cfg):
    global _overrides_cache
    with open(MODEL_OVERRIDES_JSON, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    _overrides_cache = cfg


def add_custom_model(name, channel_id, upstream_model):
    """新增/覆盖一个自定义模型别名。同名覆盖（不区分大小写）。"""
    cfg = load_model_overrides()
    customs = [c for c in (cfg.get("custom") or [])
               if c.get("name", "").strip().lower() != name.strip().lower()]
    customs.append({"name": name.strip(), "channel": channel_id,
                    "model": (upstream_model or "").strip()})
    cfg["custom"] = customs
    save_model_overrides(cfg)


def remove_custom_model(name):
    cfg = load_model_overrides()
    cfg["custom"] = [c for c in (cfg.get("custom") or [])
                     if c.get("name", "").strip().lower() != name.strip().lower()]
    save_model_overrides(cfg)


def set_hidden_models(names):
    cfg = load_model_overrides()
    cfg["hidden"] = sorted({n.strip().lower() for n in (names or []) if n and n.strip()})
    save_model_overrides(cfg)


def _custom_provider_entry(cid, upstream, h):
    """构造自定义模型条目的 provider 描述（形状与 model_providers 一致）。"""
    ch = CHANNELS.get(cid, {})
    st = h.get(cid, {})
    return {
        "id": cid,
        "name": ch.get("name", cid),
        "icon": ch.get("icon", "🤖"),
        "provider": ch.get("provider", ""),
        "base_url": ch.get("base_url", ""),
        "billing_type": ch.get("billing_type", "free"),
        "billing_tag": ch.get("billing_tag", ""),
        "billing_label": "免费" if ch.get("billing_type") in ("free", "free_quota") else "付费",
        "speed": ch.get("speed", "medium"),
        "speed_label": {"fast": "快", "medium": "中", "slow": "慢"}.get(ch.get("speed", "medium"), "中"),
        "reachable": st.get("reachable", False),
        "key_set": st.get("key_set", False),
        "matched_models": [upstream],
        "no_test": cid in NO_TEST_CHANNELS,
        "balance": st.get("balance", ""),
        "custom": True,
    }


# ---------------------------------------------------------------- 统一模型组（跨厂商归一名）

UNIFIED_JSON = os.path.join(DATA_DIR, "unified_models.json")

_unified_cache = None


def normalize_model_name(name):
    """归一模型名：小写、空格/下划线 → 短横线（统一模型名以此为准）。"""
    return ((name or "").strip().lower().replace(" ", "-").replace("_", "-"))


def load_unified():
    """读取 unified_models.json：{统一名: {display?, members:{渠道id: 上游模型名}}}。
    统一名 = 我的 API 对外唯一模型名；members = 各渠道实际转发的上游真实模型名。
    mtime 感知缓存，外部改动自动重载（编排条目 3/5 显示 bug 根因修复）。"""
    return _cached_json(UNIFIED_JSON)


def save_unified(cfg):
    global _unified_cache
    with open(UNIFIED_JSON, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    _unified_cache = cfg


def set_unified_model(name, members, display=None):
    """新增/更新统一模型组。members: {channel_id: 上游模型名}，至少一项且渠道合法。同名覆盖。"""
    nm = normalize_model_name(name)
    if not nm:
        raise ValueError("统一模型名不能为空")
    clean = {}
    for cid, up in (members or {}).items():
        if cid in CHANNELS and (up or "").strip():
            clean[cid] = up.strip()
    if not clean:
        raise ValueError("至少需要一个有效成员（渠道存在且上游模型名非空）")
    cfg = load_unified()
    entry = {"members": clean}
    if display and display.strip():
        entry["display"] = display.strip()
    cfg[nm] = entry
    save_unified(cfg)
    sync_dsh_models()
    return entry


def delete_unified_model(name):
    cfg = load_unified()
    nm = normalize_model_name(name)
    if nm in cfg:
        cfg.pop(nm, None)
        save_unified(cfg)
        sync_dsh_models()


# ---------------------------------------------------------------- DSH 同步（统一编排 → ~/.dsh/settings.yaml）

DSH_SETTINGS = os.path.expanduser("~/.dsh/settings.yaml")


def sync_dsh_models():
    """把统一模型组同步为 DSH 选择器清单（settings.yaml 热重载，免重启）。
    只托管 llm-pi-ai.providers.local-gateway.models 条目的 id（统一名）与
    name（display）；条目上的其他自定义字段（如 DSH 侧手工调优的 maxTokens
    输出预算）按 id 原样保留，编排改动不会抹掉它们；默认模型若被删则回落
    到第一项；provider 其余字段原样保留。任何失败不影响网关自身。"""
    try:
        import yaml
        unified = load_unified()
        entries = []
        for gname, g in unified.items():
            mid = normalize_model_name(gname)
            if not mid:
                continue
            m = {"id": mid}
            if (g.get("display") or "").strip():
                m["name"] = g["display"].strip()
            entries.append(m)
        if not entries:
            return  # 全删空时不清空 DSH，保留最后一份可用清单
        with open(DSH_SETTINGS, "r", encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        providers = ((doc.get("llm-pi-ai") or {}).get("providers") or {})
        prov = providers.get("local-gateway")
        if not isinstance(prov, dict):
            return  # 本机没有 local-gateway 路由，不同步
        prev = {}
        for m0 in (prov.get("models") or []):
            if isinstance(m0, dict) and isinstance(m0.get("id"), str):
                prev[m0["id"]] = m0
        for m in entries:
            for k, v in prev.get(m["id"], {}).items():
                if k not in ("id", "name"):
                    m[k] = v
        prov["models"] = entries
        adm = doc.get("agent-default-model")
        ids = [m["id"] for m in entries]
        if isinstance(adm, dict) and adm.get("provider") == "local-gateway" \
                and adm.get("model") not in ids:
            adm["model"] = ids[0]
        tmp = DSH_SETTINGS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp, DSH_SETTINGS)
    except Exception:  # noqa: BLE001
        pass


def unified_suggest(q, limit=60):
    """按子串扫描各渠道在线模型，返回 {cid: [上游模型名,...]}，供建组时预填。"""
    qq = normalize_model_name(q)
    if not qq:
        return {}
    h = cached_health_all()
    out = {}
    for cid in ordered_channels():
        st = h.get(cid, {})
        if not st.get("enabled", True) or not st.get("key_set"):
            continue
        hits = [m for m in (st.get("models") or []) if qq in normalize_model_name(m)]
        if hits:
            out[cid] = hits[:limit]
    return out


# ---------------------------------------------------------------- 渠道模型选择（单渠道已选置顶）

CHANNEL_MODELS_JSON = os.path.join(DATA_DIR, "channel_models.json")

_channel_models_cache = None


def load_channel_models():
    """读取 channel_models.json：{渠道id: {selected:[模型名,...]}}。
    渠道无条目 = 未策展，对外暴露全量模型；有条目 = 只暴露已选（详情页仍可看全量、按名调用不受限）。
    mtime 感知缓存，外部改动自动重载。"""
    return _cached_json(CHANNEL_MODELS_JSON)


def save_channel_models(cfg):
    global _channel_models_cache
    with open(CHANNEL_MODELS_JSON, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    _channel_models_cache = cfg


def get_channel_selection(cid):
    """返回该渠道已选模型列表；未策展返回 None（区别于"选了但为空"——空列表同样视为未策展）。"""
    sel = (load_channel_models().get(cid) or {}).get("selected")
    if not isinstance(sel, list) or not sel:
        return None
    return list(sel)


def set_channel_selection(cid, names):
    """保存渠道已选模型；空列表 = 取消策展（回到全量）。返回清洗后的列表。"""
    if cid not in CHANNELS:
        raise ValueError("未知渠道: " + cid)
    clean, seen = [], set()
    for n in names or []:
        n = (n or "").strip()
        if n and n not in seen:
            seen.add(n)
            clean.append(n)
    cfg = load_channel_models()
    if clean:
        cfg[cid] = {"selected": clean}
    else:
        cfg.pop(cid, None)
    save_channel_models(cfg)
    return clean


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





def _build_opener(channel_id=None):
    """根据渠道是否配置 proxy,返回 (opener 或 None)。渠道配 proxy 时走该代理(如本机 mihomo 7890 访问被墙的 Google)。"""
    ch = CHANNELS.get(channel_id or "", {})
    proxy = ch.get("proxy", "")
    if proxy:
        handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        return urllib.request.build_opener(handler)
    return None


def _urlopen(req, timeout=120, channel_id=None):
    """带可选代理的 urlopen。渠道配 proxy 且代理可用时走代理，否则直连。"""
    opener = _build_opener(channel_id)
    if opener:
        try:
            return opener.open(req, timeout=timeout)
        except (urllib.error.URLError, OSError, TimeoutError, ConnectionError):
            # 代理失败回退直连
            return urllib.request.urlopen(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)

def _get_json(url, key, timeout=8, ua="unified-ai-gateway/1.0", channel_id=None):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key}",
        "User-Agent": ua,
    })
    with _urlopen(req, timeout=timeout, channel_id=channel_id) as resp:
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
        return {"id": channel_id, "name": name, "icon": icon, "key_set": False, "reachable": False,
                "models": list(ch.get("models") or []),  # 未填 key 也回退到硬编码目录，供渠道详情页展示
                "error": "待填 key（网页渠道管理页填入）", "can_fill": can_fill,
                "provider": provider, "billing_tag": billing_tag, "billing_type": billing_type,
                "balance": "未配置 Key"}

    balance = get_balance(channel_id, key)
    # 禁测渠道：不发起任何网络探测（很贵），仅按 key 状态静态标记可达
    if channel_id in NO_TEST_CHANNELS:
        return {"id": channel_id, "name": name, "icon": icon, "key_set": True, "reachable": True,
                "models": ch.get("models", []), "error": "禁测（贵）· 不探测", "can_fill": can_fill,
                "provider": provider, "billing_tag": billing_tag, "billing_type": billing_type,
                "balance": balance}
    base = ch["base_url"].rstrip("/")
    try:
        if channel_id == "openrouter":
            data = _get_json(base + "/models", key, timeout=8, ua=ch.get("ua", "unified-ai-gateway/1.0"), channel_id=channel_id)
            models = sorted({m["id"] for m in data.get("data", []) if m.get("id")})
            return {"id": channel_id, "name": name, "icon": icon, "key_set": True, "reachable": True, "models": models,
                    "error": "", "can_fill": can_fill, "provider": provider,
                    "billing_tag": billing_tag, "billing_type": billing_type, "balance": balance}
        if channel_id == "ark":
            # 方舟目录带 status 字段：滤掉 Shutdown/Retiring，只留可用模型
            data = _get_json(base + "/models", key, timeout=12, ua=ch.get("ua", "unified-ai-gateway/1.0"), channel_id=channel_id)
            models = sorted({m["id"] for m in (data.get("data") or [])
                             if m.get("id") and m.get("status") not in ("Shutdown", "Retiring")})
            return {"id": channel_id, "name": name, "icon": icon, "key_set": True, "reachable": True, "models": models,
                    "error": "", "can_fill": can_fill, "provider": provider,
                    "billing_tag": billing_tag, "billing_type": billing_type, "balance": balance}
        models_path = ch.get("models_path", "/models")
        data = _get_json(base + models_path, key, timeout=ch.get("health_timeout", 8), ua=ch.get("ua", "unified-ai-gateway/1.0"), channel_id=channel_id)
        models = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
        if channel_id == "gemini":
            models = [m.split("/", 1)[-1] for m in models if m]  # 去掉 models/ 前缀
        models = sorted(set(models or ch.get("models", [])))  # 全量目录，不再截断（前端按厂商分组展示）
        return {"id": channel_id, "name": name, "icon": icon, "key_set": True, "reachable": True, "models": models,
                "error": "", "can_fill": can_fill, "provider": provider,
                "billing_tag": billing_tag, "billing_type": billing_type, "balance": balance}
    except urllib.error.HTTPError as e:
        # 与下方通用 Exception 分支一致：health_fallback_ok=true 时，即使目录接口
        # 返回 HTTP 错误（如 Cloudflare 的 /models 返回 405 GET not supported），
        # 只要 chat 接口可用（配置了硬编码目录），也标记为可达，避免被路由跳过。
        fb_ok = bool(ch.get("health_fallback_ok"))
        return {"id": channel_id, "name": name, "icon": icon, "key_set": True, "reachable": fb_ok,
                "models": list(ch.get("models") or []),  # 探测失败回退硬编码目录，避免「渠道有模型却显示 0」
                "error": "" if fb_ok else f"HTTP {e.code}", "can_fill": can_fill, "provider": provider,
                "billing_tag": billing_tag, "billing_type": billing_type, "balance": balance}
    except Exception as e:  # noqa: BLE001
        # health_fallback_ok：/models 探测失败（如限流超时）时回退硬编码目录并标记可达，
        # 避免渠道实际可用（chat 接口正常）却因目录接口超时被路由跳过
        fb_ok = bool(ch.get("health_fallback_ok"))
        return {"id": channel_id, "name": name, "icon": icon, "key_set": True, "reachable": fb_ok,
                "models": list(ch.get("models") or []),  # 同上：异常也回退硬编码目录
                "error": "" if fb_ok else str(e)[:120], "can_fill": can_fill, "provider": provider,
                "billing_tag": billing_tag, "billing_type": billing_type, "balance": balance}


def health_all():
    return {cid: channel_health(cid) for cid in ordered_channels()}


# ---------------------------------------------------------------- 健康缓存（避免每次请求都打 7 家 API）

_health_cache = {}
_cache_lock = threading.Lock()


def _augment_health(cid, st):
    """健康条目补充运行时字段：启停开关 + key 池大小 + 已选模型数（不污染缓存原件）。"""
    st = dict(st)
    st["enabled"] = get_channel_enabled(cid)
    st["key_pool"] = get_key_pool_size(cid)
    st["custom"] = cid in _custom_channels()
    sel = get_channel_selection(cid)
    st["sel_count"] = len(sel) if sel is not None else None
    ch = CHANNELS.get(cid, {})
    promos = _cached_json(PROMOS_JSON)
    st["promo"] = promos.get(cid) or ch.get("promo") or ""
    st["free_models"] = ch.get("free_models") or []
    return st


def cached_health_all(ttl=60):
    """带 TTL 的渠道健康缓存；过期渠道并发惰性刷新，避免串行网络探测阻塞启动。"""
    now = time.time()
    out = {}
    stale = []
    with _cache_lock:
        for cid in ordered_channels():
            hit = _health_cache.get(cid)
            if hit and now - hit[0] < ttl:
                out[cid] = _augment_health(cid, hit[1])
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
                    out[cid] = _augment_health(cid, r)
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

def _parse_trailing_json(data):
    """容忍 chunked 编码尾部多余的十六进制长度/CRLF，返回最后一个完整 JSON 对象。"""
    text = data.decode("utf-8", "ignore")
    depth = 0
    start = None
    last_obj = None
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            if depth == 0:
                start = i
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0 and start is not None:
                candidate = text[start:i + 1]
                try:
                    last_obj = json.loads(candidate)
                except Exception:  # noqa: BLE001
                    last_obj = None
    return last_obj


def _sse_usage(text):
    """从 SSE 流文本中提取末尾 usage 的 prompt_tokens/completion_tokens。"""
    import re
    pat = re.compile(r'"usage"\s*:\s*\{[^}]*\}')
    matches = pat.findall(text)
    if not matches:
        return 0, 0
    usage = matches[-1]
    pt = re.search(r'"prompt_tokens"\s*:\s*(\d+)', usage)
    ct = re.search(r'"completion_tokens"\s*:\s*(\d+)', usage)
    return (int(pt.group(1)) if pt else 0), (int(ct.group(1)) if ct else 0)


def _sse_content_chars(text):
    """累加 SSE 流里所有 delta.content 的字符数（流式估算输出 token 用）。"""
    n = 0
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        body = line[5:].strip()
        if not body or body == "[DONE]":
            continue
        try:
            obj = json.loads(body)
        except Exception:  # noqa: BLE001
            continue
        for c in (obj.get("choices") or []):
            d = c.get("delta") or {}
            v = d.get("content")
            if isinstance(v, str):
                n += len(v)
            elif isinstance(v, list):
                for part in v:
                    if isinstance(part, dict):
                        n += len(part.get("text") or "")
    return n


def _est_tokens(text):
    """上游不返回 usage 时的粗估：≈3 字符/token（中英混合量级参考，非精确值）。"""
    return max(1, round(len(text) / 3)) if text else 0


class _QuotaResponse:
    """包装 urllib response：响应成功时记录本地额度（task_011）。接口与 urllib response 兼容。"""

    def __init__(self, channel_id, model, is_stream, upstream, key="", route_info=None, req_text=""):
        self._channel = channel_id
        self._model = model
        self._key = key  # 实际使用的 key（用于 shell 检测后正确回填 429）
        self._is_stream = is_stream
        self._up = upstream
        self._recorded = False
        self._stream_buf = bytearray()
        self._route_info = route_info or {}
        # 上游不返回 usage 时的输入 token 粗估基准（请求 messages 序列化文本）
        self._req_est = _est_tokens(req_text)

    def _record(self, success, input_tokens=0, output_tokens=0):
        if self._recorded:
            return
        self._recorded = True
        if _record_call is not None:
            try:
                _record_call(GATEWAY_ID, self._channel, self._model,
                             input_tokens=input_tokens, output_tokens=output_tokens,
                             success=success)
            except Exception:  # noqa: BLE001
                pass

    def getheader(self, name, default=None):
        return self._up.getheader(name, default)

    def read(self, size=-1):
        if self._is_stream:
            chunk = self._up.read(size)
            if chunk:
                self._stream_buf.extend(chunk)
                return chunk
            self._finalize_stream()
            return b""
        # 非流式：读取全量（http.client 会自动剥离 chunked 终止符），解析 usage 后记录
        data = self._up.read() if size < 0 else self._up.read(size)
        if not data:
            return b""
        self._finalize_json(data)
        return data

    def read1(self, size=-1):
        return self.read(size)

    def _finalize_json(self, data):
        try:
            obj = _parse_trailing_json(data)
            if obj is None:
                self._record(False)
                return
            usage = obj.get("usage", {}) or {}
            it, ot = int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0)
            if it == 0 and ot == 0:
                # 上游没回 usage（如 modelscope 免费档）：按响应正文长度粗估输出，输入用请求基准
                it = self._req_est
                ot = _est_tokens(json.dumps(obj.get("choices", ""), ensure_ascii=False))
            self._record(True, input_tokens=it, output_tokens=ot)
        except Exception:  # noqa: BLE001
            self._record(False)

    def _finalize_stream(self):
        # 从 SSE 尾部尝试解析 usage（尽力而为）；没有 usage 就按 delta 内容长度粗估
        try:
            text = bytes(self._stream_buf).decode("utf-8", "ignore")
            it, ot = _sse_usage(text)
            if it == 0 and ot == 0:
                it = self._req_est
                ot = _est_tokens(_sse_content_chars(text) * "x")
            self._record(True, input_tokens=it, output_tokens=ot)
        except Exception:  # noqa: BLE001
            self._record(True)

    def force_finalize(self):
        """客户端提前断开等场景的兜底记账：流没读到 EOF 时 read 循环不会再触发
        _finalize_stream，这里主动补记一次（幂等，_recorded 防重）。非流式交给 read。"""
        if self._recorded or not self._is_stream:
            return
        try:
            self._finalize_stream()
        except Exception:  # noqa: BLE001
            pass

    def close(self):
        try:
            self._up.close()
        except Exception:  # noqa: BLE001
            pass


def chat_completion(channel_id, payload, route_info=None):
    """转发 chat/completions 到指定渠道。返回 _QuotaResponse（urllib 兼容 + 记录额度）。
    route_info 可选，透传路由决策信息供响应头使用。
    配置了 key_pools 时，遇 429 自动换下一把 key 重试，最多轮完一圈。
    限流准入（task_045）：每次真实 HTTP attempt 前原子 try_acquire 预占配额——
    key 池轮一圈是 N 次上游请求就预占 N 次；某把 key 的桶满/熔断只跳过该 key，
    全部 key 被拒才抛 RateLimitSkip 让上层走下一渠道（用户顺序不变）。"""
    ch = CHANNELS[channel_id]
    primary = get_key(channel_id)
    if not primary:
        raise RuntimeError(f"{ch['name']} 未配置 key")
    req_payload = dict(payload)
    # developer 角色 → system（部分渠道不认 developer）
    for m in req_payload.get("messages", []):
        if m.get("role") == "developer":
            m["role"] = "system"
    model = req_payload.get("model") or ch.get("default_model", "")
    ua = ch.get("ua", "unified-ai-gateway/1.0")
    url = ch["base_url"].rstrip("/") + "/chat/completions"
    body = json.dumps(req_payload).encode("utf-8")

    attempts = max(1, get_key_pool_size(channel_id))
    last_err = None
    acquired_any = False
    for i in range(attempts):
        key = get_key(channel_id)  # 每圈取下一把（get_key 内部轮换）
        if _rate_limit is not None and not _rate_limit.try_acquire(channel_id, model, key):
            continue  # 该 key 的配额桶满/429 熔断中 → 换下一把（不同账号仍有容量）
        acquired_any = True
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": ua,
        }
        if req_payload.get("stream"):
            headers["Accept"] = "text/event-stream"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            resp = _urlopen(req, timeout=300, channel_id=channel_id)
        except urllib.error.HTTPError as he:
            if _rate_limit is not None:
                ra = (he.headers or {}).get("Retry-After") if he.headers else None
                _rate_limit.record_result(channel_id, model, key, he.code, retry_after=ra)
            if he.code == 429 and i < attempts - 1:
                he.read()  # 消费 body 便于连接复用
                last_err = he
                continue  # 换下一把 key 再试
            raise
        except Exception:  # noqa: BLE001
            # 本地/网络异常：无法确认请求是否已发出，保守不回滚预占（最多多占一个窗口位）
            raise
        # 不立即 record_result(200)：等 route_completion 验证通过后再记（P0-1：否则 200 清空 consec429）
        return _QuotaResponse(channel_id, model, req_payload.get("stream"), resp, key=key,
                              route_info=route_info,
                              req_text=json.dumps(req_payload.get("messages", ""), ensure_ascii=False))
    if last_err is not None:
        raise last_err  # 全部 key 都 429
    if not acquired_any and _rate_limit is not None:
        raise _rate_limit.RateLimitSkip(
            f"{ch['name']} 触发限流保护（95% 提前切换），本轮跳过")
    raise RuntimeError(f"{ch['name']} 无可用请求")


def mark_shell_failure(channel_id, model, key=""):
    """上游以 HTTP 200 返回空壳/错误载荷时由 api_gateway 回填：按合成 429 记入限流台账，
    触发指数退避熔断，让后续请求 try_acquire 直接跳过该渠道（否则统一组每次重试
    都会先撞一遍这个死渠道再 failover，客户端侧表现为反复重启不换渠道）。
    连续失败按 BACKOFF_STEPS 15s→300s 升级；成功请求照常清零计数。
    key：实际产生该空壳的 key（由调用方从 _QuotaResponse._key 传入，避免重新 get_key
    轮换到错误 key — P0-2 修复）。"""
    if _rate_limit is None:
        return
    try:
        if key:
            _rate_limit.record_result(channel_id, model, key, 429)
    except Exception:  # noqa: BLE001
        pass


def record_channel_success(channel_id, model, key):
    """验证通过后记录渠道成功（P0-1：延迟记录，避免 HTTP 200 提前清零 consec429）。
    由 route_completion 在空壳/流式首包验证通过后调用。"""
    if _rate_limit is None:
        return
    try:
        if key:
            _rate_limit.record_result(channel_id, model, key, 200)
    except Exception:  # noqa: BLE001
        pass


def model_to_chain(model):
    """模型名 → 渠道候选链。
    统一用包含搜索 + 智能排序（免费优先 → 速度快优先）。
    这样 deepseek-v4-flash 会自动映射到 modelscope 的 deepseek-ai/DeepSeek-V4-Flash-0731、
    zscc 的 deepseek-v4-flash-cc 等（后缀不同但本质同一模型）。
    与前端 /api/model_providers 反查逻辑完全一致。"""
    providers = model_providers(model)
    if providers:
        # 已按 _channel_sort_key 排序：免费优先 → 速度快优先 → 渠道顺序
        return [p["id"] for p in providers if p.get("reachable")]
    # 无匹配：用 DEFAULT_CHAIN 兜底
    return DEFAULT_CHAIN


# ---------------------------------------------------------------- 模型反查 & 智能排序

def _channel_sort_key(cid, st):
    """渠道排序键：(免费优先, 速度快优先, 渠道顺序)。
    返回元组，越小越靠前。"""
    ch = CHANNELS.get(cid, {})
    billing = ch.get("billing_type", "free")
    speed = ch.get("speed", "medium")
    speed_rank = {"fast": 0, "medium": 1, "slow": 2}.get(speed, 1)
    free_rank = 0 if billing in ("free", "free_quota") else 1  # 免费在前
    order_rank = CHANNEL_ORDER.index(cid) if cid in CHANNEL_ORDER else 99
    return (free_rank, speed_rank, order_rank)


def _apply_routing_rule(matched, model_name):
    """按保存的路由规则重排智能排序后的 provider 列表（"搭积木"顺序）。
    用户手动排序的渠道提到最前（严格按 order 顺序，只在当前匹配到的渠道中取）；
    其余匹配渠道（不在 order）按现有智能顺序补后；disabled 渠道整体剔除。
    无规则/全空 → 原样返回。"""
    order, disabled = _routing_rule(model_name)
    if order is None and not disabled:
        return matched
    if disabled:
        matched = [p for p in matched if p["id"] not in disabled]
        if not order:
            return matched
    by_id = {p["id"]: p for p in matched}
    head = [by_id[cid] for cid in order if cid in by_id]
    tail = [p for p in matched if p["id"] not in order]
    return head + tail


def effective_order(model_name):
    """某模型应用路由规则后的渠道 id 顺序（含未配置 key 的会被跳过）。
    作为测试/参考的单点真源；与 model_providers 返回顺序一致。"""
    return [p["id"] for p in model_providers(model_name)]


def all_models():
    """聚合所有在线渠道的全部模型（去重），返回 [{name, providers:[cid,...]}]。
    每个 provider 含 {id, name, icon, billing_type, billing_tag, speed, reachable}。"""
    h = cached_health_all()
    sel_map = load_channel_models()
    model_map = {}  # model_name -> {providers: []}
    for cid in ordered_channels():
        st = h.get(cid, {})
        if not st.get("enabled", True) or not st.get("key_set") or not st.get("reachable"):
            continue
        ch = CHANNELS.get(cid, {})
        models = st.get("models", []) or []
        # 渠道模型策展：已选列表存在时，对外只暴露已选（详情页仍可看全量、按名调用不受限）
        sel = (sel_map.get(cid) or {}).get("selected")
        if isinstance(sel, list) and sel:
            sset = set(sel)
            models = [m for m in models if m in sset]
        for m in models:
            if m not in model_map:
                model_map[m] = {"name": m, "providers": []}
            model_map[m]["providers"].append({
                "id": cid,
                "name": ch.get("name", cid),
                "icon": ch.get("icon", "🤖"),
                "billing_type": ch.get("billing_type", "free"),
                "billing_tag": ch.get("billing_tag", ""),
                "speed": ch.get("speed", "medium"),
                "speed_label": {"fast": "快", "medium": "中", "slow": "慢"}.get(ch.get("speed", "medium"), "中"),
                "reachable": st.get("reachable", False),
                "no_test": cid in NO_TEST_CHANNELS,
            })
    # 自定义模型别名：注入为该模型的 provider（渠道已匹配则跳过，防重复）
    for c in load_model_overrides().get("custom") or []:
        cid, nm = c.get("channel", ""), (c.get("name") or "").strip()
        if not nm or cid not in CHANNELS:
            continue
        st = h.get(cid, {})
        if st.get("enabled") is False or not st.get("key_set"):
            continue
        mm = model_map.setdefault(nm, {"name": nm, "providers": []})
        if not any(p["id"] == cid for p in mm["providers"]):
            mm["providers"].append(_custom_provider_entry(cid, c.get("model") or nm, h))
    # 隐藏模型：不出现在模型列表（直接按名请求仍可路由）
    for nm in set(load_model_overrides().get("hidden") or []):
        model_map.pop(nm, None)
    # 统一模型组：跨厂商归一名 → 覆盖为独立条目（成员=显式配置的各渠道上游名）
    for uname, u in load_unified().items():
        provs = []
        for cid, up in (u.get("members") or {}).items():
            st = h.get(cid, {})
            if not st.get("enabled", True) or not st.get("key_set"):
                continue
            provs.append(_custom_provider_entry(cid, up, h))
        if provs:
            model_map[uname] = {"name": uname, "providers": provs, "unified": True}
            if u.get("display"):
                model_map[uname]["display"] = u["display"]
    # 每个 model 的 providers 按智能排序
    for m in model_map:
        model_map[m]["providers"].sort(key=lambda x: _channel_sort_key(x["id"], {}))
    # 模型按 providers 数量降序、名字升序
    out = sorted(model_map.values(), key=lambda x: (-len(x["providers"]), x["name"].lower()))
    return out


def _resolve_prefixed_model(q):
    """解析 "provider:model" 形式的模型 id（Claude Code / Cherry Studio 自定义模型格式）。
    返回 (真实模型名, 钉定渠道或 None)。规则：
    - 冒号前部分恰好是网关渠道 id（如 opencode:deepseek-v4-flash）→ 剥前缀并钉定该渠道；
    - 或是已知的 Cherry Studio provider uuid（sync_cherry.CHERRY_MAP 反查，如
      3f3af7c6-…:deepseek-v4-flash-vision-exp）→ 映射回对应渠道；
    - 其余含冒号模型名（如 openrouter 的 z-ai/glm-5.2:free）不匹配任何前缀，原样返回，
      避免误伤上游真实带冒号的变体名。"""
    if ":" not in q:
        return q, None
    head, tail = q.split(":", 1)
    if head in CHANNELS:
        return tail, head
    try:
        from sync_cherry import CHERRY_MAP as _CHERRY_MAP  # 同目录懒加载，避免循环 import
        rev = {pid: cid for cid, pid in _CHERRY_MAP.items()}
        cid = rev.get(head)
        if cid and cid in CHANNELS:
            return tail, cid
    except Exception:  # noqa: BLE001
        pass
    return q, None


def model_providers(model_name, full=False):
    """反查支持某模型的所有渠道（包含搜索），返回按智能排序的 provider 列表。
    包含搜索：渠道模型名包含 query 即算支持（不区分大小写）。
    full=True 时返回原始智能排序结果（不应用手动路由规则、不过滤 disabled），
    供前端编辑态展示全部匹配渠道（含已排除的）。"""
    q = (model_name or "").strip().lower()
    if not q:
        return []
    # "provider:model" 前缀解析（Claude Code/Cherry Studio 自定义模型）：命中即单渠到钉定
    real, pinned = _resolve_prefixed_model(q)
    if pinned is not None:
        h = cached_health_all()
        st = h.get(pinned, {})
        if st.get("enabled", True) and st.get("key_set"):
            return [_custom_provider_entry(pinned, real, h)]
        return []
    # 统一模型组：精确命中归一名 → 只用显式成员（转发时按渠道改写为上游真实名），不参与包含搜索
    uni = load_unified().get(normalize_model_name(q))
    if uni is not None:
        h = cached_health_all()
        members = []
        for cid, up in (uni.get("members") or {}).items():
            st = h.get(cid, {})
            if not st.get("enabled", True) or not st.get("key_set"):
                continue
            members.append(_custom_provider_entry(cid, up, h))
        members.sort(key=lambda x: _channel_sort_key(x["id"], {}))
        return members if full else _apply_routing_rule(members, model_name)
    h = cached_health_all()
    matched = []
    for cid in ordered_channels():
        st = h.get(cid, {})
        if not st.get("enabled", True) or not st.get("key_set"):
            continue
        ch = CHANNELS.get(cid, {})
        models = st.get("models", []) or []
        # 包含搜索：任一模型名包含 query
        hits = [m for m in models if q in m.lower()]
        if not hits:
            continue
        matched.append({
            "id": cid,
            "name": ch.get("name", cid),
            "icon": ch.get("icon", "🤖"),
            "provider": ch.get("provider", ""),
            "base_url": ch.get("base_url", ""),
            "billing_type": ch.get("billing_type", "free"),
            "billing_tag": ch.get("billing_tag", ""),
            "billing_label": "免费" if ch.get("billing_type") in ("free", "free_quota") else "付费",
            "speed": ch.get("speed", "medium"),
            "speed_label": {"fast": "快", "medium": "中", "slow": "慢"}.get(ch.get("speed", "medium"), "中"),
            "reachable": st.get("reachable", False),
            "key_set": st.get("key_set", False),
            "matched_models": hits,
            "no_test": cid in NO_TEST_CHANNELS,
            "balance": st.get("balance", ""),
        })
    # 自定义模型别名：精确命中别名时注入指定渠道（渠道已匹配则跳过，防重复）
    for c in load_model_overrides().get("custom") or []:
        if (c.get("name") or "").strip().lower() != q:
            continue
        cid = c.get("channel", "")
        if cid not in CHANNELS or any(x["id"] == cid for x in matched):
            continue
        st = h.get(cid, {})
        if st.get("enabled") is False or not st.get("key_set"):
            continue
        matched.append(_custom_provider_entry(cid, c.get("model") or model_name, h))
    # 智能排序：免费优先 → 速度快优先 → 渠道顺序
    matched.sort(key=lambda x: _channel_sort_key(x["id"], {}))
    if full:
        return matched  # 编辑态原始列表：不应用路由、不过滤 disabled
    # 手动路由规则（"搭积木"）：有规则则重排，无规则保持智能顺序
    return _apply_routing_rule(matched, model_name)


# ---- 启动时并入自定义渠道（网页新增的渠道免重启生效，进程重启后从 channels.json 恢复）
_merge_custom_into_globals()

