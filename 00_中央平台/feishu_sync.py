# -*- coding: utf-8 -*-
"""
飞书多维表格同步模块
定时将本地 JSON 数据同步到飞书多维表格

依赖: pip install httpx
认证: 环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET
"""

import json
import os
import time
from pathlib import Path

import httpx

CONFIG_DIR = Path(__file__).parent.parent / "config"
GATEWAYS_DIR = Path(__file__).parent.parent / "02_网关实例"

FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")

# 飞书多维表格配置（app_token 和 table_id 需手动创建后填入）
FEISHU_CONFIG = CONFIG_DIR / "feishu.json"


def load_feishu_config():
    """加载飞书配置。"""
    try:
        with open(FEISHU_CONFIG, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "app_token": "",
            "tables": {
                "gateways": "",
                "api_channels": "",
                "conversations": "",
                "daily_stats": "",
            }
        }


async def get_tenant_token():
    """获取飞书 tenant_access_token。"""
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        return None
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
        )
        if r.status_code == 200:
            return r.json().get("tenant_access_token")
    return None


async def sync_gateways():
    """同步网关注册表到飞书。"""
    # TODO: 实现网关数据同步
    pass


async def sync_channels():
    """同步 API 渠道统计到飞书。"""
    # TODO: 实现渠道数据同步
    pass


async def sync_conversations():
    """同步对话历史到飞书。"""
    # TODO: 实现对话数据同步
    pass


async def sync_all():
    """同步所有数据到飞书。"""
    token = await get_tenant_token()
    if not token:
        return {"error": "未配置飞书 APP_ID/SECRET"}
    await sync_gateways()
    await sync_channels()
    await sync_conversations()
    return {"ok": True, "synced_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
