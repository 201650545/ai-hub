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
DATA_DIR = os.path.normpath(os.path.join(os.path.dirname(BASE_DIR), "..", "data", "search_gateway"))
CHANNELS_JSON = os.path.join(DATA_DIR, "channels.json")

# 本地额度统计（task_011）：调用成功后记录 quota.json，缺失时降级不记录
GATEWAY_ID = os.environ.get("GATEWAY_ID", "ds_v4_cli")
try:
    from quota import record_call as _record_call  # noqa: F401
except Exception:  # noqa: BLE001
    _record_call = None

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
    "gemini": {
        "name": "Google Gemini 官方",
        "provider": "Google (generativelanguage.googleapis.com)",
        "billing_type": "free_quota",
        "billing_tag": "🟢 免费配额 (1500次/天)",
        "icon": "✨",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "env_key": "GOOGLE_API_KEY",
        "free": True,
        "proxy": "http://127.0.0.1:7890",  # Google 被墙，走本机 mihomo 代理
        "speed": "fast",
        "default_model": "gemini-3.5-flash",
        "models": [
            "gemini-3.5-flash", "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite", "gemini-3.6-flash", "gemini-3.7-flash",
            "gemini-flash-latest", "gemini-flash-lite-latest",
            "gemini-omni-flash-preview",
        ],  # 多模态理解模型（支持图像输入）。image 生模型免费配额 429 已剔除
        "note": "谷歌官方免费配额（key 来自 Cherry Studio）。支持多模态图像理解。走 7890 代理访问（Google 被墙）。",
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
        "icon": "⚡",
        "base_url": "https://api.groq.com/openai/v1",
        "env_key": "",
        "free": True,
        
        "speed": "fast",
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
        "icon": "🗼",
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
        "icon": "🀄",
        "base_url": "https://token.sensenova.cn/v1",
        "env_key": "",
        "free": True,
        
        "speed": "medium",
        "default_model": "deepseek-v4-flash",
        "models": ["deepseek-v4-flash", "glm-5.2", "sensenova-6.8-flash-lite"],
        "note": "商汤日日新 SenseNova（Cherry Studio 已配置 key，2026-08-16 收录）。",
    },
    "agnes": {
        "name": "AGNES AI",
        "provider": "AGNES (apihub.agnes-ai.com)",
        "billing_type": "free_quota",
        "billing_tag": "🟢 免费配额",
        "icon": "🌀",
        "base_url": "https://apihub.agnes-ai.com/v1",
        "env_key": "",
        "free": True,
        
        "speed": "medium",
        "default_model": "agnes-2.5-flash",
        "models": ["agnes-2.5-flash", "agnes-image-2.1-flash", "agnes-video-v2.0"],
        "note": "AGNES AI（Cherry Studio 已配置 key，2026-08-16 收录）。",
    },
    "zscc": {
        "name": "ZSCC",
        "provider": "ZSCC (api.zscc.in)",
        "billing_type": "free_quota",
        "billing_tag": "🟢 免费配额",
        "icon": "🔮",
        "base_url": "https://api.zscc.in/v1",
        "models_path": "/models",  # base_url 已含 /v1,/models 即 /v1/models
        "env_key": "",
        "free": True,
        
        "speed": "medium",
        "default_model": "kimi-k3-cc",
        "models": ["kimi-k3-cc", "claude-opus-4-8", "claude-sonnet-5", "deepseek-v4-flash-cc"],
        "note": "ZSCC（Cherry Studio 已配置 key，2026-08-16 收录）。",
    },
    "opencode": {
        "name": "OpenCode Go",
        "provider": "OpenCode Go (opencode.ai/zen/go)",
        "billing_type": "paid",
        "billing_tag": "🔴 付费扣费",
        "icon": "💻",
        "base_url": "https://opencode.ai/zen/go/v1",
        "env_key": "OPENCODE_API_KEY",
        "free": False,
        
        "speed": "fast",
        "default_model": "deepseek-v4-flash",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
        "note": "OpenCode Go 渠道（用户 2026-08-15 提供），优先转发 DeepSeek V4 Flash。",
        "ua": "openai-completions/pi-ai",  # Cloudflare 1010: 必须用该 UA 才放行
    },
}

CHANNEL_ORDER = ["opencode", "modelscope", "sensetime", "agnes", "zscc", "deepseek", "gemini", "openrouter", "groq", "siliconflow", "dashscope", "zhipu"]

# 禁测渠道（用户 2026-08-16 指定）：这些渠道很贵，禁止发起任何测试/探测请求。
# - zscc：用户明确「很贵，能用就行，禁止测试」
NO_TEST_CHANNELS = {"zscc"}

# fallback 链（前端模型未匹配时按此顺序路由）
DEFAULT_CHAIN = ["opencode", "modelscope", "sensetime", "agnes", "zscc", "deepseek", "openrouter", "gemini", "groq", "siliconflow", "dashscope", "zhipu"]

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
        return {"id": channel_id, "name": name, "icon": icon, "key_set": False, "reachable": False, "models": [],
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
            models = [m["id"] for m in data.get("data", [])
                      if m.get("id", "").endswith(":free") or m.get("is_free")]
            models = sorted(models)[:40]
            return {"id": channel_id, "name": name, "icon": icon, "key_set": True, "reachable": True, "models": models,
                    "error": "", "can_fill": can_fill, "provider": provider,
                    "billing_tag": billing_tag, "billing_type": billing_type, "balance": balance}
        models_path = ch.get("models_path", "/models")
        data = _get_json(base + models_path, key, timeout=8, ua=ch.get("ua", "unified-ai-gateway/1.0"), channel_id=channel_id)
        models = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
        if channel_id == "deepseek":
            models = [m for m in models if m in ("deepseek-v4-flash", "deepseek-v4-pro", "deepseek-reasoner", "deepseek-chat")]
        elif channel_id == "gemini":
            models = [m.split("/", 1)[-1] for m in models if m]  # 去掉 models/ 前缀
            models = [m for m in models if "image" in m or "flash" in m or "omni" in m][:30]
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


class _QuotaResponse:
    """包装 urllib response：响应成功时记录本地额度（task_011）。接口与 urllib response 兼容。"""

    def __init__(self, channel_id, model, is_stream, upstream):
        self._channel = channel_id
        self._model = model
        self._is_stream = is_stream
        self._up = upstream
        self._recorded = False
        self._stream_buf = bytearray()

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
            self._record(True,
                         input_tokens=usage.get("prompt_tokens", 0),
                         output_tokens=usage.get("completion_tokens", 0))
        except Exception:  # noqa: BLE001
            self._record(False)

    def _finalize_stream(self):
        # 从 SSE 尾部尝试解析 usage（尽力而为）
        try:
            text = bytes(self._stream_buf).decode("utf-8", "ignore")
            data = _sse_usage(text)
            self._record(True, input_tokens=data[0], output_tokens=data[1])
        except Exception:  # noqa: BLE001
            self._record(True)

    def close(self):
        try:
            self._up.close()
        except Exception:  # noqa: BLE001
            pass


def chat_completion(channel_id, payload):
    """转发 chat/completions 到指定渠道。返回 _QuotaResponse（urllib 兼容 + 记录额度）。"""
    ch = CHANNELS[channel_id]
    key = get_key(channel_id)
    if not key:
        raise RuntimeError(f"{ch['name']} 未配置 key")
    req_payload = dict(payload)
    # developer 角色 → system（部分渠道不认 developer）
    for m in req_payload.get("messages", []):
        if m.get("role") == "developer":
            m["role"] = "system"
    ua = ch.get("ua", "unified-ai-gateway/1.0")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "User-Agent": ua,
    }
    if req_payload.get("stream"):
        headers["Accept"] = "text/event-stream"
    url = ch["base_url"].rstrip("/") + "/chat/completions"
    req = urllib.request.Request(url, data=json.dumps(req_payload).encode("utf-8"),
                                 headers=headers, method="POST")
    resp = _urlopen(req, timeout=120, channel_id=channel_id)
    model = req_payload.get("model") or ch.get("default_model", "")
    return _QuotaResponse(channel_id, model, req_payload.get("stream"), resp)


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


def all_models():
    """聚合所有在线渠道的全部模型（去重），返回 [{name, providers:[cid,...]}]。
    每个 provider 含 {id, name, icon, billing_type, billing_tag, speed, reachable}。"""
    h = cached_health_all()
    model_map = {}  # model_name -> {providers: []}
    for cid in CHANNEL_ORDER:
        st = h.get(cid, {})
        if not st.get("key_set") or not st.get("reachable"):
            continue
        ch = CHANNELS.get(cid, {})
        for m in st.get("models", []) or []:
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
    # 每个 model 的 providers 按智能排序
    for m in model_map:
        model_map[m]["providers"].sort(key=lambda x: _channel_sort_key(x["id"], {}))
    # 模型按 providers 数量降序、名字升序
    out = sorted(model_map.values(), key=lambda x: (-len(x["providers"]), x["name"].lower()))
    return out


def model_providers(model_name):
    """反查支持某模型的所有渠道（包含搜索），返回按智能排序的 provider 列表。
    包含搜索：渠道模型名包含 query 即算支持（不区分大小写）。"""
    q = (model_name or "").strip().lower()
    if not q:
        return []
    h = cached_health_all()
    matched = []
    for cid in CHANNEL_ORDER:
        st = h.get(cid, {})
        if not st.get("key_set"):
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
    # 智能排序：免费优先 → 速度快优先 → 渠道顺序
    matched.sort(key=lambda x: _channel_sort_key(x["id"], {}))
    return matched

