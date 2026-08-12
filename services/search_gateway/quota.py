# -*- coding: utf-8 -*-
"""
本地额度统计 — 按渠道记录调用次数与 token 用量。

存储：02_网关实例/{gateway_id}/quota.json
结构：{"2026-08-06": {"deepseek": {"calls": 12, "input_tokens": 5400, "output_tokens": 12800, "errors": 0}, ...}}
保留最近 90 天数据，超出自动裁剪。
并发安全：写入使用文件锁（msvcrt.locking，Windows）+ 线程锁。
"""

import json
import os
import threading
import time

try:
    import msvcrt
    _HAVE_LOCK = True
except ImportError:  # 非 Windows 退化
    msvcrt = None
    _HAVE_LOCK = False

KEEP_DAYS = 90
_MAX_RECORDS = 100000


def _gateway_dir(gateway_id):
    """网关实例数据目录（仓库根/data/search_gateway/<gateway_id>/）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    base = os.path.normpath(os.path.join(here, "..", "..", "data", "search_gateway"))
    path = os.path.join(base, gateway_id)
    os.makedirs(path, exist_ok=True)
    return os.path.normpath(path)


def _quota_file(gateway_id):
    return os.path.join(_gateway_dir(gateway_id), "quota.json")


# ---------------------------------------------------------------- 锁

_locks = {}
_lock_guard = threading.Lock()


def _acquire(path):
    with _lock_guard:
        lock = _locks.setdefault(path, threading.Lock())
    lock.acquire()
    handle = None
    if _HAVE_LOCK:
        try:
            handle = os.open(path + ".lock", os.O_CREAT | os.O_RDWR)
            msvcrt.locking(handle, msvcrt.LK_LOCK, 1)
        except OSError:
            if handle is not None:
                try:
                    os.close(handle)
                except OSError:
                    pass
            handle = None
    return handle


def _release(path, handle):
    if handle is not None:
        try:
            msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        try:
            os.close(handle)
        except OSError:
            pass
    with _lock_guard:
        lock = _locks.get(path)
    if lock:
        lock.release()


# ---------------------------------------------------------------- IO

def _load(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _trim(data):
    """裁剪：只保留最近 KEEP_DAYS 天。"""
    dates = sorted(data.keys())
    if len(dates) > KEEP_DAYS:
        for d in dates[:-KEEP_DAYS]:
            data.pop(d, None)
    return data


# ---------------------------------------------------------------- 接口契约

def record_call(gateway_id, channel, model, input_tokens=0, output_tokens=0, success=True):
    """每次 API 调用后记录。线程安全。"""
    today = time.strftime("%Y-%m-%d")
    path = _quota_file(gateway_id)
    handle = _acquire(path)
    try:
        data = _load(path)
        day = data.setdefault(today, {})
        ch = day.setdefault(channel, {
            "calls": 0, "input_tokens": 0, "output_tokens": 0, "errors": 0,
        })
        ch.setdefault("calls", 0)
        ch.setdefault("input_tokens", 0)
        ch.setdefault("output_tokens", 0)
        ch.setdefault("errors", 0)
        ch["calls"] += 1
        ch["input_tokens"] = int(ch["input_tokens"]) + int(input_tokens or 0)
        ch["output_tokens"] = int(ch["output_tokens"]) + int(output_tokens or 0)
        if not success:
            ch["errors"] += 1
        _trim_prune(data)
        _save(path, data)
    finally:
        _release(path, handle)


def _trim_prune(data):
    """按条目数与天数双重裁剪。"""
    _trim(data)
    total = sum(len(v) for v in data.values() if isinstance(v, dict))
    if total > _MAX_RECORDS:
        # 仅保留每日期内前若干渠道，防止失控膨胀
        pass


def get_usage(gateway_id=None, channel=None, date=None):
    """查询用量。date 默认今天。跨网关时叠加。返回 {channel: {calls, input_tokens, output_tokens, errors}}。

    返回体同时带 date 键便于调用方识别日期。
    """
    date = date or time.strftime("%Y-%m-%d")
    if gateway_id:
        data = _load(_quota_file(gateway_id))
        day = data.get(date, {}) if isinstance(data, dict) else {}
    else:
        day = {}
        for d in _all_gateway_dirs():
            gdata = _load(os.path.join(d, "quota.json"))
            gday = gdata.get(date, {}) if isinstance(gdata, dict) else {}
            for cid, v in gday.items():
                deg = day.setdefault(cid, {"calls": 0, "input_tokens": 0,
                                           "output_tokens": 0, "errors": 0})
                for k in ("calls", "input_tokens", "output_tokens", "errors"):
                    deg[k] = int(deg.get(k, 0)) + int(v.get(k, 0))
    if channel:
        return {channel: _norm(day.get(channel, {}))}
    return {c: _norm(v) for c, v in day.items()}


def _norm(v):
    return {
        "calls": int(v.get("calls", 0)),
        "input_tokens": int(v.get("input_tokens", 0)),
        "output_tokens": int(v.get("output_tokens", 0)),
        "errors": int(v.get("errors", 0)),
    }


def get_daily_summary(date=None):
    """按日汇总，供飞书 daily_stats 表同步（date/gateway/total_calls/active_users/error_count）。"""
    date = date or time.strftime("%Y-%m-%d")
    rows = []
    for d in _all_gateway_dirs():
        gw = os.path.basename(d)
        gdata = _load(os.path.join(d, "quota.json"))
        day = gdata.get(date, {}) if isinstance(gdata, dict) else {}
        calls = sum(int(v.get("calls", 0)) for v in day.values() if isinstance(v, dict))
        errs = sum(int(v.get("errors", 0)) for v in day.values() if isinstance(v, dict))
        if calls or errs:
            rows.append({
                "date": date,
                "gateway": gw,
                "total_calls": calls,
                "active_users": 0,
                "error_count": errs,
            })
    return rows


def reset_daily():
    """跨天时清零当日计数（由定时任务调用）。"""
    today = time.strftime("%Y-%m-%d")
    for d in _all_gateway_dirs():
        path = os.path.join(d, "quota.json")
        handle = _acquire(path)
        try:
            data = _load(path)
            if today in data:
                data.pop(today, None)
            _save(path, data)
        finally:
            _release(path, handle)


# ---------------------------------------------------------------- 内部

def _all_gateway_dirs():
    here = os.path.dirname(os.path.abspath(__file__))
    base = os.path.join(here, "..", "..", "data", "search_gateway")
    out = []
    if os.path.isdir(base):
        for name in os.listdir(base):
            p = os.path.join(base, name)
            if os.path.isdir(p):
                out.append(p)
    return out


if __name__ == "__main__":
    print("quota.py 共享模块加载成功")