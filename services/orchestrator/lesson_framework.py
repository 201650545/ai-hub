# -*- coding: utf-8 -*-
"""课件骨架生成器（两段式生成 · 第一段）

架构依据：06_组件编排器/组件编排器架构设计.md §2 第一段
职责：接收用户目标（主题/课时号）→ 产出 7 段式 HTML 课件总框架 + 媒体槽位注释 + 资产指令。

槽位协议与 §3 完全一致：
    <!-- MEDIA:img id=.. topic=".." prompt=".." mode=download status=pending -->
    <!-- MEDIA:video id=.. topic=".." keyword=".." source=bilibili mode=embed status=pending -->
产出 HTML 可直接交给 Orchestrator.run() 走第二段资产填充。

ai_gen 可选注入：接收 (topic, segment_name) 返回教学文案；
缺省生成确定性模板文案（可离线、可单测），AI 文案增强由上层按需接入。
"""

import datetime
import re

from pathlib import Path

# ---------------------------------------------------------------- 七段式

SEGMENTS = [
    ("导入激活", "lead-in"),
    ("新知呈现", "presentation"),
    ("词汇句型", "vocabulary"),
    ("互动练习", "practice"),
    ("巩固视频", "extension"),
    ("总结反馈", "summary"),
    ("作业布置", "assignment"),
]

# 段内媒体类型：lead-in 插图 / vocabulary 插图 / extension 视频
KIND_BY_SEG = {"lead-in": "img", "vocabulary": "img", "extension": "video"}


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _escape(s: str) -> str:
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _slot_comment(slot: dict) -> str:
    if slot["type"] == "img":
        return (f'<!-- MEDIA:img id={slot["id"]} topic="{slot["topic"]}" '
                f'prompt="{slot["prompt"]}" mode=download status=pending -->')
    return (f'<!-- MEDIA:video id={slot["id"]} topic="{slot["topic"]}" '
            f'keyword="{slot["keyword"]}" source=bilibili mode=embed status=pending -->')


# ---------------------------------------------------------------- 槽位与资产指令


def _img_prompt(topic: str, segment_name: str, style: str) -> str:
    base = f"{topic}的{segment_name}场景，儿童教材插画风"
    return f"{base}, {style}" if style else base


def _video_keyword(topic: str) -> str:
    return f"{topic} song for kids" if re.search(r"[A-Za-z]", topic) else f"{topic} 儿歌视频"


def _make_slot(kind: str, segment_no: int, topic: str,
               segment_name: str, style: str) -> dict:
    sid = f"p{segment_no}_{kind}"
    if kind == "img":
        return {"id": sid, "type": "img", "topic": _escape(topic),
                "prompt": _escape(_img_prompt(topic, segment_name, style)),
                "mode": "download", "status": "pending"}
    return {"id": sid, "type": "video", "topic": _escape(topic),
            "keyword": _escape(_video_keyword(topic)), "source": "bilibili",
            "mode": "embed", "status": "pending"}


def _make_slots(topic: str, style: str) -> list:
    slots = []
    for no, (name, seg_id) in enumerate(SEGMENTS, start=1):
        kind = KIND_BY_SEG.get(seg_id)
        if kind:
            slots.append(_make_slot(kind, no, topic, name, style))
    return slots


# ---------------------------------------------------------------- HTML 模板


def _media_box(slot: dict) -> str:
    slot_line = _slot_comment(slot)
    hint = slot["prompt"] if slot["type"] == "img" else slot["keyword"]
    label = "生图提示" if slot["type"] == "img" else "检索关键词"
    return (f'<div class="media-box">\n'
            f'  <h3>{slot["topic"]}</h3>\n'
            f'  {slot_line}\n'
            f'  <p class="hint">{label}：{hint}</p>\n'
            f'</div>\n')


def _slide(no: int, name: str, slot: dict | None) -> str:
    content = _media_box(slot) if slot else '<p class="body">（教学文案由 AI 适配器生成）</p>'
    return (f'<section id="seg{no}" class="slide">\n'
            f'  <header><h2>{no}. {name}</h2></header>\n'
            f'  {content}'
            f'</section>\n')


def _render_html(title: str, topic: str, created: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_escape(title)}</title>
<style>
  body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; margin: 0; color: #2d3748; }}
  .cover {{ text-align: center; padding: 9vh 4%; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: #fff; }}
  .cover h1 {{ font-size: 2.6rem; margin: 0.5rem 0; }}
  .cover p {{ font-size: 1.05rem; opacity: .92; }}
  .slide {{ min-height: 60vh; border: 1px solid #e2e8f0; border-radius: 12px; padding: 2.5vh 4%; margin: 3vh 4%; box-shadow: 0 2px 8px rgba(0,0,0,.06); }}
  .slide header {{ border-bottom: 2px solid #764ba2; margin-bottom: 1.5vh; }}
  .slide header h2 {{ margin: .4rem 0; color: #5b3b8f; }}
  .media-box {{ margin: 1rem 0; }}
  .media-box img {{ width: 100%; max-height: 46vh; object-fit: contain; }}
  .media-box .hint {{ color: #a0aec0; font-size: .9rem; }}
  .media-box iframe {{ width: 100%; aspect-ratio: 16 / 9; border: 0; }}
</style>
</head>
<body>
<section class="cover">
  <h1>{_escape(title)}</h1>
  <p>主题：{_escape(topic)}</p>
  <p>生成时间：{_escape(created)}</p>
</section>
{body}
</body>
</html>
"""


# ---------------------------------------------------------------- 主入口


def generate_framework(topic: str, lesson: str = "", style: str = "",
                       ai_gen=None) -> dict:
    """生成 7 段式课件框架。

    topic: 课程主题（必填）
    lesson: 课时号，如 L27；缺省自动生成
    style: 图片风格锁（拼接进 prompt）
    ai_gen: 可选 AI 文案回调 (topic, segment_name) -> str

    返回 {"html","slots","assets","lesson","title","created"}。
    slots 即资产指令（含 prompt/keyword），可直接交编排器第二段填充。
    """
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("话题 topic 不能为空")
    lid = (lesson or "").strip() or f"L{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    now = _now()
    title = f"{lid} {topic} 课件"

    slots = _make_slots(topic, style)
    frames = []
    slot_iter = iter(slots)
    for no, (name, seg_id) in enumerate(SEGMENTS, start=1):
        frame_slot = next(slot_iter, None) if KIND_BY_SEG.get(seg_id) else None
        frames.append(_slide(no, name, frame_slot))

    body = "".join(frames)
    html = _render_html(title, topic, now, body)
    return {"html": html, "slots": slots, "assets": list(slots),
            "lesson": lid, "title": title, "created": now}


def write_lesson(lesson_dir: str, topic: str, lesson: str = "",
                 style: str = "", ai_gen=None) -> dict:
    """生成框架并写入课时文件夹，返回框架 dict（含 html_path）。"""
    fw = generate_framework(topic, lesson, style, ai_gen)
    out_dir = Path(lesson_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"{fw['lesson']}.html"
    html_path.write_text(fw["html"], encoding="utf-8")
    fw["html_path"] = str(html_path)
    return fw


if __name__ == "__main__":
    fw = generate_framework("英文数字", lesson="L27", style="flat cartoon")
    print(fw["lesson"], "| html bytes", len(fw["html"]))
    for s in fw["slots"]:
        print(s["id"], s["type"], "->", s.get("prompt") or s.get("keyword"))