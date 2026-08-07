# -*- coding: utf-8 -*-
"""
对话历史模块测试 (03_共享组件/history.py)
覆盖：save_turn / get_conversation / list_conversations / delete / export_daily_stats / 并发。
"""

import json
import os
import sys
import threading
import urllib.parse
import urllib.request

import common
from common import Result

BASE = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(BASE, "..", "03_共享组件"))
sys.path.insert(0, SHARED)
sys.path.insert(0, BASE)

import history  # noqa: E402

GW = "ds_v4_cli"
CID = "e2e_hist_test" + str(os.getpid())


def _clean():
    history.delete_conversation(GW, CID)


def test_save_and_get():
    _clean()
    history.save_turn(GW, "kimi", CID, "user", "你好")
    history.save_turn(GW, "kimi", CID, "assistant", "你好呀")
    history.save_turn(GW, "kimi", CID, "user", "你会什么")
    history.save_turn(GW, "kimi", CID, "assistant", "深度检索")
    conv = history.get_conversation(GW, CID)
    if len(conv) == 4 and [t["id"] for t in conv] == [1, 2, 3, 4] \
            and conv[0]["role"] == "user" and conv[1]["role"] == "assistant":
        return common.Result("history 写入/读取", common.Result.PASS, "4 turns id 1-4")
    return common.Result("history 写入/读取", common.Result.FAIL, str(conv))


def test_list():
    lst = history.list_conversations(gateway_id=GW, limit=10)
    m = [c for c in lst if c["conversation_id"] == CID]
    # 摘要：只含摘要 last_content，不含完整 content 正文键
    keys = set(m[0].keys()) if m else set()
    if m and m[0]["turns"] == 4 and m[0]["engine"] == "kimi" \
            and "content" not in keys:
        return common.Result("history-列表摘要", common.Result.PASS, f"{m[0]['turns']} turns")
    return common.Result("history-列表摘要", common.Result.FAIL, str(m))


def test_export():
    ds = history.export_daily_stats()
    if any(r["gateway"] == GW for r in ds) and {"date", "gateway", "total_calls",
                                                 "active_users", "error_count"} <= set(ds[0]):
        return common.Result("history-日统计导出", common.Result.PASS, "字段对齐 daily_stats")
    return common.Result("history-日统计导出", common.Result.FAIL, str(ds))


def test_concurrent():
    _clean()
    errs = []

    def wr(n):
        try:
            for i in range(50):
                history.save_turn(GW, "kimi", f"{CID}_t{n}", "user", f"x{n}-{i}")
        except Exception as e:  # noqa: BLE001
            errs.append(str(e))

    import threading
    ts = [threading.Thread(target=wr, args=(i,)) for i in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    ok = not errs
    for n in range(2):
        if len(history.get_conversation(GW, f"{CID}_t{n}")) != 50:
            ok = False
    for n in range(2):
        history.delete_conversation(GW, f"{CID}_t{n}")
    if ok:
        return common.Result("history-并发100轮", common.Result.PASS, "2线程×50无损坏")
    return common.Result("history-并发100轮", common.Result.FAIL, str(errs))


def test_endpoint():
    """网关 GET /api/history?engine=&limit= 应返回持久化对话列表。"""
    import history as h
    gw, cid = GW, "e2e_gw_hist"
    h.delete_conversation(gw, cid)
    h.save_turn(gw, "kimi", cid, "user", "端点测试")
    h.save_turn(gw, "kimi", cid, "assistant", "OK")
    try:
        url = "http://localhost:3000/api/history?" + urllib.parse.urlencode(
            {"engine": "kimi", "limit": "5"})
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
        convs = data.get("conversations")
        if data.get("status") == "ok" and isinstance(convs, list) \
                and any(c["conversation_id"] == cid for c in convs):
            return common.Result("history-网关端点", common.Result.PASS,
                                 f"GET /api/history 返回 {len(convs)} 对话")
        return common.Result("history-网关端点", common.Result.FAIL,
                             f"status={data.get('status')} convs={convs}")
    except Exception as e:  # noqa: BLE001
        return common.Result("history-网关端点", common.Result.FAIL, f"{type(e).__name__}: {e}")
    finally:
        h.delete_conversation(gw, cid)


def run_all():
    results = [test_save_and_get(), test_list(), test_export(), test_concurrent(),
               test_endpoint()]
    history.delete_conversation(GW, CID)
    return results


if __name__ == "__main__":
    for r in run_all():
        print(r)
    common.summarize(run_all(), "history")