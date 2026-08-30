# -*- coding: utf-8 -*-
"""
价格闸门单测（P1-2 判定 + P1-3 离线核对 + P1-4 运维态/写侧，设计稿 v0.5 §4.1–§4.6）
====================================================================
运行：python tests/test_search_gateway_pricing.py

全 hermetic：判定全部走临时文件，不触碰运行中的网关与任何上游。
覆盖（对应 §6 P4 基线例组）：
  A 分类边界：free 放行 / paid 拦 / authorized 放行 / 撤销回拦（M5）/
    unknown 拦 / 未登记三级回退 / PRICING_UNKNOWN_POLICY 开关
  B 新鲜度降级：30 天窗口 / 7 天短窗（account_bound 与 billing_model=quota）/
    临界值 / verified_at 缺失或非法按陈旧拦 / authorized 同受新鲜度约束
  C 缺文件 / 解析失败（M4 fail-closed，不保留 last-known-good）/ 修复恢复 /
    mtime 热载 / 并发读
  D 真实文件冒烟（只读）：P1-1 初版 model_pricing.json × 判定层联动
  E 离线核对脚本（P1-3）：成员翻转只告警不改组（P4 点名列例）/ M3 超期 /
    N4 到期预警 / 授权 NOTE / 真源不可读退出码
  F 运维态与写侧（P1-4）：off/observe/enforce 三态、缺省 enforce、observe 窗口必填
    且 ≤7 天、到期转拦不静默续观、启动校验退出码 3106、原子写热载无残留、坏文档拒写
  G 观测面（P2 缩窄版 peek_class）：类别与 verdict 一致但无放行语义、不读 PRICING_* env、
    坏文件/缺文件不抛异常、陈旧降级与 global_default 回退
"""
import datetime
import itertools
import json
import os
import shutil
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GW = os.path.join(ROOT, "services", "search_gateway")
sys.path.insert(0, GW)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pricing  # noqa: E402
import pricing_group_review as pgr  # noqa: E402
from common import Result  # noqa: E402

TMPDIR = tempfile.mkdtemp(prefix="pricing_test_")
_seq = itertools.count(1)

NOW = datetime.date(2026, 9, 30)  # 新鲜度用例的统一“今天”


def _write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)  # 测试侧也践行原子写（M4 写侧纪律）
    return path


def write_doc(doc, mtime=None, raw=None):
    """把定价文档写入唯一临时路径。"""
    p = os.path.join(TMPDIR, "p%03d.json" % next(_seq))
    text = raw if raw is not None else json.dumps(doc, ensure_ascii=False)
    _write(p, text)
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def write_unified(groups):
    p = os.path.join(TMPDIR, "u%03d.json" % next(_seq))
    return _write(p, json.dumps(groups, ensure_ascii=False))


def mkdoc(models, default="unknown", gdefault="unknown"):
    return {
        "version": 1,
        "channels": {"testchan": {"default_class": default, "models": models}},
        "global_default_class": gdefault,
    }


def free_entry(days_ago=1, **extra):
    v = (NOW - datetime.timedelta(days=days_ago)).isoformat()
    e = {"class": "free", "verified_at": v, "last_reviewed_ok": v}  # 登记即首次复核（M3）
    e.update(extra)
    return e


def paid_entry(days_ago=1, **extra):
    e = {"class": "paid", "verified_at": (NOW - datetime.timedelta(days=days_ago)).isoformat()}
    e.update(extra)
    return e


def with_env(pairs, fn):
    """临时设定环境变量跑一段逻辑，结束精确还原（值 None = 删除该变量）。

    定价 env 是进程级的，A–E 组与 F 组共用同一解释器进程，必须用完即还原，
    否则 PRICING_UNKNOWN_POLICY / PRICING_MODE 会泄漏到别的用例组造成假绿/假红。
    """
    saved = {}
    for k, v in pairs.items():
        saved[k] = os.environ.get(k)
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        return fn()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def tmp_residue(path):
    """返回与 path 同目录、同基名的写侧临时分片（原子写不得留下它们）。"""
    d, base = os.path.split(path)
    return [f for f in os.listdir(d) if f.startswith(base + ".tmp.")]


# 进入运维态用例前的基线：三个定价 env 全部清除，由用例按需设定。
PRICING_ENV_CLEAN = {"PRICING_MODE": None, "PRICING_OBSERVE_UNTIL": None,
                     "PRICING_UNKNOWN_POLICY": None}


def case(name, fn, res):
    try:
        fn()
        res.append(Result(name, Result.PASS))
    except AssertionError as e:
        res.append(Result(name, Result.FAIL, str(e)))
    except Exception as e:  # noqa: BLE001
        res.append(Result(name, Result.FAIL, "异常: %s" % e))


def test_classes():
    res = []

    def t_free_allow():
        p = write_doc(mkdoc({"m1": free_entry()}))
        v = pricing.verdict("testchan", "m1", now=NOW, path=p)
        assert v["allow"] is True and v["class"] == "free" and v["reason"] == "free", v

    def t_paid_deny():
        p = write_doc(mkdoc({"m1": paid_entry()}))
        v = pricing.verdict("testchan", "m1", now=NOW, path=p)
        assert v["allow"] is False and v["class"] == "paid" and v["reason"] == "paid", v

    def t_authorized_allow():
        p = write_doc(mkdoc({"m1": paid_entry(authorized={"by": "user", "at": "2026-09-01", "note": "t", "revoked_at": None})}))
        v = pricing.verdict("testchan", "m1", now=NOW, path=p)
        assert v["allow"] is True and v["reason"] == "authorized_paid" and v["authorized"] is True, v

    def t_authorized_revoked_deny():  # M5：撤销即时回拦
        p = write_doc(mkdoc({"m1": paid_entry(authorized={"by": "user", "at": "2026-09-01", "note": "t", "revoked_at": "2026-09-25"})}))
        v = pricing.verdict("testchan", "m1", now=NOW, path=p)
        assert v["allow"] is False and v["reason"] == "authorized_revoked", v

    def t_unknown_deny():
        p = write_doc(mkdoc({"m1": {"class": "unknown", "verified_at": NOW.isoformat()}}))
        v = pricing.verdict("testchan", "m1", now=NOW, path=p)
        assert v["allow"] is False and v["reason"] == "unknown", v

    def t_channel_default_paid():
        p = write_doc(mkdoc({}, default="paid"))
        v = pricing.verdict("testchan", "whatever", now=NOW, path=p)
        assert v["allow"] is False and v["class"] == "paid" and v["source"] == "channel_default", v

    def t_channel_default_unknown():
        p = write_doc(mkdoc({}, default="unknown"))
        v = pricing.verdict("testchan", "whatever", now=NOW, path=p)
        assert v["allow"] is False and v["reason"] == "unknown" and v["source"] == "channel_default", v

    def t_global_default():
        p = write_doc(mkdoc({}, default="nonsense"))  # 渠道默认非法 -> 落全局
        v = pricing.verdict("no_such_channel", "whatever", now=NOW, path=p)
        assert v["allow"] is False and v["reason"] == "unknown" and v["source"] == "global_default", v

    def t_bad_class_fallback():
        p = write_doc(mkdoc({"m1": {"class": "gratis", "verified_at": NOW.isoformat()}}, default="paid"))
        v = pricing.verdict("testchan", "m1", now=NOW, path=p)
        assert v["allow"] is False and v["class"] == "paid" and v["source"] == "channel_default", v

    def t_unknown_policy_allow():
        p = write_doc(mkdoc({"m1": {"class": "unknown"}}))
        os.environ["PRICING_UNKNOWN_POLICY"] = "allow"
        try:
            v = pricing.verdict("testchan", "m1", now=NOW, path=p)
            assert v["allow"] is True and v["reason"] == "unknown_policy_allow", v
        finally:
            os.environ.pop("PRICING_UNKNOWN_POLICY", None)

    case("A1 free 新鲜放行", t_free_allow, res)
    case("A2 paid 未授权拦截", t_paid_deny, res)
    case("A3 authorized 放行（revoked_at=null）", t_authorized_allow, res)
    case("A4 撤销后回拦（M5）", t_authorized_revoked_deny, res)
    case("A5 显式 unknown 拦截（Q2）", t_unknown_deny, res)
    case("A6 未登记落渠道默认 paid", t_channel_default_paid, res)
    case("A7 未登记落渠道默认 unknown", t_channel_default_unknown, res)
    case("A8 未登记渠道落全局默认", t_global_default, res)
    case("A9 非法 class 回退渠道默认", t_bad_class_fallback, res)
    case("A10 PRICING_UNKNOWN_POLICY=allow", t_unknown_policy_allow, res)
    return res


def test_staleness():
    res = []

    def t_free_stale31():
        p = write_doc(mkdoc({"m1": free_entry(days_ago=31)}))
        v = pricing.verdict("testchan", "m1", now=NOW, path=p)
        assert v["allow"] is False and v["class"] == "unknown" and v["reason"] == "stale", v

    def t_free_boundary30():
        p = write_doc(mkdoc({"m1": free_entry(days_ago=30)}))
        v = pricing.verdict("testchan", "m1", now=NOW, path=p)
        assert v["allow"] is True and v["reason"] == "free", v

    def t_quota_account_bound_8d():
        p = write_doc(mkdoc({"m1": free_entry(days_ago=8, account_bound=True, billing_model="quota")}))
        v = pricing.verdict("testchan", "m1", now=NOW, path=p)
        assert v["allow"] is False and v["reason"] == "stale", v

    def t_quota_billing_model_only_8d():
        p = write_doc(mkdoc({"m1": free_entry(days_ago=8, billing_model="quota")}))
        v = pricing.verdict("testchan", "m1", now=NOW, path=p)
        assert v["allow"] is False and v["reason"] == "stale", v

    def t_quota_boundary7():
        p = write_doc(mkdoc({"m1": free_entry(days_ago=7, account_bound=True)}))
        v = pricing.verdict("testchan", "m1", now=NOW, path=p)
        assert v["allow"] is True and v["reason"] == "free", v

    def t_non_quota_8d_still_fresh():  # 两计时器互不污染
        p = write_doc(mkdoc({"m1": free_entry(days_ago=8)}))
        v = pricing.verdict("testchan", "m1", now=NOW, path=p)
        assert v["allow"] is True and v["reason"] == "free", v

    def t_bad_verified_at():
        p = write_doc(mkdoc({"m1": {"class": "free", "verified_at": "not-a-date"}}))
        v = pricing.verdict("testchan", "m1", now=NOW, path=p)
        assert v["allow"] is False and v["reason"] == "stale", v

    def t_missing_verified_at():
        p = write_doc(mkdoc({"m1": {"class": "free"}}))
        v = pricing.verdict("testchan", "m1", now=NOW, path=p)
        assert v["allow"] is False and v["reason"] == "stale", v

    def t_authorized_stale_deny():  # 刻意取舍：新鲜度对 authorized 同样生效
        p = write_doc(mkdoc({"m1": paid_entry(days_ago=31, authorized={"by": "user", "at": "2026-08-01", "note": "t", "revoked_at": None})}))
        v = pricing.verdict("testchan", "m1", now=NOW, path=p)
        assert v["allow"] is False and v["reason"] == "stale", v

    case("B1 free 超 30 天降 unknown", t_free_stale31, res)
    case("B2 free 恰好 30 天仍新鲜", t_free_boundary30, res)
    case("B3 account_bound 8 天超短窗", t_quota_account_bound_8d, res)
    case("B4 billing_model=quota 同走短窗", t_quota_billing_model_only_8d, res)
    case("B5 配额型恰好 7 天仍新鲜", t_quota_boundary7, res)
    case("B6 非配额 8 天不受短窗污染", t_non_quota_8d_still_fresh, res)
    case("B7 非法 verified_at 按陈旧拦", t_bad_verified_at, res)
    case("B8 缺 verified_at 按陈旧拦", t_missing_verified_at, res)
    case("B9 authorized 过期同样降拦", t_authorized_stale_deny, res)
    return res


def test_load_failure():
    res = []

    def t_missing_file():
        p = os.path.join(TMPDIR, "never_exists.json")
        v = pricing.verdict("testchan", "m1", now=NOW, path=p)
        assert v["allow"] is False and v["reason"] == "pricing_missing", v

    def t_invalid_then_no_lkg():  # M4：坏文件不得沿用 last-known-good
        p = write_doc(mkdoc({"m1": free_entry()}), mtime=time.time() - 20)
        assert pricing.verdict("testchan", "m1", now=NOW, path=p)["allow"] is True
        with open(p, "w", encoding="utf-8") as f:
            f.write('{"channels": ')  # 半截 JSON
        os.utime(p, (time.time() - 10, time.time() - 10))
        v = pricing.verdict("testchan", "m1", now=NOW, path=p)
        st = pricing.load_pricing(p)
        assert v["allow"] is False and v["reason"] == "pricing_invalid", v
        assert st["kind"] == "invalid" and st["data"] is None, st

    def t_repair_recovers():
        p = write_doc(mkdoc({"m1": free_entry()}), mtime=time.time() - 30)
        with open(p, "w", encoding="utf-8") as f:
            f.write("{oops")
        os.utime(p, (time.time() - 20, time.time() - 20))
        assert pricing.verdict("testchan", "m1", now=NOW, path=p)["allow"] is False
        tmp = p + ".fix"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(mkdoc({"m1": free_entry()}), ensure_ascii=False))
        os.replace(tmp, p)
        os.utime(p, (time.time() - 5, time.time() - 5))
        v = pricing.verdict("testchan", "m1", now=NOW, path=p)
        assert v["allow"] is True and v["reason"] == "free", v

    def t_hot_reload_class_flip():
        t0 = time.time() - 40
        p = write_doc(mkdoc({"m1": free_entry()}), mtime=t0)
        assert pricing.verdict("testchan", "m1", now=NOW, path=p)["allow"] is True
        tmp = p + ".flip"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(mkdoc({"m1": paid_entry()}), ensure_ascii=False))
        os.replace(tmp, p)
        os.utime(p, (t0 + 5, t0 + 5))
        v = pricing.verdict("testchan", "m1", now=NOW, path=p)
        assert v["allow"] is False and v["class"] == "paid", v

    def t_not_dict_root():
        p = write_doc(None, raw="[1,2,3]")
        v = pricing.verdict("testchan", "m1", now=NOW, path=p)
        assert v["allow"] is False and v["reason"] == "pricing_invalid", v

    def t_concurrent_reads():
        p = write_doc(mkdoc({"m1": free_entry()}))
        errs = []

        def worker():
            try:
                for _ in range(40):
                    v = pricing.verdict("testchan", "m1", now=NOW, path=p)
                    assert v["allow"] is True and v["class"] == "free"
            except Exception as e:  # noqa: BLE001
                errs.append(e)

        ths = [threading.Thread(target=worker) for _ in range(8)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        assert not errs, errs[:3]

    case("C1 缺文件全拦（Q2）", t_missing_file, res)
    case("C2 解析失败不沿用旧数据（M4）", t_invalid_then_no_lkg, res)
    case("C3 修复后热载恢复", t_repair_recovers, res)
    case("C4 mtime 热载 free→paid 翻转", t_hot_reload_class_flip, res)
    case("C5 根节点非对象按损坏处理", t_not_dict_root, res)
    case("C6 并发读一致", t_concurrent_reads, res)
    return res


def test_real_file():
    """P1-1 初版真源 × 判定层联动（只读冒烟）。"""
    res = []

    def t_real_load_ok():
        st = pricing.load_pricing()
        assert st["kind"] == "ok", st
        assert (st["data"] or {}).get("global_default_class") == "unknown", st

    def t_real_zenmux():
        assert pricing.verdict("zenmux", "dots-studio/dots3-note-prev")["allow"] is True
        v = pricing.verdict("zenmux", "anthropic/claude-sonnet-5")
        assert v["allow"] is False and v["class"] == "paid", v
        v2 = pricing.verdict("zenmux", "some-brand-new-model")  # 渠道默认 paid 兜底
        assert v2["allow"] is False and v2["class"] == "paid", v2

    def t_real_opencode_authorized():
        v = pricing.verdict("opencode", "deepseek-v4-flash")
        assert v["allow"] is True and v["reason"] == "authorized_paid", v

    def t_real_quota_window():
        # modelscope 配额条目：今天新鲜；+8 天（超 7 天短窗）应降拦
        assert pricing.verdict("modelscope", "deepseek-ai/DeepSeek-V4-Pro-0813")["allow"] is True
        future = datetime.date.today() + datetime.timedelta(days=8)
        v = pricing.verdict("modelscope", "deepseek-ai/DeepSeek-V4-Pro-0813", now=future)
        assert v["allow"] is False and v["reason"] == "stale", v

    def t_real_unlisted_channel():
        v = pricing.verdict("gmi", "MiniMaxAI/MiniMax-M3")
        assert v["allow"] is False and v["reason"] == "unknown" and v["source"] == "global_default", v

    case("D1 真实文件可加载", t_real_load_ok, res)
    case("D2 zenmux 免费/收费/默认兜底", t_real_zenmux, res)
    case("D3 opencode 授权放行", t_real_opencode_authorized, res)
    case("D4 配额条目 7 天短窗生效", t_real_quota_window, res)
    case("D5 未登记渠道落全局 unknown", t_real_unlisted_channel, res)
    return res


def test_group_review():
    """P1-3 离线核对脚本：只告警留痕，绝不改组。"""
    res = []
    grp = {"g1": {"members": {"testchan": "m1"}}}

    def t_all_free_exit0():
        up = write_unified(grp)
        pp = write_doc(mkdoc({"m1": free_entry()}))
        code, lines = pgr.run(now=NOW, unified_path=up, pricing_path=pp)
        assert code == 0 and "BLOCKED=0" in lines[0], lines

    def t_free_to_paid_warn_only():  # P4 点名列例：free→paid 只告警，成员列表不动
        up = write_unified(grp)
        before = open(up, "rb").read()
        pp = write_doc(mkdoc({"m1": paid_entry()}))
        code, lines = pgr.run(now=NOW, unified_path=up, pricing_path=pp)
        text = "\n".join(lines)
        assert code == 1 and "[BLOCKED] g1 testchan/m1" in text, lines
        assert open(up, "rb").read() == before, "核对脚本改动了组文件！"

    def t_missing_member_blocked():
        up = write_unified(grp)
        pp = write_doc(mkdoc({}))  # m1 未登记，渠道默认 unknown
        code, lines = pgr.run(now=NOW, unified_path=up, pricing_path=pp)
        assert code == 1 and "[BLOCKED]" in "\n".join(lines), lines

    def t_review_overdue():  # M3：free 条目超 7 天未复核
        up = write_unified(grp)
        e = free_entry()
        e["last_reviewed_ok"] = (NOW - datetime.timedelta(days=8)).isoformat()
        pp = write_doc(mkdoc({"m1": e}))
        code, lines = pgr.run(now=NOW, unified_path=up, pricing_path=pp)
        assert code == 1 and "[REVIEW] testchan/m1" in "\n".join(lines), lines

    def t_expiring_prewarn():  # N4：30 天窗口剩 ≤7 天
        up = write_unified(grp)
        pp = write_doc(mkdoc({"m1": free_entry(days_ago=25)}))
        code, lines = pgr.run(now=NOW, unified_path=up, pricing_path=pp)
        assert code == 1 and "[EXPIRING] testchan/m1 5 天" in "\n".join(lines), lines

    def t_quota_no_duplicate_prewarn():  # 配额型不重复报 EXPIRING（其预警=逐周 REVIEW）
        up = write_unified(grp)
        e = free_entry(days_ago=8, account_bound=True, billing_model="quota")
        e["last_reviewed_ok"] = NOW.isoformat()
        pp = write_doc(mkdoc({"m1": e}))
        code, lines = pgr.run(now=NOW, unified_path=up, pricing_path=pp)
        text = "\n".join(lines)
        assert "[EXPIRING]" not in text, lines
        assert code == 1 and "[BLOCKED]" in text, lines  # 8 天超短窗 -> 成员会被运行时剔除

    def t_authorized_member_note_only():
        up = write_unified(grp)
        e = paid_entry(authorized={"by": "user", "at": "2026-09-01", "note": "t", "revoked_at": None})
        pp = write_doc(mkdoc({"m1": e}))
        code, lines = pgr.run(now=NOW, unified_path=up, pricing_path=pp)
        text = "\n".join(lines)
        assert code == 0 and "[NOTE]" in text and "BLOCKED=0" in lines[0], lines

    def t_source_unreadable_exit2():
        up = write_unified(grp)
        code, lines = pgr.run(now=NOW, unified_path=up,
                              pricing_path=os.path.join(TMPDIR, "nope.json"))
        assert code == 2 and "FATAL" in lines[0], lines

    case("E1 全员新鲜 -> 退出 0", t_all_free_exit0, res)
    case("E2 free→paid 只告警不改组（P4 例）", t_free_to_paid_warn_only, res)
    case("E3 成员未登记计入 BLOCKED", t_missing_member_blocked, res)
    case("E4 M3 超 7 天未复核计入 REVIEW", t_review_overdue, res)
    case("E5 N4 到期前 7 天预警", t_expiring_prewarn, res)
    case("E6 配额型不重复报 EXPIRING", t_quota_no_duplicate_prewarn, res)
    case("E7 授权成员仅 NOTE 不算异常", t_authorized_member_note_only, res)
    case("E8 真源不可读退出码 2", t_source_unreadable_exit2, res)
    return res


def test_mode_and_write():
    """P1-4 运维态（N1/M2/Q5）+ 写侧原子替换（M4）。"""
    res = []
    paid_doc = lambda: mkdoc({"m1": paid_entry()})  # noqa: E731  每例独立临时文件

    def env(mode=None, until=None):
        e = dict(PRICING_ENV_CLEAN)
        if mode is not None:
            e["PRICING_MODE"] = mode
        if until is not None:
            e["PRICING_OBSERVE_UNTIL"] = until
        return e

    def t_default_enforce():  # N1：忘配 env 只会拦多，不会悄悄放
        p = write_doc(paid_doc())
        v = with_env(env(), lambda: pricing.effective_verdict("testchan", "m1", now=NOW, path=p))
        assert v["allow"] is False and v["reason"] == "paid", v

    def t_off_allows_all():  # 含真源缺失也放行——off 就是明确关闸
        missing = os.path.join(TMPDIR, "off_missing.json")
        fn = lambda: pricing.effective_verdict("testchan", "m1", now=NOW, path=missing)  # noqa: E731
        v = with_env(env(mode="off"), fn)
        assert v["allow"] is True and v["reason"] == "pricing_off", v

    def t_observe_allows_with_tag():
        p = write_doc(paid_doc())
        until = (NOW + datetime.timedelta(days=3)).isoformat()
        fn = lambda: pricing.effective_verdict("testchan", "m1", now=NOW, path=p)  # noqa: E731
        v = with_env(env(mode="observe", until=until), fn)
        assert v["allow"] is True and v["reason"] == "observe_would_deny:paid", v
        assert v["class"] == "paid" and "若 enforce 将被拦" in v["detail"], v

    def t_observe_today_still_valid():  # 剩余 0 天当天仍有效
        p = write_doc(paid_doc())
        fn = lambda: pricing.effective_verdict("testchan", "m1", now=NOW, path=p)  # noqa: E731
        v = with_env(env(mode="observe", until=NOW.isoformat()), fn)
        assert v["allow"] is True and v["reason"].startswith("observe_would_deny"), v

    def t_observe_expired_denies():  # M2：到期不静默续观
        p = write_doc(paid_doc())
        until = (NOW - datetime.timedelta(days=1)).isoformat()
        ev = lambda: pricing.effective_verdict("testchan", "m1", now=NOW, path=p)  # noqa: E731
        st = lambda: pricing.validate_startup_config(now=NOW, pricing_path=p)  # noqa: E731
        v = with_env(env(mode="observe", until=until), ev)
        assert v["allow"] is False and v["reason"] == "pricing_config_invalid", v
        ok, code, msg = with_env(env(mode="observe", until=until), st)
        assert ok is False and code == 3106 and "到期" in msg, (ok, code, msg)

    def t_observe_missing_until():
        p = write_doc(paid_doc())
        st = lambda: pricing.validate_startup_config(now=NOW, pricing_path=p)  # noqa: E731
        ok, code, msg = with_env(env(mode="observe"), st)
        assert ok is False and code == pricing.EXIT_PRICING_CONFIG and "PRICING_OBSERVE_UNTIL" in msg, (ok, code, msg)

    def t_observe_window_too_long():
        p = write_doc(paid_doc())
        until = (NOW + datetime.timedelta(days=pricing.OBSERVE_MAX_DAYS + 1)).isoformat()
        st = lambda: pricing.validate_startup_config(now=NOW, pricing_path=p)  # noqa: E731
        ok, code, msg = with_env(env(mode="observe", until=until), st)
        assert ok is False and code == 3106 and "上限" in msg, (ok, code, msg)

    def t_bad_mode_value():
        p = write_doc(mkdoc({"m1": free_entry()}))
        ev = lambda: pricing.effective_verdict("testchan", "m1", now=NOW, path=p)  # noqa: E731
        st = lambda: pricing.validate_startup_config(now=NOW, pricing_path=p)  # noqa: E731
        v = with_env(env(mode="lenient"), ev)
        assert v["allow"] is False and v["reason"] == "pricing_config_invalid", v
        ok, code, msg = with_env(env(mode="lenient"), st)
        assert ok is False and code == 3106 and "PRICING_MODE" in msg, (ok, code, msg)

    def t_startup_corrupt_source():
        p = write_doc(None, raw='{"channels": ')
        ok, code, msg = with_env(env(), lambda: pricing.validate_startup_config(now=NOW, pricing_path=p))
        assert ok is False and code == 3106 and "pricing-invalid" in msg, (ok, code, msg)

    def t_startup_missing_source_warns():  # 缺文件不拒启动，运行期逐条拦
        missing = os.path.join(TMPDIR, "startup_missing.json")
        ok, code, msg = with_env(env(), lambda: pricing.validate_startup_config(now=NOW, pricing_path=missing))
        assert ok is True and code is None and "警告" in msg, (ok, code, msg)

    def t_atomic_write_hot_reload():
        p = write_doc(paid_doc())
        doc = mkdoc({"m1": free_entry()})
        assert pricing.write_pricing_atomic(doc, p) == p
        assert json.loads(open(p, encoding="utf-8").read())["channels"]["testchan"]["models"]["m1"]["class"] == "free"
        v = pricing.verdict("testchan", "m1", now=NOW, path=p)  # 缓存已失效，热载即见新值
        assert v["allow"] is True and v["reason"] == "free", v
        assert tmp_residue(p) == [], tmp_residue(p)

    def t_atomic_write_rejects_bad_doc():  # M4 写侧：坏数据永远落不到真源上
        p = write_doc(paid_doc())
        before = open(p, "rb").read()
        bad = mkdoc({"m1": free_entry()})
        bad["channels"]["testchan"]["models"] = "not-an-object"
        try:
            pricing.write_pricing_atomic(bad, p)
            raise AssertionError("非法文档竟然写成功了")
        except ValueError:
            pass
        assert open(p, "rb").read() == before, "拒写却改动了目标文件"
        assert tmp_residue(p) == [], tmp_residue(p)

    def t_version_mismatch():
        p = write_doc(paid_doc())
        bad = mkdoc({"m1": free_entry()})
        bad["version"] = 2
        try:
            pricing.write_pricing_atomic(bad, p)
            raise AssertionError("version=2 竟然通过写侧校验")
        except ValueError:
            pass
        q = write_doc(None, raw=json.dumps(bad, ensure_ascii=False))
        assert pricing.load_pricing(q)["kind"] == "invalid"
        v = pricing.verdict("testchan", "m1", now=NOW, path=q)
        assert v["allow"] is False and v["reason"] == "pricing_invalid", v

    case("F1 缺省模式=enforce（N1）", t_default_enforce, res)
    case("F2 off 一律放行（含缺文件）", t_off_allows_all, res)
    case("F3 observe 窗内放行并留痕", t_observe_allows_with_tag, res)
    case("F4 observe UNTIL 当天仍有效", t_observe_today_still_valid, res)
    case("F5 observe 到期转拦 + 启动 3106（M2）", t_observe_expired_denies, res)
    case("F6 observe 缺 UNTIL 拒启动", t_observe_missing_until, res)
    case("F7 observe 窗口 >7 天拒启动", t_observe_window_too_long, res)
    case("F8 mode 非法值拒启动且运行期拦", t_bad_mode_value, res)
    case("F9 真源损坏拒启动（3106，Q5）", t_startup_corrupt_source, res)
    case("F10 真源缺失仅警告不拒启动", t_startup_missing_source_warns, res)
    case("F11 原子写成功且热载无残留（M4）", t_atomic_write_hot_reload, res)
    case("F12 非法文档拒写、目标字节不变", t_atomic_write_rejects_bad_doc, res)
    case("F13 version 不等读写两侧均拒", t_version_mismatch, res)
    return res


def test_peek_class():
    """G 观测面（P2 缩窄版）：peek_class 只报类别 —— 不具放行权、不读 env、绝不抛异常。"""
    res = []

    def t_peek_matches_verdict_but_no_allow():
        p = write_doc(mkdoc({"m1": free_entry(), "m2": paid_entry()}))
        for m in ("m1", "m2"):
            pk = pricing.peek_class("testchan", m, NOW, p)
            vd = pricing.verdict("testchan", m, NOW, p)
            assert pk["class"] == vd["class"], (pk, vd)
            assert "allow" not in pk, pk  # 观测结果不可被当作放行依据

    def t_peek_ignores_env():
        p = write_doc(mkdoc({"m3": {"class": "unknown", "verified_at": NOW.isoformat()}}))

        def go():
            return pricing.peek_class("testchan", "m3", NOW, p)

        a = with_env(dict(PRICING_ENV_CLEAN, PRICING_UNKNOWN_POLICY="allow",
                          PRICING_MODE="enforce"), go)
        b = with_env(dict(PRICING_ENV_CLEAN), go)
        assert a == b and a["class"] == "unknown", (a, b)
        # 反证：同一 env 会改变 verdict 的放行结果 —— 所以观测面绝不复用 verdict
        v_allow = with_env({"PRICING_UNKNOWN_POLICY": "allow"},
                           lambda: pricing.verdict("testchan", "m3", NOW, p)["allow"])
        v_deny = with_env(dict(PRICING_ENV_CLEAN),
                          lambda: pricing.verdict("testchan", "m3", NOW, p)["allow"])
        assert (v_allow, v_deny) == (True, False), (v_allow, v_deny)

    def t_peek_corrupt_and_missing_never_raise():
        bad = write_doc(None, raw='{"broken": ')
        assert pricing.peek_class("testchan", "m1", NOW, bad) == \
            {"class": "unknown", "source": "invalid", "stale": False}
        gone = os.path.join(TMPDIR, "never_written.json")
        r = pricing.peek_class("testchan", "m1", NOW, gone)
        assert r["class"] == "unknown" and r["source"] == "missing", r

    def t_peek_stale_downgrade_and_global_default():
        p = write_doc(mkdoc({"old": free_entry(days_ago=40)}, gdefault="paid"))
        pk = pricing.peek_class("testchan", "old", NOW, p)
        assert pk["class"] == "unknown" and pk["stale"] is True, pk
        other = pricing.peek_class("chan-not-in-doc", "any", NOW, p)
        assert other == {"class": "paid", "source": "global_default", "stale": False}, other

    case("G1 观测类别与 verdict 一致、但不含放行语义", t_peek_matches_verdict_but_no_allow, res)
    case("G2 观测不受任何 PRICING_* env 影响（verdict 会）", t_peek_ignores_env, res)
    case("G3 真源损坏/缺失：观测降级且绝不抛异常", t_peek_corrupt_and_missing_never_raise, res)
    case("G4 陈旧降级与未登记 global_default 回退", t_peek_stale_downgrade_and_global_default, res)
    return res


def run_all():
    print()
    print("===== :3100 网关价格闸门（P1-2 判定 + P1-4 运维态/写侧）=====")
    out = []
    for group in (test_classes, test_staleness, test_load_failure, test_real_file,
                  test_group_review, test_mode_and_write, test_peek_class):
        out.extend(group())
    for r in out:
        print(" ", r)
    return out


if __name__ == "__main__":
    try:
        results = run_all()
    finally:
        shutil.rmtree(TMPDIR, ignore_errors=True)
    passed = sum(1 for r in results if r.status == Result.PASS)
    failed = sum(1 for r in results if r.status == Result.FAIL)
    print()
    print("价格闸门 P1（判定+核对+运维态）: %d/%d 通过" % (passed, len(results)))
    sys.exit(1 if failed else 0)
