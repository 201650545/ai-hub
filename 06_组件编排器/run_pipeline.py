# -*- coding: utf-8 -*-
"""
run_pipeline.py — 组件编排器顶层跑手
串联 lesson_framework → orchestrator → components 完成两段式课件生成。

用法：
  python run_pipeline.py --topic "英文数字" --lesson L27 --style "flat cartoon"
  python run_pipeline.py --topic "超市场景" --card image_gen_doubao.yaml --autonomy L1

架构依据：06_组件编排器/组件编排器架构设计.md §2/§7/§8
"""

import argparse
import datetime
import json
import os
import sys

# 确保能找到同级模块
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)

from lesson_framework import write_lesson
from orchestrator import Orchestrator

RULE_CARD_DIR = os.path.join(_THIS_DIR, "组件规则卡")

# 默认组件注册表
def _default_registry(image_card: str = "image_gen_doubao.yaml") -> dict:
    from components import image_gen, video_embed_bilibili
    return {
        "image_gen": {
            "component": image_gen,
            "rule_card": os.path.join(RULE_CARD_DIR, image_card),
        },
        "video_embed": {
            "component": video_embed_bilibili,
            "rule_card": os.path.join(RULE_CARD_DIR, "video_embed_bilibili.yaml"),
        },
    }


def _list_cards() -> list:
    import glob
    cards = []
    for fp in glob.glob(os.path.join(RULE_CARD_DIR, "image_gen_*.yaml")):
        try:
            import yaml
            with open(fp, "r", encoding="utf-8") as f:
                c = yaml.safe_load(f)
                if c:
                    cards.append((os.path.basename(fp), c.get("site", "?"), c.get("status", "?")))
        except Exception:
            cards.append((os.path.basename(fp), "?", "?"))
    return cards


def _event_printer(ev: dict) -> None:
    """打印事件到终端（§8 SSE 协议的可读格式）。"""
    ts = ev.get("ts", "")
    phase = ev.get("phase", "")
    slot = ev.get("slot", "")
    event = ev.get("event", "")
    detail = ev.get("detail", "")
    icon = {"prompt_ready": "📝", "generating": "🎨", "done": "✅",
            "retry": "🔄", "failed": "❌", "slot_list_confirm": "⏸️"}.get(event, "ℹ️")
    label = f"[{phase}]" if phase and phase != "deliver" else ""
    slot_tag = f"({slot})" if slot else ""
    print(f"  {icon} {label} {slot_tag} {detail}" if detail else f"  {icon} {label} {slot_tag} {event}")


def run_pipeline(topic: str, lesson: str = "", style: str = "",
                 autonomy: str = "L2", image_card: str = "image_gen_doubao.yaml",
                 lesson_dir: str | None = None,
                 event_callback=None) -> dict:
    """
    全流程入口。

    Parameters
    ----------
    topic : 课程主题（必填）
    lesson : 课时号，如 L27；缺省自动生成
    style : 图片风格锁
    autonomy : L1 全自动 / L2 关键节点确认 / L3 每步确认
    image_card : 图片规则卡文件名（在组件规则卡/ 下）
    lesson_dir : 课时输出目录；缺省自动创建
    event_callback : 事件回调函数（可选）；缺省用 _event_printer 打印到终端

    Returns
    -------
    {"ok", "lesson", "html_path", "pipeline", "errors"}
    """
    # 1. 确定输出目录
    lid = lesson.strip() or f"L{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    if not lesson_dir:
        lesson_dir = os.path.join(_THIS_DIR, "课时样例", lid)
    os.makedirs(lesson_dir, exist_ok=True)

    # 2. 生成框架（第一段）
    print(f"\n{'='*50}")
    print(f"📋 第一段：生成课件框架 — {topic}")
    print(f"   输出目录: {lesson_dir}")
    fw = write_lesson(lesson_dir, topic, lesson, style)
    html_path = fw["html_path"]
    print(f"   框架 HTML: {html_path} ({len(fw['html'])} bytes)")
    print(f"   槽位数: {len(fw['slots'])}")
    for s in fw["slots"]:
        kw = s.get("prompt") or s.get("keyword") or ""
        print(f"     - {s['id']} ({s['type']}): {kw[:50]}...")
    print(f"{'='*50}\n")

    # 3. 构建组件注册表
    registry = _default_registry(image_card)
    print(f"📦 组件注册表:")
    for k, v in registry.items():
        print(f"     - {k}: {os.path.basename(v['rule_card'])}")
    print()

    # 4. 编排器第二段
    cb = event_callback or _event_printer
    orch = Orchestrator(lesson_dir, autonomy, registry)
    print(f"⚙️  第二段：资产填充（档位 {autonomy}）")
    result = orch.run(html_path, event_callback=cb)

    # 5. 汇总
    print(f"\n{'='*50}")
    print(f"📊 管线结果")
    print(f"   成功: {result.get('done', 0)} | 失败: {result.get('failed', 0)} | 跳过: {result.get('skipped', 0)}")
    print(f"   耗时: {result.get('elapsed_s', 0):.1f}s")
    print(f"   输出: {html_path}")

    # 6. 验证报告
    ver = orch.verify(html_path)
    if ver["ok"]:
        print(f"   ✅ 资产校验全部通过")
    else:
        print(f"   ⚠️  资产校验问题: {ver['issues']}")

    errors = []
    if result.get("failed", 0) > 0:
        errors.append(f"{result['failed']} 个槽位填充失败")

    out = {
        "ok": result.get("failed", 0) == 0,
        "lesson": lid,
        "html_path": html_path,
        "pipeline": result,
        "errors": errors or None,
    }
    return out


def main():
    parser = argparse.ArgumentParser(
        description="组件编排器 — 两段式课件生成管线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "可用图片规则卡:\n"
            + "\n".join(f"  {n:40s} {s:20s} {st}"
                        for n, s, st in _list_cards())
        ),
    )
    parser.add_argument("--topic", "-t", required=True, help="课程主题")
    parser.add_argument("--lesson", "-l", default="", help="课时号，如 L27")
    parser.add_argument("--style", "-s", default="flat cartoon, 儿童教材插画风, 明亮色调",
                        help="图片风格锁")
    parser.add_argument("--autonomy", "-a", default="L2", choices=["L1", "L2", "L3"],
                        help="执行档位 (L1=全自动, L2=关键节点确认, L3=每步确认)")
    parser.add_argument("--card", "-c", default="image_gen_doubao.yaml",
                        help="图片规则卡文件名")
    parser.add_argument("--dir", "-d", default=None,
                        help="课时输出目录（缺省自动创建）")
    parser.add_argument("--json", action="store_true",
                        help="仅输出 JSON 结果（不打印事件）")
    args = parser.parse_args()

    cb = None if args.json else _event_printer
    result = run_pipeline(
        topic=args.topic,
        lesson=args.lesson,
        style=args.style,
        autonomy=args.autonomy,
        image_card=args.card,
        lesson_dir=args.dir,
        event_callback=cb,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"\n{'='*50}")
        print(f"{'✅ 管线完成' if result['ok'] else '❌ 管线有误'}")
        if result.get("errors"):
            for e in result["errors"]:
                print(f"  - {e}")
        print(f"   HTML: {result['html_path']}")
        print(f"{'='*50}")


if __name__ == "__main__":
    main()