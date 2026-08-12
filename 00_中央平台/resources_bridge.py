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

缓存: 进程内模块级 TTL（remote 成功 300s / local 回退 60s）+ single-flight 防击穿；
命中缓存时 fresh 按当前时刻重算，不随缓存固化。Dashboard 反复切 Tab/点刷新不打爆 GitHub Pages。
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
CACHE_TTL = 300  # 秒 —— 远程成功缓存
CACHE_TTL_LOCAL = 60  # 秒 —— 本地回退短缓存（防故障期反复打远端）

_CACHE = {"ts": 0.0, "data": None, "ttl": CACHE_TTL}
_CACHE_LOCK = asyncio.Lock()  # single-flight：并发 auto 请求只拉一次远端


def _load_local():
    """读取本地 public/ 产物，缺失或解析失败返回 None（全有或全无由调用方判断）。"""
    out = {}
    for name in FILES:
        try:
            with open(LOCAL_DIR / name, "r", encoding="utf-8") as f:
                out[name] = json.load(f)
        except (OSError, json.JSONDecodeError):
            out[name] = None
    return out


def _validate_files(files):
    """最小结构校验：index 为 dict，capabilities/instances 为 list。

    返回 False 即回退，避免「JSON 合法但结构错」在后端 500 / 前端 .map() 才炸。
    显式 isinstance 也保证了合法的空数组([])不会被误判为拉取失败。
    """
    return (
        isinstance(files.get("index.json"), dict)
        and isinstance(files.get("capabilities.json"), list)
        and isinstance(files.get("instances.json"), list)
    )


async def _fetch_remote():
    """并发拉取线上 JSON，并保证三文件同属一个 build。

    双读 index 防 GitHub Pages 发布切换瞬间的跨 build 混搭：
      读 index A → 并发拉 capabilities/instances → 再读 index B，
    A/B 的 build_id 一致才接受；任一环节失败/异常返回全 None（由调用方回退）。
    """
    async with httpx.AsyncClient(timeout=httpx.Timeout(8.0), follow_redirects=True) as client:
        async def _get_json(name):
            try:
                r = await client.get(f"{REMOTE_BASE}/{name}")
                return r.json() if r.status_code == 200 else None
            except Exception:  # noqa: BLE001 —— 网络/解析失败统一按缺失处理
                return None

        failed = {"index.json": None, "capabilities.json": None, "instances.json": None}
        index_a = await _get_json("index.json")
        if not isinstance(index_a, dict):
            return failed
        caps, insts = await asyncio.gather(
            _get_json("capabilities.json"), _get_json("instances.json"))
        index_b = await _get_json("index.json")
        if not isinstance(index_b, dict) or index_a.get("build_id") != index_b.get("build_id"):
            return failed
        return {"index.json": index_a, "capabilities.json": caps, "instances.json": insts}


def _recompute_fresh(meta):
    """由 meta 的 generated_at/stale_after_hours 按当前时刻重算 fresh。

    无时区 / 未来时间（机器时钟错误）/ 解析失败 → 返回 None（前端显示未知）。
    """
    try:
        gen = datetime.fromisoformat(meta.get("generated_at", ""))
        if gen.tzinfo is None:
            return None  # 无时区无法正确换算，按未知处理
        age = (datetime.now(timezone.utc) - gen.astimezone(timezone.utc)).total_seconds()
        if age < 0:
            return None  # 未来时间（时钟错误）→ 未知
        hours = float(meta.get("stale_after_hours") or 48)
        return age <= hours * 3600  # True=新鲜 False=已陈旧 None=未知
    except Exception:  # noqa: BLE001
        return None


def _aggregate(index, caps, insts, source, fallback=False):
    meta = {
        "site": index.get("site", ""),
        "repo": index.get("repo", ""),
        "bridge_version": index.get("bridge_version"),
        "build_id": index.get("build_id"),
        "generated_at": index.get("generated_at", ""),
        "stale_after_hours": index.get("freshness", {}).get("stale_after_hours"),
        "note": index.get("note", ""),
    }
    meta["fresh"] = _recompute_fresh(meta)  # 构建时按当前时刻重算，不缓存死
    return {
        "ok": True,
        "source": source,  # "remote" | "local"
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "cache_hit": False,
        "fallback": fallback,
        "meta": meta,
        "counts": {"capabilities": len(caps or []), "instances": len(insts or [])},
        "capabilities": caps or [],
        "instances": insts or [],
    }


async def get_resources(source="auto"):
    """返回聚合后的资源清单。

    source:
      - auto   （默认）线上优先；remote 成功缓存 300s、local 回退缓存 60s；
               single-flight 防并发重复拉取；命中缓存时 fresh 按当前时刻重算
      - remote （强制线上，绕过缓存；验证/切换钩子）
      - local  （强制本地；验证回退路径）
    """
    if source == "remote":
        files = await _fetch_remote()
        if _validate_files(files):
            return _aggregate(files["index.json"], files["capabilities.json"], files["instances.json"], "remote")
        return {"ok": False, "error": "远程数据桥不可用或结构异常", "source": "remote"}

    if source == "local":
        files = _load_local()
        if _validate_files(files):
            return _aggregate(files["index.json"], files["capabilities.json"], files["instances.json"], "local", fallback=True)
        return {"ok": False, "error": "本地 public 产物缺失或结构异常", "source": "local"}

    # auto：single-flight + 双检缓存
    async with _CACHE_LOCK:
        if _CACHE["data"] and time.time() - _CACHE["ts"] < _CACHE["ttl"]:
            # 返回浅拷贝：fresh 按当前时刻重算、cache_hit 标记，但不能原地改缓存对象
            # （否则前一次请求已返回的同一 dict 会被后续命中请求污染）
            data = dict(_CACHE["data"])
            data["meta"] = dict(_CACHE["data"]["meta"])
            data["meta"]["fresh"] = _recompute_fresh(data["meta"])
            data["cache_hit"] = True
            return data

        files = await _fetch_remote()
        if _validate_files(files):
            data = _aggregate(files["index.json"], files["capabilities.json"], files["instances.json"], "remote")
            _CACHE["ts"], _CACHE["data"], _CACHE["ttl"] = time.time(), data, CACHE_TTL
            return data

        # 原子回退本地（短缓存）
        files = _load_local()
        if _validate_files(files):
            data = _aggregate(files["index.json"], files["capabilities.json"], files["instances.json"], "local", fallback=True)
            _CACHE["ts"], _CACHE["data"], _CACHE["ttl"] = time.time(), data, CACHE_TTL_LOCAL
            return data
        return {"ok": False, "error": "远程与本地数据桥均不可用", "source": "auto"}
