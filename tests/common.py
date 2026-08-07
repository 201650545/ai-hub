# -*- coding: utf-8 -*-
"""
E2E 验收测试套件 — 公共工具
提供: HTTP helper、服务在线检查、结果汇总。
"""

import json
import urllib.error
import urllib.request


class Result:
    """单个用例结果。"""
    PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"

    def __init__(self, name, status, detail=""):
        self.name = name
        self.status = status
        self.detail = detail

    def __str__(self):
        return f"[{self.status}] {self.name} — {self.detail}"


def _request(method, url, body=None, timeout=10):
    """返回 (status, parsed_json|text)。异常返回 (None, {"error": ...})。"""
    data, headers = None, {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "ignore")
            code = resp.getcode()
    except urllib.error.HTTPError as e:
        code = e.code
        raw = e.read().decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001
        return None, {"error": str(e)[:150]}
    try:
        return code, json.loads(raw)
    except Exception:  # noqa: BLE001
        return code, raw


def http_get(url, timeout=10):
    return _request("GET", url, timeout=timeout)


def http_post(url, body=None, timeout=10):
    return _request("POST", url, body=body, timeout=timeout)


def check_service(url, name, timeout=5):
    """服务在线返回 True，否则打印提示并返回 False。"""
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except Exception:  # noqa: BLE001
        print(f"  ⚠️ 服务未在线: {name} ({url}) — 请先启动后再运行测试")
        return False


def summarize(results, suite=""):
    """汇总：总计 X 通过 / Y 失败 / Z 跳过。返回 (passed, failed, skipped)。"""
    passed = sum(1 for r in results if r.status == Result.PASS)
    failed = sum(1 for r in results if r.status == Result.FAIL)
    skipped = sum(1 for r in results if r.status == Result.SKIP)
    print(f"  【{suite or '本组'}】总计 {passed} 通过 / {failed} 失败 / {skipped} 跳过")
    return passed, failed, skipped