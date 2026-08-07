# -*- coding: utf-8 -*-
"""
中央平台测试 (:8000)
覆盖: 导航页 / 网关注册与心跳 / 统计 / dashboard 静态文件。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import Result, http_get, http_post, check_service, summarize

CENTRAL = "http://localhost:8000"
TEST_GID = "e2e_test_gw"


def _register_test_gateway():
    """注册一个测试网关，返回 (ok, resp)。"""
    code, body = http_post(f"{CENTRAL}/api/gateways", {
        "id": TEST_GID, "name": "E2E Test", "port": 39999,
        "url": "http://localhost:39999",
    })
    return code, body


def test_index():
    """GET / 应返回 200 且含 'AI Hub' 标题。"""
    code, text = http_get(f"{CENTRAL}/")
    if code is None:
        return Result("导航页 GET /", Result.FAIL, str(text.get("error", "")))
    if code == 200 and "AI Hub" in (text or ""):
        return Result("导航页 GET /", Result.PASS, "200 + 含 AI Hub")
    return Result("导航页 GET /", Result.FAIL, f"code={code} content={'AI Hub' in str(text)}")


def test_list_gateways():
    code, body = http_get(f"{CENTRAL}/api/gateways")
    if code == 200 and isinstance(body, dict) and "gateways" in body:
        return Result("列表 GET /api/gateways", Result.PASS, f"含 {len(body['gateways'])} 个网关")
    return Result("列表 GET /api/gateways", Result.FAIL, f"code={code}, keys={list(body.keys()) if isinstance(body, dict) else type(body)}")


def test_register():
    code, body = http_post(f"{CENTRAL}/api/gateways", {"id": TEST_GID, "name": "E2E Test"})
    if code == 200 and body.get("ok") and body.get("id") == TEST_GID:
        return Result("注册 POST /api/gateways", Result.PASS, f"id={TEST_GID}")
    return Result("注册 POST /api/gateways", Result.FAIL, f"code={code} body={body}")


def test_heartbeat():
    code, body = http_post(f"{CENTRAL}/api/gateways/{TEST_GID}/heartbeat")
    if code == 200 and body.get("ok"):
        return Result("心跳 POST /heartbeat", Result.PASS, "last_seen 更新")
    return Result("心跳 POST /heartbeat", Result.FAIL, f"code={code} body={body}")


def test_unregister():
    code, body = http_post(f"{CENTRAL}/api/gateways/{TEST_GID}/unregister")
    if code == 200 and body.get("ok"):
        return Result("注销 POST /unregister", Result.PASS, "status=offline")
    return Result("注销 POST /unregister", Result.FAIL, f"code={code} body={body}")


def test_stats():
    code, body = http_get(f"{CENTRAL}/api/stats")
    if code == 200 and isinstance(body, dict):
        keys = {"total_gateways", "online_gateways", "offline_gateways"}
        if keys <= set(body.keys()):
            return Result("统计 GET /api/stats", Result.PASS, str(body))
    return Result("统计 GET /api/stats", Result.FAIL, f"code={code} body={body}")


def test_dashboard():
    code, _ = http_get(f"{CENTRAL}/dashboard/index.html")
    if code == 200:
        return Result("面板 GET /dashboard/index.html", Result.PASS, "200")
    return Result("面板 GET /dashboard/index.html", Result.FAIL, f"code={code}")


def main():
    results = []
    if check_service(f"{CENTRAL}/", "中央平台 :8000"):
        results.append(test_index())
        results.append(test_list_gateways())
        results.append(test_register())
        results.append(test_heartbeat())
        results.append(test_unregister())
        results.append(test_stats())
        results.append(test_dashboard())
    else:
        results.append(Result("中央平台服务检查", Result.SKIP, "服务未启动"))
    return results


# run_all 别名（供 run_all.py 聚合用）
run_all = main