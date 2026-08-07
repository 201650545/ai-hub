# -*- coding: utf-8 -*-
"""
网关测试 (:3000)
覆盖：健康 / 首页 / 模型列表。渠道测试通过调用 ds_v4_cli 下的 channels 模块。
"""

import sys
import os

GATEWAY_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "02_网关实例", "ds_v4_cli"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import Result, http_get, check_service, summarize  # noqa: E402

GATEWAY_URL = "http://localhost:3000"

# 渠道测试在本网关目录下运行，加载其 channels 模块
if os.path.isdir(GATEWAY_DIR):
    sys.path.insert(0, GATEWAY_DIR)


def test_health():
    # health 会对所有引擎+渠道做探测，耗时较长
    code, body = http_get(f"{GATEWAY_URL}/api/health", timeout=40)
    if code == 200 and isinstance(body, dict) and "engines" in body:
        eng_count = len(body.get("engines", {}))
        return Result("网关健康 GET /api/health", Result.PASS, f"engines 含 {eng_count} 项")
    return Result("网关健康 GET /api/health", Result.FAIL, f"code={code} type={type(body).__name__}")


def test_home():
    code, text = http_get(f"{GATEWAY_URL}/")
    if code == 200:
        return Result("网关首页 GET /", Result.PASS, "200")
    return Result("网关首页 GET /", Result.FAIL, f"code={code}")


def test_models():
    code, body = http_get(f"{GATEWAY_URL}/v1/models", timeout=15)
    if code == 200 and isinstance(body, dict) and len(body.get("data", [])) > 0:
        return Result("模型列表 GET /v1/models", Result.PASS, f"{len(body['data'])} 个模型")
    return Result("模型列表 GET /v1/models", Result.FAIL, f"code={code}")


# ---- 渠道测试（基于 channels.py 健康探测）----

def _load_channels():
    if not GATEWAY_DIR:
        return None
    import channels
    return channels


def test_channels_health():
    ch = _load_channels()
    if ch is None:
        return Result("渠道健康(本地channels)", Result.SKIP, "网关目录缺失")
    hs = ch.health_all()
    passed = [cid for cid, h in hs.items()
              if h.get("key_set") and h.get("reachable")]
    if {"deepseek", "gemini", "openrouter"} <= set(passed):
        return Result("渠道健康(本地channels)", Result.PASS,
                      f"deepseek/gemini/openrouter reachable=True")
    detail = {cid: ("✅" if (h.get("reachable") or not h.get("key_set")) else "❌")
              for cid, h in hs.items()}
    return Result("渠道健康(本地channels)", Result.FAIL, str(detail))


def test_channels_fallback():
    ch = _load_channels()
    if ch is None:
        return Result("渠道 fallback 链", Result.SKIP, "目录网关缺失")
    chain = ch.model_to_chain("gpt-oss-120b")
    if chain == ["groq"] and ch.model_to_chain("qwen-plus") == ["dashscope"] \
            and ch.model_to_chain("glm-4-flash") == ["zhipu"]:
        return Result("渠道 fallback 链", Result.PASS,
                      "groq→gpt-oss-120b, dashscope→qwen-plus, zhipu→glm-4-flash")
    return Result("渠道 fallback 链", Result.FAIL, f"chain={chain}")


def test_channels_ping():
    ch = _load_channels()
    if ch is None:
        return Result("渠道测试请求", Result.SKIP, "目录网关缺失")
    # 对已配置 key 的渠道发一条测试消息。openrouter 用当前可用免费模型（默认模型可能下架）
    results = []
    for cid in ("deepseek", "gemini", "openrouter"):
        if not ch.key_is_set(cid):
            continue
        model = ch.CHANNELS[cid]["default_model"]
        if cid == "openrouter":
            avail = ch.channel_health(cid).get("models", [])
            if avail:
                model = avail[0]
        try:
            resp = ch.chat_completion(cid, {
                "model": model,
                "messages": [{"role": "user", "content": "ping：请只回复 OK"}],
                "stream": False,
            })
            data = __import__("json").loads(resp.read().decode("utf-8", "ignore"))
            content = (data.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()
            results.append(f"{cid}:{'PASS' if content else '空回复'}")
        except Exception as e:  # noqa: BLE001
            results.append(f"{cid}:FAIL({str(e)[:40]})")
    if results and all("PASS" in r for r in results):
        return Result("渠道测试请求", Result.PASS, ", ".join(r.split(":")[0] + ":OK" for r in results))
    return Result("渠道测试请求", Result.FAIL, " ".join(results))
def run_all():
    results = []
    if check_service(f"{GATEWAY_URL}/", "网关 :3000"):
        results.append(test_health())
        results.append(test_home())
        results.append(test_models())
    else:
        results.append(Result("网关服务检查", Result.SKIP, "服务未启动"))
    if os.path.isdir(GATEWAY_DIR):
        results.append(test_channels_health())
        results.append(test_channels_fallback())
        results.append(test_channels_ping())
    else:
        results.append(Result("渠道测试", Result.SKIP, "网关目录缺失"))
    return results


if __name__ == "__main__":
    for r in run_all():
        print(r)
    summarize(run_all(), "网关")
