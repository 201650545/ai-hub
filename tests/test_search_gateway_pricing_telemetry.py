# -*- coding: utf-8 -*-
"""
价格观测接线（P2 缩窄版）守护测试
================================
运行：python tests/test_search_gateway_pricing_telemetry.py

只验证一条安全主张：**观测代码只能损失 telemetry，绝不能影响转发链**。
全部走临时路径，不触碰运行中的 :3100、不写生产 JSONL、不调任何上游。
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GW = os.path.join(ROOT, "services", "search_gateway")
sys.path.insert(0, GW)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import api_gateway as ag  # noqa: E402
from common import Result  # noqa: E402

TMPDIR = tempfile.mkdtemp(prefix="pricing_tele_")

# 真实 deepseek-free 候选链（unified_models.json），用于确认贴标不失真
DEEPSEEK_CHAIN = [
    ("modelscope", "deepseek-ai/DeepSeek-V4-Pro-0813"),
    ("bai", "deepseek-v4-flash-vision-exp"),
    ("sensetime", "deepseek-v4-flash"),
    ("nvidia", "deepseek-ai/deepseek-v4-flash-0731"),
    ("dashscope", "deepseek-v4-flash"),
    ("opencode", "deepseek-v4-flash"),
    ("siliconflow", "deepseek-ai/DeepSeek-V3"),
]


def case(name, fn, res):
    saved = (ag._PRICING_TELEMETRY, dict(ag._TELEMETRY_ERRORS), list(ag._ROUTE_LOG))
    try:
        fn()
        res.append(Result(name, Result.PASS))
    except AssertionError as e:
        res.append(Result(name, Result.FAIL, str(e)))
    except Exception as e:  # noqa: BLE001
        res.append(Result(name, Result.FAIL, "异常: %s" % e))
    finally:
        ag._PRICING_TELEMETRY = saved[0]
        ag._TELEMETRY_ERRORS.clear()
        ag._TELEMETRY_ERRORS.update(saved[1])
        ag._ROUTE_LOG[:] = saved[2]


def t_chain_labeling():
    out = ag._peek_chain(DEEPSEEK_CHAIN)
    assert len(out) == len(DEEPSEEK_CHAIN), out  # 不增删候选
    assert [x["channel"] for x in out] == [c for c, _ in DEEPSEEK_CHAIN], out  # 不改顺序
    got = {x["channel"]: x["class"] for x in out}
    assert got["modelscope"] == "free" and got["nvidia"] == "free", got
    assert got["sensetime"] == "unknown" and got["dashscope"] == "unknown", got
    assert got["opencode"] == "paid", got
    assert got["siliconflow"] == "unknown", got  # 未登记 -> global_default


def t_garbage_input_never_raises():
    assert ag._peek_chain([("a", None), (1, 2)]) == [
        {"channel": "a", "model": None, "class": "unknown", "source": "global_default"},
        {"channel": 1, "model": 2, "class": "unknown", "source": "global_default"}]
    assert ag._peek_chain("not-a-list") == [], "非法输入必须降级为空，不得抛"
    assert ag._peek_chain(None) == []


def t_jsonl_record_shape():
    path = os.path.join(TMPDIR, "ok.jsonl")
    ag._PRICING_TELEMETRY = path
    ag._log_route({"ts": "19:20:00", "client_model": "deepseek-v4-flash",
                   "attempted": ["modelscope", "bai"],
                   "attempted_class": ag._peek_chain(DEEPSEEK_CHAIN[:2]),
                   "resolved_channel": "modelscope",
                   "resolved_model": "deepseek-ai/DeepSeek-V4-Pro-0813",
                   "resolved_class": "free", "fallback_count": 0,
                   "errors": ["boom" * 50], "failures": [{"channel": "bai"}, {"channel": "x"}]})
    lines = open(path, encoding="utf-8").read().strip().splitlines()
    assert len(lines) == 1, lines
    rec = __import__("json").loads(lines[0])
    assert rec["resolved_class"] == "free" and rec["attempted_class"][1]["class"] == "free", rec
    assert rec["failure_count"] == 2 and rec["epoch"] > 0, rec
    assert "errors" not in rec and "boom" not in lines[0], "错误正文不得进 telemetry（只留计数）"
    assert len(ag._ROUTE_LOG) == 1, "内存环形仍需保留完整 entry"


def t_writer_failure_isolated_and_self_disabling():
    ag._PRICING_TELEMETRY = TMPDIR  # 对目录本身 append -> 必然失败
    for _ in range(ag._TELEMETRY_MAX_ERRORS - 1):
        ag._write_telemetry({"ts": "x"})
    assert ag._TELEMETRY_ERRORS["disabled"] is False, ag._TELEMETRY_ERRORS
    ag._write_telemetry({"ts": "x"})
    assert ag._TELEMETRY_ERRORS["disabled"] is True, ag._TELEMETRY_ERRORS
    before = ag._TELEMETRY_ERRORS["count"]
    for _ in range(30):
        ag._write_telemetry({"ts": "x"})
    assert ag._TELEMETRY_ERRORS["count"] == before, "自禁用后不得再撞磁盘 I/O"


def t_route_log_survives_writer_death():
    ag._PRICING_TELEMETRY = TMPDIR
    ag._TELEMETRY_ERRORS.update({"count": 0, "disabled": True})
    ag._log_route({"ts": "19:30:00", "client_model": "m", "attempted": [],
                   "attempted_class": [], "resolved_channel": None, "fallback_count": 0})
    assert len(ag._ROUTE_LOG) == 1, "telemetry 挂了也不能吞掉路由日志本身"


def run_all():
    print()
    print("===== :3100 价格观测接线（P2 缩窄版）安全主张 =====")
    out = []
    for name, fn in (("H1 候选链贴标：不增删、不改序、类别取自真实定价", t_chain_labeling),
                     ("H2 垃圾输入绝不抛异常（降级为空/unknown）", t_garbage_input_never_raises),
                     ("H3 JSONL 字段裁剪正确、错误正文不外泄", t_jsonl_record_shape),
                     ("H4 writer 故障隔离 + 达阈值自禁用（不再撞 I/O）", t_writer_failure_isolated_and_self_disabling),
                     ("H5 telemetry 失效不影响内存路由日志", t_route_log_survives_writer_death)):
        case(name, fn, out)
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
    print("价格观测接线（P2 缩窄版）: %d/%d 通过" % (passed, len(results)))
    sys.exit(1 if failed else 0)
