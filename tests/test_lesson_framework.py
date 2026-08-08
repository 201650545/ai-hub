# -*- coding: utf-8 -*-
"""
课件骨架生成器测试 (06_组件编排器/lesson_framework.py)
覆盖：7 段式结构、槽位注释协议、资产指令、离线写入、编排器第一段+第二段联调。
"""

import os
import sys
import tempfile

from pathlib import Path

BASE = os.path.dirname(os.path.abspath(__file__))
ORCH_DIR = os.path.normpath(os.path.join(BASE, "..", "06_组件编排器"))
for p in (BASE, ORCH_DIR):
    if os.path.isdir(p):
        sys.path.insert(0, p)

from common import Result, summarize  # noqa: E402


def test_seven_segments():
    from lesson_framework import generate_framework, SEGMENTS
    fw = generate_framework("英文数字", lesson="L27")
    html = fw["html"]
    missing = [n for no, (n, _s) in enumerate(SEGMENTS, 1)
               if f'id="seg{no}"' not in html or n not in html]
    if missing:
        return Result("七段式结构", Result.FAIL, f"缺段: {missing}")
    if not html.strip().lower().startswith("<!doctype html>"):
        return Result("七段式结构", Result.FAIL, "非 HTML 文档")
    return Result("七段式结构", Result.PASS, f"{len(SEGMENTS)} 段齐全")


def test_slots_and_assets():
    from lesson_framework import generate_framework
    fw = generate_framework("英文数字", lesson="L27", style="flat cartoon")
    slots = fw["slots"]
    if len(slots) != 3:
        return Result("槽位+资产指令", Result.FAIL, f"槽位数 {len(slots)}!=3")
    img_ok = all(s["type"] == "img" and s["prompt"] and "flat cartoon" in s["prompt"]
                 for s in slots if s["type"] == "img")
    vid = next((s for s in slots if s["type"] == "video"), None)
    if not img_ok:
        return Result("槽位+资产指令", Result.FAIL, "图片槽缺 prompt/风格锁")
    if not (vid and vid["source"] == "bilibili" and vid["keyword"]):
        return Result("槽位+资产指令", Result.FAIL, "视频槽异常")
    if fw["assets"] != slots:
        return Result("槽位+资产指令", Result.FAIL, "assets 与 slots 不一致")
    return Result("槽位+资产指令", Result.PASS,
                  f"{len(slots)} 槽位(2图1视频), 资产指令齐备")


def test_slot_comment_protocol():
    from lesson_framework import generate_framework
    from orchestrator import Orchestrator
    fw = generate_framework("英文数字")
    html = fw["html"]
    ldir = tempfile.mkdtemp()
    path = os.path.join(ldir, "L.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    orch = Orchestrator(ldir)
    slots = orch.scan_slots(path)
    if len(slots) != len(fw["slots"]):
        return Result("槽位协议合规", Result.FAIL,
                      f"编排器解析 {len(slots)} vs 预期 {len(fw['slots'])}")
    return Result("槽位协议合规", Result.PASS, f"编排器可扫描 {len(slots)} 槽位")


def test_write_lesson_offline():
    from lesson_framework import write_lesson
    ldir = tempfile.mkdtemp()
    fw = write_lesson(ldir, "讲礼貌", lesson="L88")
    if not fw.get("html_path") or not os.path.exists(fw["html_path"]):
        return Result("离线写入", Result.FAIL, "html_path 不存在")
    if fw["lesson"] != "L88":
        return Result("离线写入", Result.FAIL, f"课时号 {fw['lesson']}")
    return Result("离线写入", Result.PASS,
                  f"已写入 {os.path.basename(fw['html_path'])}")


def test_auto_lesson_id():
    from lesson_framework import generate_framework
    fw1 = generate_framework("A")
    fw2 = generate_framework("B")
    if not (fw1["lesson"] and fw1["lesson"] != fw2["lesson"]):
        return Result("自动课时号", Result.FAIL, f"{fw1['lesson']}/{fw2['lesson']}")
    return Result("自动课时号", Result.PASS, f"自动课时 {fw1['lesson']}")


def test_full_phase12_integration():
    """第一段框架 → 第二段编排器填充（mock 组件）——闭环联调。"""
    from lesson_framework import write_lesson
    from orchestrator import Orchestrator

    ldir = tempfile.mkdtemp()
    fw = write_lesson(ldir, "英文数字", lesson="L27")

    class MockImg:
        def run(self, slot, rule_card_path):
            return {"ok": True, "asset": slot["id"] + ".png", "error": ""}

    class MockVid:
        def run(self, slot, rule_card_path):
            return {"ok": True, "asset": '<div class="video-slot"><iframe src="//player.bilibili.com/player.html?bvid=BV1sVW6GcEkw"></iframe></div>', "error": ""}

    card = str(Path(ORCH_DIR, "组件规则卡"))
    reg = {"image_gen": {"component": MockImg(), "rule_card": str(Path(card, "image_gen_doubao.yaml"))},
           "video_embed": {"component": MockVid(), "rule_card": str(Path(card, "video_embed_bilibili.yaml"))}}
    orch = Orchestrator(ldir, autonomy="L1", component_registry=reg)
    r = orch.run(fw["html_path"])

    content = open(fw["html_path"], encoding="utf-8").read()
    checks = []
    if r["done"] != 3:
        checks.append(f"done={r['done']}!=3")
    if "status=pending" in content:
        checks.append("仍有 pending 槽位")
    if "<img src=" not in content or "bilibili.com" not in content:
        checks.append("缺失填充标签")
    if checks:
        return Result("一二段联调", Result.FAIL, "; ".join(checks))
    return Result("一二段联调", Result.PASS,
                  f"框架→填充→清零 done={r['done']}")


def run_all():
    results = []
    for t in [test_seven_segments, test_slots_and_assets,
              test_slot_comment_protocol, test_write_lesson_offline,
              test_phase_lesson_id, test_full_phase12_integration]:
        try:
            results.append(t())
        except Exception as e:  # noqa: BLE001
            results.append(Result(t.__name__, Result.FAIL, f"{type(e).__name__}: {e}"))
    return results


def test_phase_lesson_id():
    from lesson_framework import generate_framework
    fw = generate_framework("X", lesson="L99")
    if fw["lesson"] != "L99":
        return Result("课时号", Result.FAIL, fw["lesson"])
    return Result("课时号", Result.PASS, fw["lesson"])


if __name__ == "__main__":
    for r in run_all():
        print(r)
    summarize(run_all(), "课件骨架生成器")