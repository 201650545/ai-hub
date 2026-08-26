#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网关渠道配置 → Cherry Studio 单向同步。

读取网关渠道配置（channels.json + unified_models.json + channel_models.json），
把渠道/密钥/模型写入 Cherry Studio SQLite（user_provider / user_model）。

网关是唯一数据源；Cherry Studio 只做接收。只 upsert 不删除，保留 Cherry Studio 里
用户手动添加的其它模型。

两种用法:
  CLI:  python sync_cherry.py [--dry-run]
  模块: from sync_cherry import run_sync; run_sync()   # 供 api_gateway 自动触发
"""
import json
import os
import sqlite3
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import channels  # noqa: E402

CHERRY_DB = os.path.expanduser(r"~\AppData\Roaming\CherryStudio\Data\cherrystudio.sqlite")

# 网关渠道 id → Cherry Studio provider_id 映射。
# UUID 型 provider 是用户手动创建的（ID 稳定）；预设型直接用预设 id。
# 未列出的渠道：以网关渠道 id 作为 Cherry Studio provider_id 新建。
CHERRY_MAP = {
    "openrouter": "openrouter",
    "opencode": "opencode",
    "modelscope": "modelscope",
    "sensetime": "b5586a30-eb6b-49a2-a982-2f737b0668e3",
    "agnes": "1659d51f-e6f4-4d84-b78d-5e3c345e170d",
    "zscc": "13e36358-c0ba-4318-a121-8c3f0505e2d8",
    "xiaohongshu": "3abed275-3184-4e45-8f00-9f29c20ab988",
    "zenmux": "e13120ce-0096-493b-85dc-4fb73666d5c6",
    "bai": "3f3af7c6-fb14-4c78-a272-b5088360a391",
    "gmi": "778676a0-f4b4-479f-b757-ea9279978d8f",
    "groq": "groq",
    "cerebras": "cerebras",
    "ark": "ark",
    "deepseek": "deepseek",
    "dashscope": "dashscope",
    "siliconflow": "silicon",
    # zhipu_coding 不映射到现有 zhipu provider（会覆盖其普通端点 /api/paas/v4，
    # 导致原有免费模型 glm-4.5-flash 等走 Coding 端点失效）。独立新建 provider。
}


def cherry_provider_id(cid):
    return CHERRY_MAP.get(cid, cid)


def _gen_order_key(cur):
    """生成不冲突的 order_key（Cherry Studio 排序用，base62 风格字符串）。"""
    used = {r[0] for r in cur.execute("SELECT order_key FROM user_provider WHERE order_key IS NOT NULL")}
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    for a in chars:
        for b in chars:
            k = "Z" + a + b
            if k not in used:
                return k
    return "Z" + str(uuid.uuid4().hex[:6])


def upsert_provider(cur, pid, name, base_url, key, enabled, now):
    endpoint = json.dumps({"openai-chat-completions": {"baseUrl": base_url}}, ensure_ascii=False)
    keys = json.dumps([{"id": str(uuid.uuid4()), "key": key, "isEnabled": True}], ensure_ascii=False)
    auth = json.dumps({"type": "api-key"}, ensure_ascii=False)
    exists = cur.execute("SELECT 1 FROM user_provider WHERE provider_id=?", (pid,)).fetchone()
    if exists:
        cur.execute(
            """UPDATE user_provider SET
               name=?, endpoint_configs=?, api_keys=?, auth_config=?, is_enabled=?, updated_at=?
               WHERE provider_id=?""",
            (name, endpoint, keys, auth, enabled, now, pid),
        )
    else:
        cur.execute(
            """INSERT INTO user_provider
               (provider_id, name, endpoint_configs, api_keys, auth_config, is_enabled,
                order_key, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, name, endpoint, keys, auth, enabled, _gen_order_key(cur), now, now),
        )


def upsert_model(cur, pid, model_id, display_name, group, enabled, now):
    mid = f"{pid}::{model_id}"
    exists = cur.execute("SELECT 1 FROM user_model WHERE id=?", (mid,)).fetchone()
    if exists:
        cur.execute(
            """UPDATE user_model SET
               name=?, "group"=?, is_enabled=?, updated_at=?
               WHERE id=?""",
            (display_name, group, enabled, now, mid),
        )
    else:
        cur.execute(
            """INSERT INTO user_model
               (id, provider_id, model_id, name, "group", capabilities, supports_streaming,
                is_enabled, is_hidden, is_deprecated, order_key, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (mid, pid, model_id, display_name, group, "[]", 1,
             enabled, 0, 0, _gen_order_key(cur), now, now),
        )


def run_sync(dry=False):
    """执行同步，返回结果 dict（供 CLI 与 api_gateway 共用）。"""
    now = int(time.time() * 1000)
    hidden = set(channels.get_hidden_channels())
    sel_map = channels.load_channel_models()

    con = sqlite3.connect(CHERRY_DB)
    cur = con.cursor()

    synced_providers = []
    synced_models = []

    # ---- 1. 同步渠道 provider + 渠道模型 ----
    for cid in channels.CHANNELS:
        if cid in hidden:
            continue
        ch = channels.CHANNELS[cid]
        key = channels.get_key(cid)
        if not key:
            continue
        pid = cherry_provider_id(cid)
        base_url = ch.get("base_url", "")
        name = ch.get("name", cid)
        enabled = 1 if channels.get_channel_enabled(cid) else 0

        if not dry:
            upsert_provider(cur, pid, name, base_url, key, enabled, now)
        synced_providers.append((cid, pid, name, enabled))

        # 渠道模型（按 channel_models.json 已选列表过滤，未配置时用全量 models）
        models = ch.get("models") or []
        sel = (sel_map.get(cid) or {}).get("selected")
        if isinstance(sel, list) and sel:
            sset = set(sel)
            models = [m for m in models if m in sset]
        for m in models:
            if not dry:
                upsert_model(cur, pid, m, m, cid, enabled, now)
            synced_models.append((pid, m, cid))

    # ---- 2. 统一模型组不直接同步为模型名 ----
    # 统一模型名（如 fast / deepseek-v4-flash）是网关层抽象，各成员渠道的上游真实模型名不同
    # （如 sensetime 上游是 sensenova-6.8-flash-lite）。直接写统一名会导致 Cherry Studio
    # 调用错误模型。渠道真实模型已在上一步按 channel_models.json 已选列表同步。
    # 仅当统一名与某渠道上游名一致时，该模型已作为渠道模型被同步（如 glm-5.3-flash）。

    if not dry:
        con.commit()
    con.close()

    return {
        "dry": dry,
        "providers": synced_providers,
        "models": synced_models,
    }


def main():
    dry = "--dry-run" in sys.argv
    res = run_sync(dry=dry)
    print(f"模式: {'DRY-RUN 预览' if dry else '实际同步'}")
    print(f"同步渠道 {len(res['providers'])} 个:")
    for cid, pid, name, enabled in res["providers"]:
        print(f"  [{cid}] -> Cherry provider [{pid}] {name} enabled={enabled}")
    print(f"同步模型 {len(res['models'])} 条:")
    for pid, m, cid in res["models"]:
        print(f"  {pid}::{m}  (来自 {cid})")


if __name__ == "__main__":
    main()
