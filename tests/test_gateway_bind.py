# -*- coding: utf-8 -*-
"""绑定地址 fail-closed 单测（GPT R2-GW-BIND-NARROW-2026-0829 裁定 P1）。

覆盖：空值/空白回退本机（防 Python 空串→INADDR_ANY 意外 wildcard）；
0.0.0.0/:: 及其展开/映射形式（0:0:0:0:0:0:0:0、::ffff:0.0.0.0）未授权=拒绝；
ALLOW_WILDCARD 严格白名单（非 "1" 真值仍拒绝）；显式授权后允许；LAN IP/localhost 正常。

运行：python tests/test_gateway_bind.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
GW = os.path.normpath(os.path.join(ROOT, "..", "services", "search_gateway"))
sys.path.insert(0, ROOT)

from common import Result  # noqa: E402

SNIPPET = (
    "import sys; sys.path.insert(0, %r); "
    "import api_gateway as g; "
    "print('BIND=' + g.BIND_HOST + '|WILD=' + str(g.BIND_WILDCARD_UNAUTHORIZED))"
) % GW


def _probe(env_extra, drop_bind=True):
    env = dict(os.environ)
    if drop_bind:
        env.pop("API_GATEWAY_BIND", None)
        env.pop("API_GATEWAY_ALLOW_WILDCARD", None)
    env.update(env_extra)
    r = subprocess.run([sys.executable, "-c", SNIPPET], capture_output=True,
                       text=True, env=env, cwd=GW, timeout=60)
    if r.returncode != 0:
        return None, r.stderr.strip().splitlines()[-1] if r.stderr else "exit=%d" % r.returncode
    line = (r.stdout or "").strip().splitlines()[-1]
    parts = dict(kv.split("=") for kv in line.split("|"))
    return parts.get("BIND"), parts.get("WILD")


def test_bind_resolution():
    cases = [
        # (env_extra, expected_host, expected_wild_unauthorized, name)
        ({}, "127.0.0.1", "False", "未设置 → 默认本机 127.0.0.1"),
        ({"API_GATEWAY_BIND": ""}, "127.0.0.1", "False", "空串 → 回退本机（防 INADDR_ANY 意外 wildcard）"),
        ({"API_GATEWAY_BIND": "   "}, "127.0.0.1", "False", "纯空白 → 回退本机"),
        ({"API_GATEWAY_BIND": "0.0.0.0"}, "0.0.0.0", "True", "0.0.0.0 未授权 → wildcard 拒绝标志"),
        ({"API_GATEWAY_BIND": "::"}, "::", "True", ":: 未授权 → wildcard 拒绝标志"),
        ({"API_GATEWAY_BIND": "0:0:0:0:0:0:0:0"}, "0:0:0:0:0:0:0:0", "True",
         "IPv6 全展开零地址 → wildcard 拒绝标志（Claude 评审发现项）"),
        ({"API_GATEWAY_BIND": "::ffff:0.0.0.0"}, "::ffff:0.0.0.0", "True",
         "IPv4 映射 IPv6 wildcard → 拒绝标志（Claude 评审发现项）"),
        ({"API_GATEWAY_BIND": "0.0.0.0", "API_GATEWAY_ALLOW_WILDCARD": "1"},
         "0.0.0.0", "False", "0.0.0.0 + 显式授权 → 允许"),
        ({"API_GATEWAY_BIND": "0.0.0.0", "API_GATEWAY_ALLOW_WILDCARD": "true"},
         "0.0.0.0", "True", "ALLOW_WILDCARD=非\"1\"真值 → 仍拒绝（严格白名单）"),
        ({"API_GATEWAY_BIND": "192.168.1.134"}, "192.168.1.134", "False", "具体 LAN IP → 正常解析"),
        ({"API_GATEWAY_BIND": "localhost"}, "localhost", "False", "localhost → 正常解析"),
    ]
    out = []
    for env_extra, exp_host, exp_wild, name in cases:
        try:
            host, wild = _probe(env_extra)
            ok = host == exp_host and wild == exp_wild
            detail = "host=%s wild=%s（期望 %s/%s）" % (host, wild, exp_host, exp_wild)
            out.append(Result(name, Result.PASS if ok else Result.FAIL, detail))
        except Exception as e:  # noqa: BLE001
            out.append(Result(name, Result.FAIL, "异常: %s" % e))
    return out


def run_all():
    print()
    print("===== 绑定地址 fail-closed 单测（R2 P1）=====")
    out = test_bind_resolution()
    for r in out:
        print(" ", r)
    return out


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r.status == Result.PASS)
    failed = sum(1 for r in results if r.status == Result.FAIL)
    print()
    print("BIND fail-closed: %d/%d 通过" % (passed, len(results)))
    sys.exit(1 if failed else 0)
