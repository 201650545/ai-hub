# -*- coding: utf-8 -*-
"""
引擎测试 (ds_v4_cli/engines.py)
覆盖：会话自建(A2A)、多轮记录结构、历史读取。
引擎依赖本地 opencli 浏览器登录会话；无已连接引擎时标记 SKIP。
"""

import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
GATEWAY_DIR = os.path.normpath(os.path.join(BASE, "..", "02_网关实例", "ds_v4_cli"))
sys.path.insert(0, BASE)
if os.path.isdir(GATEWAY_DIR):
    sys.path.insert(0, GATEWAY_DIR)

from common import Result, summarize  # noqa: E402


def _load_engines():
    if not os.path.isfile(os.path.join(GATEWAY_DIR, "engines.py")):
        return None
    sys.path.insert(0, GATEWAY_DIR)
    sys.modules.pop("engines", None)
    import engines  # noqa: WPS433
    return engines


def _pick_connected(engines):
    """返回第一个已连接的引擎 id，未连接返回 None。"""
    try:
        hs = engines.health_all()
        for eid in engines.ENGINE_ORDER:
            if hs.get(eid) and hs[eid].get("connected"):
                return eid
    except Exception:  # noqa: BLE001
        return None
    return None


def test_engine_config_wiring(engines):
    """静态配置校验：豆包/通义走专用提取器，通义用 type 原生键入 + 发送按钮提交。"""
    try:
        checks = []
        checks.append((
            "豆包专用提取器",
            engines.ENGINES["doubao"]["extract_js"] is engines.DOUBAO_EXTRACT_JS,
            f"extract={engines.ENGINES['doubao']['extract_js'] is engines.DOUBAO_EXTRACT_JS}",
        ))
        db = engines.ENGINES["doubao"]
        checks.append(("豆包 type 原生键入", db.get("input_method") == "type",
                       f"method={db.get('input_method')}"))
        checks.append(("豆包温和提交", db.get("gentle_submit") is True,
                       f"gentle={db.get('gentle_submit')}"))
        qw = engines.ENGINES["qianwen"]
        checks.append(("通义专用提取器", qw["extract_js"] is engines.QIANWEN_EXTRACT_JS,
                       f"extract={qw['extract_js'] is engines.QIANWEN_EXTRACT_JS}"))
        checks.append(("通义 type 原生键入", qw.get("input_method") == "type",
                       f"method={qw.get('input_method')}"))
        checks.append(("通义 enter+发送按钮提交", bool(qw.get("submit", {}).get("enter")) and bool(qw.get("submit", {}).get("click")),
                       f"submit={qw.get('submit', {}).get('click')}"))

        for name, ok, info in checks:
            if not ok:
                return Result("引擎输入/配置套", Result.FAIL, f"{name}:{info}")
        return Result("引擎输入/配置套", Result.PASS,
                      f"{len(checks)} 项配置正确(doubao+qianwen)")
    except Exception as e:  # noqa: BLE001
        return Result("引擎输入/提取配置", Result.FAIL, f"{type(e).__name__}: {e}")


def test_a2a_auto_conversation(engines):
    """start_conversation 无参时返回自动生成的 conversation_id。"""
    try:
        cid = engines.start_conversation("kimi")
        ok = isinstance(cid, str) and cid.startswith("conv_")
        if ok:
            engines.end_conversation("kimi", cid)
            return Result("引擎会话自动生成", Result.PASS, f"id={cid}")
        return Result("引擎会话自动生成", Result.FAIL, f"返回异常:{cid!r}")
    except Exception as e:  # noqa: BLE001
        return Result("引擎会话自动生成", Result.FAIL, f"{type(e).__name__}: {e}")


def test_multi_turn(engines, eid):
    """连接引擎上的多轮：start→ask→history→end。"""
    cid = None
    try:
        cid = engines.start_conversation(eid)
        if not cid:
            return Result("引擎多轮对话", Result.FAIL, "start 未返回会话 id")

        r1 = engines.ask_conversation(eid, cid, "你好，请用一句话自我介绍")
        if r1.get("status") != "ok":
            return Result("引擎多轮对话", Result.SKIP,
                          f"{eid} 首轮未就绪({r1.get('status')}:{(r1.get('error') or '')[:60]})")

        hist = engines.get_conversation_history(eid, cid)
        turns = len(hist)
        roles = [h.get("role") for h in hist if isinstance(h, dict)]
        if turns >= 2 and roles[:2] == ["user", "assistant"]:
            engines.end_conversation(eid, cid)
            cid = None
            return Result("引擎多轮对话", Result.PASS, f"user->assistant 共 {turns} 条")
        return Result("引擎多轮对话", Result.FAIL, f"历史异常 roles={roles}")
    except Exception as e:  # noqa: BLE001
        return Result("引擎多轮对话", Result.FAIL, f"{type(e).__name__}: {e}")
    finally:
        if cid:
            try:
                engines.end_conversation(eid, cid)
            except Exception:  # noqa: BLE001
                pass


def run_all():
    results = []
    engines = _load_engines()
    if engines is None:
        results.append(Result("引擎模块加载", Result.SKIP, "缺少 ds_v4_cli/engines.py"))
        return results

    results.append(test_a2a_auto_conversation(engines))
    results.append(test_engine_config_wiring(engines))

    test_engine = _pick_connected(engines)
    if test_engine:
        results.append(test_multi_turn(engines, test_engine))
    else:
        results.append(Result("引擎多轮对话", Result.SKIP, "无已连接引擎会话（opencli 浏览器未绑定）"))
    return results


def _pick_connected(engines):
    try:
        hs = engines.health_all()
        for eid in engines.ENGINE_ORDER:
            if hs.get(eid) and hs[eid].get("connected"):
                return eid
    except Exception:  # noqa: BLE001
        pass
    return None


# 占位（保留普通便捷入口）
def run_test():
    return run_all()


if __name__ == "__main__":
    for r in run_test():
        print(r)
    summarize(run_test(), "引擎")