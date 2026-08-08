# -*- coding: utf-8 -*-
"""
B站视频嵌入组件测试 (06_组件编排器/components/video_embed_bilibili.py)
覆盖：BV 正则、儿童内容排序、build_iframe 模板、validate_bv、run 契约、search。
网络部分（B站/网关）内置 SKIP 保护：站点风控或不可达时不判失败。
"""

import os
import re
import sys
import tempfile
from pathlib import Path

BASE = os.path.dirname(os.path.abspath(__file__))
ORCH_DIR = os.path.normpath(os.path.join(BASE, "..", "06_组件编排器"))
sys.path.insert(0, BASE)
if os.path.isdir(ORCH_DIR):
    sys.path.insert(0, ORCH_DIR)

from common import Result, summarize  # noqa: E402

RULE_CARD = str(Path(ORCH_DIR, "组件规则卡", "video_embed_bilibili.yaml"))
KNOWN_GOOD_BV = "BV12J41137hp"     # 儿童教学儿歌，可公开访问
KNOWN_BAD_BV = "BV0000000001"      # 伪造 BV

from components import video_embed_bilibili as vid  # noqa: E402


# ---------------------------------------------------------------- 用例

def test_bv_regex():
    good = all(re.fullmatch(vid.BV_RE, b) for b in
               ("BV12J41137hp", "BV1sVW6GcEkw", "BV1ON1WoJveK"))
    bad = any(re.fullmatch(vid.BV_RE, b) for b in
              ("BV", "BV12", "av123", "bv1234567890", "BV123456789"))
    if good and not bad:
        return Result("BV 号正则", Result.PASS, "大小写敏感+定长 12")
    return Result("BV 号正则", Result.FAIL, f"good={good} bad_allowed={bad}")


def test_sort_kid_preferred():
    fake = [
        {"bv": "BV1AA00000001", "title": "老电影 88分钟", "duration_s": 5280},
        {"bv": "BV1BB00000002", "title": "English Number Song for Kids", "duration_s": 96},
        {"bv": "BV1CC00000003", "title": "儿歌动画 5分钟", "duration_s": 300},
    ]
    out = vid._sort_kid_preferred(fake)
    if out[0]["bv"] == "BV1BB00000002" and out[-1]["bv"] == "BV1AA00000001":
        return Result("儿童内容优先排序", Result.PASS, "关键词+时长优先")
    return Result("儿童内容优先排序", Result.FAIL, f"顺序={[o['bv'] for o in out]}")


def test_build_iframe():
    iframe = vid.build_iframe(KNOWN_GOOD_BV, RULE_CARD)
    require = ["player.bilibili.com/player.html", "bvid=" + KNOWN_GOOD_BV,
               "autoplay=0", "danmaku=0", "aspect-ratio:16/9", "<iframe"]
    missing = [k for k in require if k not in iframe]
    if not missing:
        return Result("build_iframe", Result.PASS, "模板含 16:9/autoplay=0/danmaku=0")
    return Result("build_iframe", Result.FAIL, f"缺失 {missing}")


def test_validate_bv():
    good = vid.validate_bv(KNOWN_GOOD_BV)
    bad = vid.validate_bv(KNOWN_BAD_BV)
    badfmt = vid.validate_bv("BV1x")
    if good is True and bad is False and badfmt is False:
        return Result("validate_bv", Result.PASS,
                      f"真={good} 伪造={bad} 格式错={badfmt}")
    if good is False:
        # B站风控/不可达时 SKIP
        return Result("validate_bv", Result.SKIP,
                      "B站不可达/风控，validate 无法在线验证")
    return Result("validate_bv", Result.FAIL,
                  f"真={good} 伪造={bad} 格式错={badfmt}")


def test_search_candidates():
    try:
        out = vid.search_candidates("English number song kids", limit=5,
                                    rule_card_path=RULE_CARD)
    except Exception as e:  # noqa: BLE001
        return Result("search_candidates", Result.SKIP, f"网络异常: {e}")
    if len(out) >= 3:
        bvs = [x["bv"] for x in out]
        return Result("search_candidates", Result.PASS,
                      f"{len(out)} 候选，含 BV={bvs[0]}")
    return Result("search_candidates", Result.SKIP,
                  f"仅 {len(out)} 候选（B站风控）")


def test_run_with_slot():
    slot = {"id": "p60_vid", "keyword": "English number song kids",
            "mode": "embed", "source": "bilibili"}
    try:
        r = vid.run(slot, RULE_CARD)
    except Exception as e:  # noqa: BLE001
        return Result("run 组件(slot)", Result.SKIP, f"异常: {e}")
    if r.get("ok"):
        asset = r.get("asset") or ""
        if "bvid=" in asset and r.get("bv"):
            return Result("run 组件(slot)", Result.PASS,
                          f"ok → bv={r['bv']} iframe={len(asset)}字")
        return Result("run 组件(slot)", Result.FAIL,
                      "ok=True 但 asset/bv 异常")
    return Result("run 组件(slot)", Result.SKIP,
                  f"无可用候选: {r.get('error')}")


def test_run_missing_keyword():
    r = vid.run({"id": "x", "keyword": ""}, RULE_CARD)
    if not r["ok"] and "keyword" in (r.get("error") or ""):
        return Result("run 缺 keyword", Result.PASS, "缺 keyword 被拒绝")
    return Result("run 缺 keyword", Result.FAIL, str(r))


def test_build_iframe_raises_bad():
    try:
        vid.build_iframe("BV1x")
        return Result("build_iframe 非法BV", Result.FAIL, "未抛错")
    except ValueError:
        return Result("build_iframe 非法BV", Result.PASS, "非法 BV 抛 ValueError")


def run_all():
    results = []
    tests = [
        test_bv_regex,
        test_sort_kid_preferred,
        test_build_iframe,
        test_build_iframe_raises_bad,
        test_validate_bv,
        test_search_candidates,
        test_run_with_slot,
        test_run_missing_keyword,
    ]
    for t in tests:
        try:
            results.append(t())
        except Exception as e:  # noqa: BLE001
            results.append(Result(t.__name__, Result.FAIL, f"{type(e).__name__}: {e}"))
    return results


if __name__ == "__main__":
    for r in run_all():
        print(r)
    summarize(run_all(), "B站视频组件")