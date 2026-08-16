# -*- coding: utf-8 -*-
"""
心跳上报模块 —— 让中央平台（:8000）看到本网关在线。

- 启动时注册：POST  http://<central>/api/gateways
- 每 HEARTBEAT_INTERVAL 秒上报：POST /api/gateways/<gid>/heartbeat
- central 不可达时静默降级（不阻塞网关本身），可设置 CENTRAL_URL 关闭（空字符串）。

用法：
    from heartbeat import start_heartbeat
    start_heartbeat(gateway_id="search_gateway", name="AI 搜索网关",
                    icon="🔍", description="...", port=3000)
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request

CENTRAL_URL = os.environ.get("CENTRAL_URL", "http://127.0.0.1:8000").rstrip("/")
HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", "30"))

_registered = False
_lock = threading.Lock()


def _post(path, payload=None):
    """POST JSON 到 central；失败静默（返回 False）。"""
    if not CENTRAL_URL:
        return False
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        CENTRAL_URL + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
        return True
    except Exception:  # noqa: BLE001
        return False


def register(gateway_id, name, icon, description, port):
    """注册网关（幂等：已注册则直接上报心跳更新 last_seen）。"""
    global _registered
    if _registered:
        return
    ok = _post("/api/gateways", {
        "id": gateway_id,
        "name": name,
        "icon": icon,
        "description": description,
        "port": port,
    })
    if not ok:
        # 可能已注册（重复启动）→ 用 heartbeat 兜底
        _post(f"/api/gateways/{gateway_id}/heartbeat", {})
    _registered = True


def start_heartbeat(gateway_id, name, icon="🔗", description="", port=3000):
    """启动注册 + 心跳线程。返回线程对象。"""
    register(gateway_id, name, icon, description, port)

    def _run():
        while True:
            time.sleep(HEARTBEAT_INTERVAL)
            _post(f"/api/gateways/{gateway_id}/heartbeat", {})

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t
