# -*- coding: utf-8 -*-
"""
ai-resource-hub 公开数据桥代理（子项目①雏形）
================================================
链路: 飞书表 → 数据桥构建 → GitHub Pages → 门户 /api/resources

数据源优先级:
  1. 线上 GitHub Pages（https://201650545.github.io/ai-resource-hub）
  2. 本地 public/ 产物原子回退（本地 D:/项目/ai-resource-hub/public）

协议（方案书 v2）: manifest.json 提交点。
  - 数据桥发布顺序: 先写数据文件、最后写 manifest；manifest 声明各文件字节 sha256。
  - 门户拉取: 读 manifest → 对每个文件「原始字节」算 sha256 逐项比对 → 全匹配 且
    index.build_id == manifest.build_id 才接受；任一失败/缺失/结构非法 → 整体回退本地
    （fail-closed，杜绝跨 build 混搭）。无 manifest 即失败（硬切换，不降级双读 index）。
  - 本地回退: 本地有 manifest 则同样校验；本地无 manifest 时过渡期信任（三个月后删除该分支）。

缓存: 进程内模块级 TTL（remote 成功 300s / local 回退 60s）+ single-flight 防击穿；
命中缓存时 fresh 按当前时刻重算，不随缓存固化。Dashboard 反复切 Tab/点刷新不打爆 GitHub Pages。
雏形只做「读」，不做任何写；数据桥公开产物无凭证。

依赖: pip install httpx
"""

import asyncio
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

REMOTE_BASE = "https://201650545.github.io/ai-resource-hub"
MANIFEST = "manifest.json"
# 哈希校验目标：4 个产物全校验（含 schema），与 manifest.files 声明一致
DATA_FILES = ["index.json", "capabilities.json", "instances.json", "schema.json"]


def _resolve_local_dir():
    """定位本地 ai-resource-hub/public 产物目录。

    候选顺序（首个存在的目录即采用）：
      1. 环境变量 AIHUB_RESOURCE_PUBLIC 显式指定（CI / 自定义布局覆盖）
      2. 与 ai-hub 仓库同级的 ai-resource-hub/public
      3. 旧布局（历史环境兼容）
    兜底：全部不存在时返回候选 2（_load_local 按目录缺失整体回退，行为与缺文件一致）。
    """
    env = os.environ.get("AIHUB_RESOURCE_PUBLIC")
    if env:
        return Path(env)
    hub_root = Path(__file__).resolve().parent.parent.parent  # ai-hub 仓库的上级
    candidates = [
        hub_root / "ai-resource-hub" / "public",
        Path("D:/项目/ai-resource-hub/public"),
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


LOCAL_DIR = _resolve_local_dir()
CACHE_TTL = 300  # 秒 —— 远程成功缓存
CACHE_TTL_LOCAL = 60  # 秒 —— 本地回退短缓存（防故障期反复打远端）

_CACHE = {"ts": 0.0, "data": None, "ttl": CACHE_TTL}
_CACHE_LOCK = asyncio.Lock()  # single-flight：并发 auto 请求只拉一次远端


def _load_local():
    """读取本地 public/ 产物（原始字节口径 + 本地 manifest 校验）。

    本地有 manifest：按字节 sha256 逐文件比对，不一致置 None（全有或全无由调用方判断）。
    本地无 manifest：过渡期信任（三个月后删除该宽容分支）。
    """
    out = {}
    manifest = None
    m_path = LOCAL_DIR / MANIFEST
    if m_path.exists():
        try:
            manifest = json.loads(m_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {n: None for n in DATA_FILES}  # manifest 存在但不可解析 → 不可信
    for name in DATA_FILES:
        try:
            raw = (LOCAL_DIR / name).read_bytes()
        except OSError:
            out[name] = None
            continue
        if manifest is not None:
            declared = (manifest.get("files") or {}).get(name, {}).get("sha256")
            if not declared or hashlib.sha256(raw).hexdigest() != declared:
                out[name] = None
                continue
        try:
            out[name] = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
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


def _failed_files():
    """fail-closed 的返回：全部置 None，触发调用方回退。"""
    return {name: None for name in DATA_FILES}


async def _fetch_remote():
    """并发拉取线上产物，按 manifest 校验「四文件同属一个 build」（fail-closed）。

    流程：拉 manifest → 并发拉 4 数据文件 → 对每个文件「原始字节」(r.content) 算 sha256
    与 manifest.files 逐项比对 → 全部匹配 且 index.build_id == manifest.build_id 才接受。
    任一失败/缺失/结构非法 → 返回全 None，由调用方回退本地。无 manifest 即失败
    （硬切换，不降级双读 index）。哈希的是原始字节而非 r.json()，两端口径一致。
    """
    async with httpx.AsyncClient(timeout=httpx.Timeout(8.0), follow_redirects=True) as client:
        async def _get(name):
            try:
                r = await client.get(f"{REMOTE_BASE}/{name}")
                return r if r.status_code == 200 else None
            except Exception:  # noqa: BLE001 —— 网络失败统一按缺失处理
                return None

        m_resp = await _get(MANIFEST)
        if m_resp is None:
            return _failed_files()  # 无 manifest → fail-closed
        try:
            manifest = m_resp.json()
        except Exception:  # noqa: BLE001
            return _failed_files()
        if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
            return _failed_files()  # manifest 结构非法 → fail-closed

        resps = await asyncio.gather(*[_get(f) for f in DATA_FILES])
        files = {}
        for name, resp in zip(DATA_FILES, resps):
            if resp is None:
                return _failed_files()
            body = resp.content  # 原始字节（勿用 r.json()——哈希口径必须同字节）
            declared = (manifest["files"].get(name) or {}).get("sha256")
            if not declared or hashlib.sha256(body).hexdigest() != declared:
                return _failed_files()  # 哈希不匹配（混搭/篡改）→ fail-closed
            try:
                files[name] = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return _failed_files()

        # 纵深防御：build_id 与 manifest 一致
        if not isinstance(files["index.json"], dict) \
                or files["index.json"].get("build_id") != manifest.get("build_id"):
            return _failed_files()
        if not _validate_files(files):
            return _failed_files()
        return files


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
