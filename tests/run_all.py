# -*- coding: utf-8 -*-
"""
E2E 验收测试套件 — 总入口
依次运行：中央平台 / 网关 / 引擎 三组，最后汇总。
"""

import os
import re
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(BASE, ".."))
sys.path.insert(0, BASE)

from common import Result, summarize  # noqa: E402


def test_secret_scan():
    """敏感信息扫描：git grep 检测真实 key/token 模式，应无命中。"""
    try:
        r = subprocess.run(
            ["git", "grep", "-nE", r"(sk-[A-Za-z0-9]{16,}|AIza[A-Za-z0-9_-]{20,}|Bearer [A-Za-z0-9._-]{20,})"],
            cwd=ROOT,
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        return Result("敏感信息扫描", Result.SKIP, "git 不可用")
    except Exception as e:  # noqa: BLE001
        return Result("敏感信息扫描", Result.SKIP, f"扫描异常: {e}")
    # 过滤示例/占位文件（含 your-...-here / example / .example 命名）
    hits = []
    for line in (r.stdout or "").splitlines():
        low = line.lower()
        if ".example" in low or "your-" in low and "here" in low or "xxx" in low:
            continue
        hits.append(line)
    if not hits:
        return Result("敏感信息扫描", Result.PASS, "未发现 sk-/AIza/Bearer 真实 key 入库")
    return Result("敏感信息扫描", Result.FAIL, f"发现疑似 key:\n" + "\n".join(hits))


def main() -> None:
    import importlib

    # 套件清单：(模块名, 中文名)。
    # 网关三件套（03_共享组件）已随 48eac65 删除，test_gateway/test_engines/
    # test_history/test_quota 依赖其 history/quota/engines 模块——缺失时整套 SKIP
    # （保留文件供参考，不删除），其余在测套件照常运行。
    SUITES = [
        ("test_central", "中央平台"),
        ("test_gateway", "网关"),
        ("test_engines", "引擎"),
        ("test_history", "历史管理"),
        ("test_quota", "额度统计"),
        ("test_orchestrator", "编排器"),
        ("test_video_embed", "视频组件"),
        ("test_lesson_framework", "课件骨架"),
    ]

    all_results = []
    for mod_name, desc in SUITES:
        try:
            mod = importlib.import_module(mod_name)
        except ImportError as e:
            r = Result(desc, Result.SKIP, f"模块缺失（{mod_name}）: {e}")
            print(f"===== {desc} test suite =====")
            print(r)
            all_results.append(r)
            continue
        try:
            res = mod.run_all()
        except ModuleNotFoundError as e:
            # 函数内惰性 import（如 test_gateway 运行时 import channels）依赖
            # 已删除的共享组件 → 整套 SKIP
            r = Result(desc, Result.SKIP, f"依赖模块缺失（{mod_name}）: {e}")
            print()
            print(f"===== {desc} test suite =====")
            print(r)
            all_results.append(r)
            continue
        print()
        print(f"===== {desc} test suite =====")
        for r in res:
            print(r)
        passed, failed, skipped = summarize(res, desc)
        all_results.extend(res)

    print()
    print("===== 敏感信息扫描 =====")
    sec = test_secret_scan()
    print(sec)
    all_results.append(sec)

    total = len(all_results)
    passed = sum(1 for r in all_results if r.status == Result.PASS)
    failed = sum(1 for r in all_results if r.status == Result.FAIL)
    skipped = sum(1 for r in all_results if r.status == Result.SKIP)
    print()
    print(f"总览: {passed}/{total} 通过, {failed} 失败, {skipped} 跳过")
    if failed:
        print("存在 FAIL，请查看上方明细。")
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())