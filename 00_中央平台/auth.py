# -*- coding: utf-8 -*-
"""
简单 Token 认证模块
适用于 ≤50 人局域网共享场景
"""

import json
import secrets
import time
from pathlib import Path

CONFIG_DIR = Path(__file__).parent.parent / "config"
AUTH_JSON = CONFIG_DIR / "auth.json"


def _load():
    try:
        with open(AUTH_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"tokens": {}, "admin_token": ""}


def _save(data):
    CONFIG_DIR.mkdir(exist_ok=True)
    with open(AUTH_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def init_admin_token():
    """初始化管理员 token（仅首次）。"""
    data = _load()
    if not data.get("admin_token"):
        data["admin_token"] = secrets.token_urlsafe(32)
        _save(data)
    return data["admin_token"]


def generate_token(user_name="default"):
    """为用户生成访问 token。"""
    data = _load()
    token = secrets.token_urlsafe(16)
    data["tokens"][token] = {
        "user": user_name,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "active": True,
    }
    _save(data)
    return token


def verify_token(token):
    """验证 token 是否有效。"""
    data = _load()
    if token == data.get("admin_token"):
        return {"valid": True, "user": "admin", "role": "admin"}
    info = data.get("tokens", {}).get(token)
    if info and info.get("active"):
        return {"valid": True, "user": info["user"], "role": "user"}
    return {"valid": False}


def revoke_token(token):
    """吊销 token。"""
    data = _load()
    if token in data.get("tokens", {}):
        data["tokens"][token]["active"] = False
        _save(data)
        return True
    return False


def list_tokens():
    """列出所有 token（脱敏）。"""
    data = _load()
    result = []
    for tok, info in data.get("tokens", {}).items():
        result.append({
            "token_prefix": tok[:8] + "...",
            "user": info["user"],
            "active": info["active"],
            "created_at": info["created_at"],
        })
    return result
