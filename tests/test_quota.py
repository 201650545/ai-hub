# -*- coding: utf-8 -*-
"""
额度统计模块测试 (03_共享组件/quota.py + channels 集成)
覆盖：record_call 累计 / errors / get_usage / get_daily_summary / 并发 / 网关端点 / 真实渠道调用。
"""

import datetime
import json
import os
import sys
import threading
import urllib.request

import common

BASE = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(BASE, "..", "services", "search_gateway"))
sys.path.insert(0, SHARED)
sys.path.insert(0, BASE)

import quota  # noqa: E402

GW = "ds_v4_cli"


def _cleanup(channels):
    d = datetime.date.today().isoformat()
    path = os.path.join(BASE, "..", "data", "search_gateway", GW, "quota.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for c in channels:
            if d in data:
                data[d].pop(c, None)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass


def test_record_and_get():
    _cleanup(["testchan"])
    quota.record_call(GW, "testchan", "m", input_tokens=100, output_tokens=200, success=True)
    quota.record_call(GW, "testchan", "m", input_tokens=50, output_tokens=60, success=True)
    quota.record_call(GW, "testchan", "m", input_tokens=5, output_tokens=5, success=False)
    d = quota.get_usage(gateway_id=GW, channel="testchan")["testchan"]
    if d["calls"] == 3 and d["input_tokens"] == 155 and d["output_tokens"] == 265 \
            and d["errors"] == 1:
        return common.Result("quota 记录/查询", common.Result.PASS, "calls=3 errors=1")
    return common.Result("quota 记录/查询", common.Result.FAIL, str(d))


def test_daily_summary():
    ds = quota.get_daily_summary()
    fields = {"date", "gateway", "total_calls", "active_users", "error_count"}
    if ds and all(fields <= set(r) for r in ds):
        return common.Result("quota 日汇总", common.Result.PASS, "字段对齐 daily_stats")
    return common.Result("quota 日汇总", common.Result.FAIL, str(ds[:2]))


def test_concurrent():
    _cleanup(["concurrent"])
    errs = []

    def wr():
        try:
            for _ in range(20):
                quota.record_call(GW, "concurrent", "m", input_tokens=1, output_tokens=1, success=True)
        except Exception as e:  # noqa: BLE001
            errs.append(str(e))

    ts = [threading.Thread(target=wr) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    calls = quota.get_usage(gateway_id=GW, channel="concurrent")["concurrent"]["calls"]
    if not errs and calls == 40:
        return common.Result("quota 并发20", common.Result.PASS, f"{calls} 次无丢失")
    return common.Result("quota 并发20", common.Result.FAIL, f"calls={calls} errs={errs}")


def test_endpoint():
    """网关 GET /api/quota?date= 返回当日用量。"""
    try:
        with urllib.request.urlopen("http://localhost:3000/api/quota", timeout=8) as r:
            d = json.loads(r.read().decode("utf-8", "ignore"))
        if d.get("status") == "ok" and isinstance(d.get("usage"), dict):
            return common.Result("quota-网关端点", common.Result.PASS,
                                 f"GET /api/quota 含 {len(d['usage'])} 渠道")
        return common.Result("quota-网关端点", common.Result.FAIL, str(d)[:120])
    except Exception as e:  # noqa: BLE001
        return common.Result("quota-网关端点", common.Result.FAIL, f"{type(e).__name__}: {e}")


def test_channel_integration():
    """真实渠道调用后 quota.json 累计 calls + usage。无可用 key 时 SKIP。"""
    gate = os.path.normpath(os.path.join(BASE, "..", "services", "search_gateway"))
    try:
        sys.path.insert(0, gate)
        import channels
        if not channels.key_is_set("deepseek"):
            return common.Result("quota-渠道联动", common.Result.SKIP, "deepseek 未配置 key")
        before = quota.get_usage("ds_v4_cli", channel="deepseek").get(
            "deepseek", {"calls": 0, "errors": 0})
        resp = channels.chat_completion("deepseek", {
            "model": channels.CHANNELS["deepseek"]["default_model"],
            "messages": [{"role": "user", "content": "ping回复OK"}],
            "stream": False})
        resp.read()
        after = quota.get_usage("ds_v4_cli", channel="deepseek")["deepseek"]
        if after["calls"] == before["calls"] + 1 and after["errors"] == before["errors"] \
                and after["input_tokens"] > 0:
            return common.Result("quota-渠道联动", common.Result.PASS,
                                 f"calls {before['calls']}→{after['calls']}, in_tok={after['input_tokens']}")
        return common.Result("quota-渠道联动", common.Result.FAIL, f"before={before} after={after}")
    except Exception as e:  # noqa: BLE001
        return common.Result("quota-渠道联动", common.Result.FAIL, f"{type(e).__name__}: {e}")


def run_all():
    results = [test_record_and_get(), test_daily_summary(), test_concurrent(),
               test_endpoint(), test_channel_integration()]
    _cleanup(["testchan", "concurrent"])
    return results


if __name__ == "__main__":
    for r in run_all():
        print(r)
    common.summarize(run_all(), "quota")