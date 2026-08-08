# -*- coding: utf-8 -*-
"""
编排器核心测试 (06_组件编排器/orchestrator.py)
覆盖：槽位扫描、mock 组件联调、L2 确认暂停/恢复、事件协议、验证闭环。
使用 mock 组件，不依赖真实网络/浏览器。
"""

import os
import sys
import tempfile
import threading

from pathlib import Path

BASE = os.path.dirname(os.path.abspath(__file__))
ORCH_DIR = os.path.normpath(os.path.join(BASE, "..", "06_组件编排器"))
sys.path.insert(0, BASE)
if os.path.isdir(ORCH_DIR):
    sys.path.insert(0, ORCH_DIR)

from common import Result, summarize  # noqa: E402    


# ---------------------------------------------------------------- mock 组件

class MockImageComponent:
    """模拟图片组件：返回 png 资产文件名。"""

    def __init__(self, ok=True):
        self.ok = ok
        self.calls = 0

    def run(self, slot, rule_card_path):
        self.calls += 1
        if not self.ok:
            return {"ok": False, "asset": None, "error": "mock image failed"}
        return {"ok": True, "asset": slot["id"] + ".png", "error": ""}


class MockVideoComponent:
    """模拟视频组件：返回 iframe HTML。"""

    def __init__(self, ok=True):
        self.ok = ok
        self.calls = 0

    def run(self, slot, rule_card_path):
        self.calls += 1
        if not self.ok:
            return {"ok": False, "asset": None,
                    "error": f"mock video failed for {slot['id']}"}
        return {"ok": True, "asset": _iframe("BV1sVW6GcEkw"), "error": ""}


def _iframe(bv):
    return ('<div class="video-slot" style="position:relative;width:100%;'
            'aspect-ratio:16/9;"><iframe '
            'src="//player.bilibili.com/player.html?bvid=' + bv +
            '&page=1&high_quality=1&danmaku=0&autoplay=0" '
            'scrolling="no" border="0" frameborder="no" '
            'framespacing="0" allowfullscreen="true" '
            'style="position:absolute;inset:0;width:100%;height:100%;">'
            '</iframe></div>')


def _registry(img_ok=True, vid_ok=True):
    card_dir = Path(ORCH_DIR, "组件规则卡")
    return {
        "image_gen": {"component": MockImageComponent(img_ok),
                      "rule_card": str(card_dir / "image_gen_doubao.yaml")},
        "video_embed": {"component": MockVideoComponent(vid_ok),
                        "rule_card": str(card_dir / "video_embed_bilibili.yaml")},
    }


# ---------------------------------------------------------------- 组件全局快照
# 单测会临时替换 image_gen 模块全局（inject/extract/run_cli），跑完需恢复，
# 避免测试间相互污染（曾因未恢复导致后续用例拿到残留 fake 而误判）。
try:
    from components import image_gen as _image_gen
    _REAL_INJECT = _image_gen.inject_and_generate
    _REAL_EXTRACT = _image_gen.extract_image
    _REAL_RUNCLI = _image_gen.run_cli
except Exception:  # noqa: BLE001
    _REAL_INJECT = _REAL_EXTRACT = _REAL_RUNCLI = None


# ---------------------------------------------------------------- 测试用例

def _write_html(ldir, lines):
    html = os.path.join(ldir, "lesson.html")
    with open(html, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return html


def test_scan_slots():
    ldir = tempfile.mkdtemp()
    html = _write_html(ldir, [
        "<h1>L27 课件</h1>",
        '<!-- MEDIA:img id=p12_market topic="超市场景对话" prompt="A supermarket" mode=download status=pending -->',
        '<!-- MEDIA:video id=p30_song topic="英文数字儿歌" keyword="English number song kids" source=bilibili mode=embed status=pending -->',
        "<p>Hello</p>",
    ])
    from orchestrator import Orchestrator
    orch = Orchestrator(ldir)
    slots = orch.scan_slots(html)
    if len(slots) != 2:
        return Result("槽位扫描", Result.FAIL, f"共 {len(slots)} 槽位")
    img = slots[0]
    vid = slots[1]
    if not (img["type"] == "img" and img["prompt"] and img["source"] is None):
        return Result("槽位扫描", Result.FAIL, f"图片槽解析异常 {img}")
    if not (vid["type"] == "video" and vid["keyword"]
            and vid["source"] == "bilibili" and vid["mode"] == "embed"):
        return Result("槽位扫描", Result.FAIL, f"视频槽解析异常 {vid}")
    return Result("槽位解析", Result.PASS, f"{len(slots)} 槽位(1图1频)")


def test_format_error_line():
    ldir = tempfile.mkdtemp()
    html = _write_html(ldir, [
        '<p>x</p>',
        '<!-- MEDIA:video id=v1 topic="t" keyword="k" mode=embed status=pending -->',
    ])
    from orchestrator import Orchestrator
    orch = Orchestrator(ldir)
    try:
        orch.scan_slots(html)
        return Result("槽位格式报错", Result.FAIL, "缺失 source 未报错")
    except ValueError as e:
        if "source" in str(e) or "行 2" in str(e):
            return Result("槽位格式报错", Result.PASS, str(e))
        return Result("槽位格式报错", Result.FAIL, str(e))


def test_mock_full_run():
    ldir = tempfile.mkdtemp()
    lines = ["<h1>L27</h1>"]
    for i in ["p12_img", "p33_img2", "p45_img3"]:
        lines.append(f'<!-- MEDIA:img id={i} topic="图{i}" prompt="prompt {i}" mode=download status=pending -->')
    lines.append('<!-- MEDIA:video id=p60_vid topic="视频" keyword="kid song" source=bilibili mode=embed status=pending -->')
    html = _write_html(ldir, lines)

    from orchestrator import Orchestrator
    orch = Orchestrator(ldir, autonomy="L1", component_registry=_registry())
    events = []
    r = orch.run(html, event_callback=events.append)

    content = open(html, encoding="utf-8").read()
    bad = [ev for ev in events if not _valid_ev(ev)]
    checks = []
    if r["done"] != 4:
        checks.append(f"done={r['done']}!=4")
    if r["failed"] != 0:
        checks.append(f"failed={r['failed']}!=0")
    if "status=pending" in content:
        checks.append("有 pending 残留")
    if content.count("<iframe") != 1:
        checks.append(f"iframe 数量={content.count('<iframe')}!=1")
    if content.count("<img ") != 3:
        checks.append(f"img 数量={content.count('<img ')}!=3")
    if bad:
        checks.append(f"非法事件 {len(bad)} 条")
    if checks:
        return Result("mock 全流程", Result.FAIL, "; ".join(checks))
    return Result("mock 全流程", Result.PASS, f"done={ r['done']} 事件{len(events)}条")


def _valid_ev(ev):
    from orchestrator import validate_event
    return validate_event(ev)


def test_l2_pause_resume():
    ldir = tempfile.mkdtemp()
    html = _write_html(ldir, [
        '<!-- MEDIA:video id=p90 topic="测试视频" keyword="abc" source=bilibili mode=embed status=pending -->',
    ])
    from orchestrator import Orchestrator
    orch = Orchestrator(ldir, autonomy="L2", component_registry=_registry())
    events = []
    confirmation_seen = threading.Event()

    def cb(ev):
        events.append(ev)
        if ev["event"] == "slot_list_confirm":
            confirmation_seen.set()
            orch.confirm_slots()  # 模拟画布确认

    r = orch.run(html, event_callback=cb)
    if not confirmation_seen.is_set():
        return Result("L2 确认节点", Result.FAIL, "未发出 slot_list_confirm 事件")
    if r["done"] != 1:
        return Result("L2 确认节点", Result.FAIL, f"确认后 done={r['done']}")
    return Result("L2 确认节点", Result.PASS, "暂停→确认→恢复完成")


def test_failed_slot_reports():
    ldir = tempfile.mkdtemp()
    html = _write_html(ldir, [
        '<!-- MEDIA:video id=vbad topic="失败视频" keyword="news" source=bilibili mode=embed status=pending -->',
    ])
    from orchestrator import Orchestrator
    orch = Orchestrator(ldir, autonomy="L1",
                        component_registry=_registry(vid_ok=False))
    events = []
    r = orch.run(html, event_callback=events.append)
    content = open(html, encoding="utf-8").read()
    has_failed_event = any(ev["event"] == "failed" for ev in events)
    if r["failed"] != 1:
        return Result("失败槽位", Result.FAIL, f"failed={r['failed']}!=1")
    if not has_failed_event:
        return Result("失败槽位", Result.FAIL, "未推送 failed 事件")
    if "status=failed" not in content:
        return Result("失败槽位", Result.FAIL, "HTML 中未标记 status=failed")
    return Result("失败槽位", Result.PASS, "failed 事件+标记回写")


def test_verify_residue_and_image():
    ldir = tempfile.mkdtemp()
    html = _write_html(ldir, [
        "<img src=\"./i1.png\" alt=\"x\">",
    ])
    # 未放置 i1.png → 报图片缺失
    from orchestrator import Orchestrator
    orch = Orchestrator(ldir)
    v = orch.verify(html)
    if v["ok"] or not any("图片" in i for i in v["issues"]):
        return Result("verify 图片缺失", Result.FAIL, f"issues={v['issues']}")
    # 放置可解码 PNG → 通过
    from PIL import Image
    Image.new("RGB", (1, 1), (255, 255, 255)).save(os.path.join(ldir, "i1.png"))
    v2 = orch.verify(html)
    if not v2["ok"]:
        return Result("verify 图片解码", Result.FAIL, "; ".join(v2["issues"]))
    return Result("verify 资产校验", Result.PASS, "文件存在+PNG 解码通过")


def test_lesson_dir_injection():
    """编排器在调组件前会把 lesson_dir 注入槽位（image_gen 契约依赖它）。"""
    ldir = tempfile.mkdtemp()
    html = _write_html(ldir, [
        '<!-- MEDIA:img id=p12 topic="图" prompt="x" mode=download status=pending -->',
    ])
    seen = {}

    class CapturingComponent:
        def run(self, slot, rule_card_path):
            seen["slot"] = slot
            seen["card"] = rule_card_path
            return {"ok": True, "asset": "p12.png", "error": ""}

    from orchestrator import Orchestrator
    reg = {"image_gen": {"component": CapturingComponent(),
                         "rule_card": "image_gen_doubao.yaml"}}
    orch = Orchestrator(ldir, autonomy="L1", component_registry=reg)
    r = orch.run(html)
    if r["done"] != 1:
        return Result("lesson_dir 注入", Result.FAIL, f"done={r['done']}")
    if seen.get("slot", {}).get("lesson_dir") != ldir:
        return Result("lesson_dir 注入", Result.FAIL,
                      f"slot['lesson_dir']={seen.get('slot',{}).get('lesson_dir')}")
    return Result("lesson_dir 注入", Result.PASS, "slot 已携带课时目录")


def test_real_image_gen_two_arg_contract():
    """真实 image_gen.run 兼容两参数调用（编排器契约），且按 slot lesson_dir 存盘。"""
    ldir = tempfile.mkdtemp()
    from components import image_gen

    saved = {}

    def fake_inject(session, url, prompt, card):
        saved["prompt"] = prompt
        return True

    def fake_extract(session, card, save_path):
        from PIL import Image
        Image.new("RGB", (64, 64), (200, 30, 30)).save(save_path)
        return True

    image_gen.inject_and_generate = fake_inject
    image_gen.extract_image = fake_extract

    slot = {"id": "p12", "topic": "测试", "prompt": "a red apple",
            "mode": "download", "lesson_dir": ldir}
    card = os.path.join(ORCH_DIR, "组件规则卡", "image_gen_doubao.yaml")
    r = image_gen.run(slot, card)
    image_gen.inject_and_generate = _REAL_INJECT
    image_gen.extract_image = _REAL_EXTRACT
    if not r.get("ok"):
        return Result("image_gen 两参数", Result.FAIL, f"run 返回 {r}")
    if not saved.get("prompt"):
        return Result("image_gen 两参数", Result.FAIL, "未注入提示词")
    if not os.path.exists(os.path.join(ldir, "p12.png")):
        return Result("image_gen 两参数", Result.FAIL, "资产未写入 lesson_dir")
    return Result("image_gen 两参数", Result.PASS,
                  f"run(slot,card) ok, asset={r['asset']}, 提示词已注入")


def _b64png(seed: int) -> str:
    """根据 seed 生成一个可靠的 >100 字节 PNG 的 data URL（含不同像素）。"""
    import base64 as _b64
    import io
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (24, 24), (30, 90, 200))
    draw = ImageDraw.Draw(img)
    for i in range(24):
        for j in range(16):
            draw.point((i, j), ((seed * 13 + i * 7 + j * 3) % 256,
                                (seed * 5 + i) % 256, (j * 11) % 256))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + _b64.b64encode(buf.getvalue()).decode()


def test_image_gen_slot_isolation_regression():
    """回归：同一页面多槽位不得取同一张图（曾因共用 session + poll 命中旧图）。"""
    ldir = tempfile.mkdtemp()
    from components import image_gen

    pages = {}

    def fake_run_cli(args, timeout=90):
        import json as _json
        cmd = list(args)
        if cmd[0] == "browser" and len(cmd) >= 4:
            session, action = cmd[1], cmd[2]
            if action == "open":
                pages[session] = {"n": 0, "last": "", "generating": False}
                return {"ok": True, "stdout": "", "stderr": ""}
            if action == "keys":
                if session in pages:
                    pages[session]["generating"] = True
                return {"ok": True, "stdout": "", "stderr": ""}
            if action == "eval":
                js = cmd[3]
                page = pages.setdefault(session, {"n": 0, "last": "", "generating": False})
                if "JSON.stringify({n:imgs.length" in js:
                    if page["generating"]:
                        page["n"] += 1
                        page["last"] = _b64png(page["n"] + sum(map(ord, session)))
                        page["generating"] = False
                    return {"ok": True,
                            "stdout": _json.dumps({"n": page["n"], "s": page["last"]}),
                            "stderr": ""}
                if "img.src" in js:  # extract_image: 返回末张 src
                    return {"ok": True, "stdout": page["last"], "stderr": ""}
        return {"ok": True, "stdout": "not handled", "stderr": ""}

    image_gen.run_cli = fake_run_cli
    card = os.path.join(ORCH_DIR, "组件规则卡", "image_gen_doubao.yaml")

    def gen(slot_id, prompt):
        slot = {"id": slot_id, "topic": "t", "prompt": prompt,
                "mode": "download", "lesson_dir": ldir}
        return image_gen.run(slot, card)

    r1 = gen("p1_img", "red apple")
    r2 = gen("p2_img", "blue sky")
    image_gen.run_cli = _REAL_RUNCLI
    image_gen.inject_and_generate = _REAL_INJECT
    image_gen.extract_image = _REAL_EXTRACT
    if not (r1.get("ok") and r2.get("ok")):
        return Result("生图槽位隔离", Result.FAIL,
                      f"r1={r1.get('error')} r2={r2.get('error')}")
    b1 = open(os.path.join(ldir, "p1_img.png"), "rb").read()
    b2 = open(os.path.join(ldir, "p2_img.png"), "rb").read()
    if b1 == b2:
        return Result("生图槽位隔离", Result.FAIL, "两个槽位图片内容相同(未隔离)")
    return Result("生图槽位隔离", Result.PASS, "槽位会话隔离，图片互不相同")


def test_rule_card_load():
    card = Path(ORCH_DIR, "组件规则卡", "video_embed_bilibili.yaml")
    from orchestrator import load_rule_card
    data = load_rule_card(str(card))
    if not data:
        return Result("规则卡加载", Result.FAIL, "video_embed_bilibili.yaml 未加载")
    if data.get("component") != "video_embed":
        return Result("规则卡加载", Result.FAIL, f"component={data.get('component')}")
    return Result("规则卡加载", Result.PASS,
                  f"component={data['component']} mode={data.get('mode')}")


def run_all():
    results = []
    tests = [
        test_scan_slots,
        test_format_error_line,
        test_mock_full_run,
        test_l2_pause_resume,
        test_failed_slot_reports,
        test_verify_residue_and_image,
        test_lesson_dir_injection,
        test_real_image_gen_two_arg_contract,
        test_image_gen_slot_isolation_regression,
        test_rule_card_load,
    ]
    for t in tests:
        thr = None
        try:
            results.append(t())
        except Exception as e:  # noqa: BLE001
            results.append(Result(t.__name__, Result.FAIL, f"{type(e).__name__}: {e}"))
    return results


if __name__ == "__main__":
    for r in run_all():
        print(r)
    summarize(run_all(), "编排器核心")