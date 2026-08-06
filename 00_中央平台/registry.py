# -*- coding: utf-8 -*-
"""
网关注册/发现/监控模块
负责网关的生命周期管理：注册、心跳、健康检查、状态标记
"""

import json
import time
from pathlib import Path

CONFIG_DIR = Path(__file__).parent.parent / "config"
GATEWAYS_JSON = CONFIG_DIR / "gateways.json"


def load_gateways():
    """加载网关注册表。"""
    try:
        with open(GATEWAYS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"gateways": {}}


def save_gateways(data):
    """保存网关注册表。"""
    CONFIG_DIR.mkdir(exist_ok=True)
    with open(GATEWAYS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def register(gateway_id, name, port, url=None, icon="🔗", description=""):
    """注册新网关。"""
    data = load_gateways()
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    data["gateways"][gateway_id] = {
        "name": name,
        "icon": icon,
        "description": description,
        "port": port,
        "url": url or f"http://localhost:{port}",
        "status": "online",
        "created_at": now,
        "last_seen": now,
    }
    save_gateways(data)
    return gateway_id


def heartbeat(gateway_id):
    """更新网关心跳时间。"""
    data = load_gateways()
    if gateway_id in data["gateways"]:
        data["gateways"][gateway_id]["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        data["gateways"][gateway_id]["status"] = "online"
        save_gateways(data)
        return True
    return False


def mark_offline(gateway_id):
    """标记网关离线。"""
    data = load_gateways()
    if gateway_id in data["gateways"]:
        data["gateways"][gateway_id]["status"] = "offline"
        save_gateways(data)
        return True
    return False


def check_stale(timeout_seconds=300):
    """检查超时未心跳的网关，标记为离线。"""
    data = load_gateways()
    now = time.time()
    changed = False
    for gid, gw in data["gateways"].items():
        if gw.get("status") != "online":
            continue
        last_seen = gw.get("last_seen", "")
        if last_seen:
            try:
                last_ts = time.mktime(time.strptime(last_seen, "%Y-%m-%dT%H:%M:%S"))
                if now - last_ts > timeout_seconds:
                    data["gateways"][gid]["status"] = "offline"
                    changed = True
            except ValueError:
                pass
    if changed:
        save_gateways(data)
    return data


def list_all():
    """列出所有网关。"""
    return load_gateways().get("gateways", {})


def get(gateway_id):
    """获取单个网关信息。"""
    return load_gateways().get("gateways", {}).get(gateway_id)
