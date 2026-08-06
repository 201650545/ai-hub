# -*- coding: utf-8 -*-
"""
task_006 渠道验证脚本
验证 4 个新增 LLM 渠道（Groq / 硅基流动 / 通义 DashScope / 智谱 GLM）是否可用。

用法：
    python test_channels.py                # 检查全部渠道 key 与连通性
    python test_channels.py --ping groq    # 仅 ping 单个渠道（发一条测试请求）
    python test_channels.py --fallback     # 测试 fallback 链路由

Key 来源（优先级）：环境变量 > config/channels.json > 本地 channels.json
  例如：$env:GROQ_API_KEY="gsk_..." 或编辑 D:\\项目\\config\\channels.json
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import channels  # noqa: E402

NEW_CHANNELS = ["groq", "siliconflow", "dashscope", "zhipu"]


def check_key(channel_id):
    ch = channels.CHANNELS.get(channel_id, {})
    key = channels.get_key(channel_id)
    env_name = ch.get("env_key", "")
    source = "env" if env_name and os.environ.get(env_name) else (
        "config/channels.json" if key and key != channels._load_config().get("keys", {}).get(channel_id) else "本地channels.json")
    return {"id": channel_id, "name": ch.get("name"), "key_set": bool(key),
            "env_key": env_name, "source": source, "key_prefix": (key[:8] + "…") if key else ""}


def health_report():
    hs = channels.health_all()
    print("=" * 60)
    for cid in channels.CHANNEL_ORDER:
        h = hs[cid]
        flag = "✅" if (h["key_set"] and h["reachable"]) else ("🟡 未配置key" if not h["key_set"] else "❌")
        print(f"  {flag}  {cid:12s} {h['name']}  余额: {h['balance']}  {h['error'][:40]}")
    print("=" * 60)


def ping_one(channel_id):
    ch = channels.CHANNELS.get(channel_id)
    if not ch:
        print(f"未知渠道 {channel_id}"); return 1
    if not channels.key_is_set(channel_id):
        print(f"⚠️ {channel_id} 未配置 key，先写入 config/channels.json 或设置环境变量 {ch.get('env_key','')}")
        return 1
    t0 = time.time()
    try:
        resp = channels.chat_completion(channel_id, {
            "model": ch["default_model"],
            "messages": [{"role": "user", "content": "ping：请只回复 OK"}],
            "stream": False,
        })
        data = json.loads(resp.read().decode("utf-8", "ignore"))
        reply = (data.get("choices", [{}])[0].get("message", {}).get("content", ""))[:60]
        print(f"✅ {channel_id} ({ch['name']}) 成功  {int((time.time()-t0)*1000)}ms  → {reply}")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"❌ {channel_id} ({ch['name']}) 失败: {type(e).__name__}: {str(e)[:150]}")
        return 1


def test_fallback_chain():
    print("测试 fallback 链路由（model_to_chain）：")
    cases = ["deepseek-v4-flash", "gemini-2.5-flash", "gpt-oss-120b", "deepseek-ai/DeepSeek-V3",
             "qwen-plus", "glm-4-flash", "meta-llama/llama-3.3-70b-instruct:free", "随便型号zzz"]
    for m in cases:
        chain = channels.model_to_chain(m)
        print(f"  model={m:42s} → {chain}")
    print("\n模拟请求失败时顺序 fallback 到下一可用渠道：")
    tried = []
    for m in ["gpt-oss-120b", "qwen-plus", "glm-4-flash", "deepseek-ai/DeepSeek-V3"]:
        chain = channels.model_to_chain(m)
        for cid in chain:
            if not channels.key_is_set(cid):
                tried.append(f"{cid}(未配key)")
                continue
            tried.append(f"{cid}")
            print(f"  model={m:30s} 走 {cid}（有 key，已路由）")
            break
    print(f"  汇总必须按序跳过未配置渠道：{tried}")


def main():
    parser = argparse.ArgumentParser(description="task_006 渠道验证")
    parser.add_argument("--test", nargs="*", help="ping 指定渠道（默认全部 4 个新渠道）")
    parser.add_argument("--fallback", action="store_true", help="测试 fallback 链")
    args = parser.parse_args()

    print("=== 各渠道 Key 来源检查 ===")
    for c in channels.CHANNEL_ORDER:
        k = check_key(c)
        print(f"  {k['id']:12s} key_set={k['key_set']}  来源={k['source']}  {k['key_prefix']}")

    if args.fallback:
        test_fallback_chain()

    test_report = False
    if args.test is not None:
        targets = args.test if args.test else NEW_CHANNELS
        test_report = True
        print("\n=== 实际发送测试请求 ===")
        rc = 0
        for cid in targets:
            rc |= ping_one(cid)
        print(f"\n结果：{'全部成功' if rc == 0 else '存在失败'}")
    elif not (args.fallback):
        # 默认只做连通性状态报告（不发真实请求）
        print("\n=== 渠道健康状态（不发真实请求，只探测）===")
        health_report()
    print("\n提示：如 4 个新渠道显示未配置 key，请在各厂商官网注册后")
    print("      设置环境变量（GROQ_API_KEY / SILICONFLOW_API_KEY / DASHSCOPE_API_KEY / ZHIPU_API_KEY）")


if __name__ == "__main__":
    main()