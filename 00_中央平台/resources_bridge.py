# -*- coding: utf-8 -*-
"""
ai-resource-hub 公开数据桥代理（子项目①雏形）
================================================
链路: 飞书表 → 数据桥构建 → GitHub Pages → 门户 /api/resources

数据源优先级:
  1. 线上 GitHub Pages（https://201650545.github.io/ai-resource-hub）
  2. 本地 public/ 产物原子回退（本地 D:/项目/ai-resource-hub/public）

回退策略: 全有或全无——3 个文件（index/capabilities/instances）任一拉取失败，
即整体回退本地，避免混搭不同 build_id 的 index 与 capabilities。

缓存: 进程内模块级 TTL 缓存（300s），dashbboard 反复切 Tab/点刷新不打爆 GitHub Pages。
雏形只做「读」，不做任何写；数据桥公开产物无凭证。

依赖: pip install httpx
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

REMOTE_BASE = "https://201650545.github.io/ai-resource-hub"
FILES = ["index.json", "capabilities.json", "instances.json"]
LOCAL_DIR = Path(__file__).parent.parent / "ai-resource-hub" / "public"  # D:\项目\ai-resource-hub\public
CACHE_TTL = 300  # 秒

_CACHE = {"ts": 0.0, "data": None}


def _load_local():
    """读取本地 public/ 产物，缺失或解析失败返回 None（全有或全无由调用方判断）。"""
    out = {}
    for name in FILES:
        try:
            with open(LOCAL_DIR / name, "r", encoding="utf-8") as f:
                out[name] = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            out[name] = None
    return out


async def _fetch_remote():
    """并发拉取线上 3 个 JSON，失败项置 None。"""
    async with httpx.AsyncClient(timeout=httpx.Timeout(8.0), follow_redirects=True) as client:
        async def _get(name):
            try:
                r = await client.get(f"{REMOTE_BASE}/{name}")
                return (name, r.json()) if r.status_code == 200 else (name, None)
            except Exception:  # noqa: BLE001 —— 网络/解析失败统一按缺失处理
                return (name, None)
        return dict(await asyncio.gather(*(_get(name) for name in FILES)))


def _is_fresh(index):
    """由 generated_at 对照 stale_after_hours 判断新鲜度；解析失败返回 None（前端显示未知）。"""
    try:
        gen = datetime.fromisoformat(index.get("generated_at", ""))
        hours = float(index.get("freshness", {}).get("stale_after_hours", 48))
        age = (datetime.now(timezone.utc) - gen.astimezone(timezone.utc)).total_seconds()
        return age <= hours * 3600  # True=新鲜 False=已陈旧 None=未知
    except Exception:  # noqa: BLE001
        return None


def _aggregate(index, caps, insts, source):
    return {
        "ok": True,
        "source": source,  # "remote" | "local"
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "meta": {
            "site": index.get("site", ""),
            "repo": index.get("repo", ""),
            "bridge_version": index.get("bridge_version"),
            "build_id": index.get("build_id"),
            "generated_at": index.get("generated_at", ""),
            "stale_after_hours": index.get("freshness", {}).get("stale_after_hours"),
            "fresh": _is_fresh(index),  # True=新鲜 False=已陈旧 None=未知
            "note": index.get("note", ""),
        },
        "counts": {"capabilities": len(caps or []), "instances": len(insts or [])},
        "capabilities": caps or [],
        "instances": insts or [],
    }


async def get_resources(source="auto"):
    """返回聚合后的资源清单。

    source:
      - auto   （默认）线上优先 + 300s 缓存，线上不可用回退本地
      - remote （强制线上，不走缓存；验证/切换钩子）
      - local  （强制本地；验证回退路径）
    """
    if source == "remote":
        files = await _fetch_remote()
        if all(files.values()):
            return _aggregate(files["index.json"], files["capabilities.json"], files["instances.json"], "remote")
        return {"ok": False, "error": "远程数据桥不可用", "source": "remote"}

    if source == "local":
        files = _load_local()
        if all(files.values()):
            return _aggregate(files["index.json"], files["capabilities.json"], files["instances.json"], "local")
        return {"ok": False, "error": "本地 public 产物缺失", "source": "local"}

    # auto
    if _CACHE["data"] and time.time() - _CACHE["ts"] < CACHE_TTL:
        return _CACHE["data"]

    files = await _fetch_remote()
    if all(files.values()):
        data = _aggregate(files["index.json"], files["capabilities.json"], files["instances.json"], "remote")
        _CACHE["ts"], _CACHE["data"] = time.time(), data
        return data

    # 原子回退本地
    files = _load_local()
    if all(files.values()):
        return _aggregate(files["index.json"], files["capabilities.json"], files["instances.json"], "local")
    return {"ok": False, "error": "远程与本地数据桥均不可用", "source": "auto"}
