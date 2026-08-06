# -*- coding: utf-8 -*-
"""
引擎会话绑定助手 —— 为 4 大 AI 搜索引擎建立/核对 opencli 浏览器会话。

用法：
    python setup_engines.py            # 逐个打开站点并核对健康
    python setup_engines.py --all      # 全部打开（同上，默认行为）

原理：opencli 会话名不存在时 `open <url>` 会自动创建会话并打开站点。
首次打开时请在弹出的 Chrome 标签页里完成登录（元宝可微信/QQ 扫码），
然后重跑本脚本确认状态变为「已连接」。
"""

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engines  # noqa: E402


def run_cli(args, timeout=60):
    cmdline = subprocess.list2cmdline(engines._cli_prefix() + [str(a).replace("\r", " ").replace("\n", " ") for a in args])
    try:
        p = subprocess.run(cmdline, shell=True, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
        return p
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️ {e}")
        return None


def setup_one(engine_id, eng):
    sess = eng["session"]
    print(f"\n{'=' * 60}\n[{engine_id}] {eng['name']}  (会话: {sess})\n 站点: {eng['site_url']}")
    r = run_cli(["browser", sess, "open", eng["site_url"]])
    if r is None:
        print("  ❌ 无法执行 opencli（确认 opencli 已安装、daemon 运行中）")
        return False
    time.sleep(5)
    h = engines.engine_health(engine_id)
    ok = h["connected"] and h["input_found"]
    print(f"  状态: {'✅ 已连接' if ok else '⚠️ 待处理'}  URL: {h['url'][:70]}")
    if not h["connected"]:
        print("  → 请在打开的标签页中登录后重跑本脚本。")
    elif not h["input_found"]:
        print("  → 页面已打开但未检测到输入框，可能需登录或页面未就绪。")
    return ok


def main():
    print("🔌 引擎会话绑定助手")
    print("   (确保 opencli daemon 已运行、Chrome 扩展已连接)\n")
    for eid in engines.ENGINE_ORDER:
        setup_one(eid, engines.ENGINES[eid])

    print("\n\n📊 最终健康状态：")
    for eid, h in engines.health_all().items():
        flag = "✅" if (h["connected"] and h["input_found"]) else ("🟡" if h["connected"] else "⚪")
        print(f"  {flag} {eid:8s} URL: {h['url'][:60]}  输入框: {'有' if h['input_found'] else '无'}")
    print("\n提示：绑定完成后打开 http://localhost:3000 即可使用网页端；")
    print("     手机端 Pi Agent / Chatbox 用 http://<局域网IP>:3000/v1 。")


if __name__ == "__main__":
    main()
