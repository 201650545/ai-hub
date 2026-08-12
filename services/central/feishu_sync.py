# -*- coding: utf-8 -*-
"""
飞书多维表格同步模块 (task_003)
定时将本地 JSON 数据同步到飞书多维表格：gateways / api_channels / conversations / daily_stats

独占写入声明（P2-3）：本模块为 AI Hub 网关数据 4 表（gateways/api_channels/
conversations/daily_stats）的**唯一写入方**。英语教学流水线 feishu_sync.py 写的是
另一张飞书 Base（英语教学课程进度看板），与本模块无交集；双写分工见 TOPOLOGY.md。

依赖: pip install httpx
认证:
  - 环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET
  - 配置 config/feishu.json（app_token 与 4 张表 table_id）

设计要点（增量同步 / 避免重复）:
  - 查询飞书表内现有记录 → 按「业务主键」去重 → 命中则 update，未命中则 create/batch_create。
  - 各表主键:
      gateways     -> name
      api_channels -> gateway + "|" + channel
      conversations-> gateway + "|" + engine + "|" + created_at
      daily_stats  -> date + "|" + gateway
"""

import json
import os
import time
from pathlib import Path

import httpx

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
# 网关运行数据（monorepo 数据分离：仓库根/data/search_gateway/）
GATEWAYS_DIR = Path(__file__).parent.parent.parent / "data" / "search_gateway"

FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
FEISHU_CONFIG = CONFIG_DIR / "feishu.json"
API = "https://open.feishu.cn/open-apis"


def load_feishu_config():
    try:
        with open(FEISHU_CONFIG, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"app_token": "", "tables": {
            "gateways": "", "api_channels": "",
            "conversations": "", "daily_stats": ""}}


async def get_tenant_token():
    """获取飞书 tenant_access_token。"""
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        return None
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET})
        if r.status_code == 200:
            return r.json().get("tenant_access_token")
    return None


# ---------------------------------------------------------------- 本地数据源

def _load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else {}


def _gw_dirs():
    if not GATEWAYS_DIR.exists():
        return []
    return [gw for gw in GATEWAYS_DIR.iterdir() if gw.is_dir()]


def read_local_gateways():
    raw = _load_json(CONFIG_DIR / "gateways.json").get("gateways", {})
    return [{
        "name": gw.get("name", gid),
        "port": gw.get("port", 0),
        "status": gw.get("status", "offline"),
        "url": gw.get("url", ""),
        "created_at": gw.get("created_at", ""),
        "last_seen": gw.get("last_seen", ""),
    } for gid, gw in raw.items()]


def read_local_channels():
    rows = []
    for gw in _gw_dirs():
        data = _load_json(gw / "channels.json").get("keys", {})
        for key, cid in data.items():
            rows.append({
                "gateway": gw.name,
                "channel": key,
                "key_prefix": (str(cid)[:6] + "…") if cid else "",
                "today_calls": 0,
                "quota_remaining": 0,
                "status": "active" if cid else "exhausted",
            })
    return rows


def read_local_conversations():
    rows = []
    for gw in _gw_dirs():
        data = _load_json(gw / "history.json")
        hist = data.get("history", []) if isinstance(data, dict) else (data or [])
        for item in hist:
            rows.append({
                "gateway": gw.name,
                "engine": item.get("engine", ""),
                "question": item.get("question", ""),
                "answer": item.get("answer", ""),
                "created_at": item.get("created_at", ""),
            })
    return rows


def read_local_daily_stats():
    gates = read_local_gateways()
    today = time.strftime("%Y-%m-%d")
    err = sum(1 for g in gates if g.get("status") == "error")
    return [{
        "date": today,
        "gateway": "ALL",
        "total_calls": len(read_local_conversations()),
        "active_users": 0,
        "error_count": err,
    }]


# ---------------------------------------------------------------- 飞书 Bitable 封装

def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _ts_ms(s):
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return int(time.mktime(time.strptime(s[:19], fmt)) * 1000)
        except ValueError:
            continue
    return None


def _feishu_fields(row):
    out = {}
    for k, v in row.items():
        if v is None:
            continue
        if isinstance(v, bool):
            out[k] = str(v)
        elif isinstance(v, (int, float)):
            out[k] = v
        elif k in ("date", "created_at", "last_seen"):
            ms = _ts_ms(v)
            out[k] = ms if ms is not None else str(v)
        else:
            out[k] = str(v)
    return out


async def _fetch_records(token, app_token, table_id):
    if not table_id:
        return [], "未配置 table_id"
    records, page_token = [], ""
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        while True:
            params = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            r = await client.get(
                f"{API}/bitable/v1/apps/{app_token}/tables/{table_id}/records",
                params=params, headers=_headers(token))
            if r.status_code != 200:
                return records, f"query {r.status_code}: {r.text[:200]}"
            data = r.json().get("data") or {}
            for rec in data.get("items", []):
                records.append((rec["record_id"], rec.get("fields", {})))
            if not data.get("has_more"):
                break
            page_token = data.get("page_token", "")
    return records, None


def _row_key(r, primary_fields):
    return "|".join(str(r.get(k, "")).strip() for k in primary_fields)


async def _sync_table(token, app_token, table_id, local_rows, primary_fields, table_name):
    if not table_id:
        return {"table": table_name, "status": "skip", "reason": "未配置 table_id"}

    existing, err = await _fetch_records(token, app_token, table_id)
    if err:
        return {"table": table_name, "status": "error", "reason": err}

    existing_map = {_row_key(f, primary_fields): rid for rid, f in existing}
    created, updated, skipped = 0, 0, 0
    to_create = []

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
        headers = _headers(token)
        for row in local_rows:
            kid = _row_key(row, primary_fields)
            if not kid:
                skipped += 1
                continue
            rid = existing_map.get(kid)
            if rid is None:
                to_create.append(row)
                created += 1
            else:
                r = await client.put(
                    f"{API}/bitable/v1/apps/{app_token}/tables/{table_id}/records/{rid}",
                    json={"fields": _feishu_fields(row)}, headers=headers)
                if r.status_code in (200, 201):
                    updated += 1
                else:
                    skipped += 1
        for i in range(0, len(to_create), 500):
            body = [{"fields": _feishu_fields(r)} for r in to_create[i:i + 500]]
            await client.post(
                f"{API}/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create",
                json={"records": body}, headers=headers)

    return {"table": table_name, "created": created, "updated": updated,
            "existing": len(existing), "skipped": skipped}


# ---------------------------------------------------------------- 各表同步

def _data_for(table):
    return {
        "gateways": read_local_gateways,
        "api_channels": read_local_channels,
        "conversations": read_local_conversations,
        "daily_stats": read_local_daily_stats,
    }[table]()


async def sync_all():
    cfg = load_feishu_config()
    token = await get_tenant_token()
    if not token:
        return {"error": "未配置飞书 APP_ID/SECRET"}

    app_token = cfg.get("app_token", "")
    tables = cfg.get("tables", {})
    specs = (("gateways", ["name"]),
             ("api_channels", ["gateway", "channel"]),
             ("conversations", ["gateway", "engine", "created_at"]),
             ("daily_stats", ["date", "gateway"]))

    results = {}
    for table, pkey in specs:
        tid = tables.get(table, "")
        results[table] = await _sync_table(token, app_token, tid,
                                           _data_for(table), pkey, table)
    return {"ok": True, "synced_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "results": results}


async def sync_gateways():
    cfg = load_feishu_config()
    token = await get_tenant_token()
    if not token:
        return {"error": "未配置飞书 APP_ID/SECRET"}
    return await _sync_table(token, cfg.get("app_token", ""),
                             cfg.get("tables", {}).get("gateways", ""),
                             _data_for("gateways"), ["name"], "gateways")


async def sync_channels():
    cfg = load_feishu_config()
    token = await get_tenant_token()
    if not token:
        return {"error": "未配置飞书 APP_ID/SECRET"}
    return await _sync_table(token, cfg.get("app_token", ""),
                             cfg.get("tables", {}).get("api_channels", ""),
                             _data_for("api_channels"), ["gateway", "channel"], "api_channels")


async def sync_conversations():
    cfg = load_feishu_config()
    token = await get_tenant_token()
    if not token:
        return {"error": "未配置飞书 APP_ID/SECRET"}
    return await _sync_table(token, cfg.get("app_token", ""),
                             cfg.get("tables", {}).get("conversations", ""),
                             _data_for("conversations"),
                             ["gateway", "engine", "created_at"], "conversations")


async def sync_daily_stats():
    cfg = load_feishu_config()
    token = await get_tenant_token()
    if not token:
        return {"error": "未配置飞书 APP_ID/SECRET"}
    return await _sync_table(token, cfg.get("app_token", ""),
                             cfg.get("tables", {}).get("daily_stats", ""),
                             _data_for("daily_stats"), ["date", "gateway"], "daily_stats")


def schedule_sync(interval_seconds=300, loop=None):
    """定时同步（每 N 秒）。供 server.py 在后台启动。"""
    import asyncio
    if loop is None:
        loop = asyncio.get_event_loop()

    async def _runner():
        while True:
            try:
                await sync_all()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(interval_seconds)

    loop.create_task(_runner())