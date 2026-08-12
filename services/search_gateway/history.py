# -*- coding: utf-8 -*-
"""
对话历史管理 — JSON 持久化，供网关与中央平台共用。

存储：02_网关实例/{gateway_id}/history.json
结构：
{
  "conversations": {
    "<conv_id>": {
      "engine": "...", "created_at": "...",
      "turns": [{"id": 1, "role": "user|assistant", "content": "...", "created_at": "..."}]
    }
  }
}

并发安全：写入使用文件锁（msvcrt.locking，Windows），同进程内加线程锁兜底。
容量控制：单文件超过 10MB 时按月份归档为 history_YYYY-MM.json。
"""

import json
import os
import threading
import time

try:
    import msvcrt
    _HAVE_LOCK = True
except ImportError:  # 非 Windows 平台退化
    msvcrt = None
    _HAVE_LOCK = False

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10MB


# ---------------------------------------------------------------- 路径

def _gateway_dir(gateway_id):
    """定位网关实例数据目录（仓库根/data/search_gateway/<gateway_id>/）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    base = os.path.join(os.path.dirname(here), "data", "search_gateway")
    path = os.path.join(base, gateway_id)
    os.makedirs(path, exist_ok=True)
    return os.path.normpath(path)


def _history_file(gateway_id):
    return os.path.join(_gateway_dir(gateway_id), "history.json")


def _all_gateway_dirs():
    here = os.path.dirname(os.path.abspath(__file__))
    base = os.path.join(os.path.dirname(here), "data", "search_gateway")
    out = []
    if os.path.isdir(base):
        for name in os.listdir(base):
            p = os.path.join(base, name)
            if os.path.isdir(p):
                out.append(p)
    return out


# ---------------------------------------------------------------- 锁管理

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


# ---------------------------------------------------------------- 读写

def _load(path):
    if not os.path.exists(path):
        return {"conversations": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:  # noqa: BLE001
        return {"conversations": {}}
    if isinstance(data, dict) and "conversations" in data:
        return data
    return {"conversations": {}}


def _save(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        if os.path.getsize(path) > MAX_FILE_BYTES:
            _archive_month(path)
    except OSError:
        pass


def _archive_month(path):
    """当前文件超限：把既有会话按创建月份归档到 history_YYYY-MM.json。"""
    data = _load(path)
    conversations = data.get("conversations", {})
    if not conversations:
        return
    by_month = {}
    for conv_id, conv in conversations.items():
        month = (conv or {}).get("created_at", "")[:7] or time.strftime("%Y-%m")
        by_month.setdefault(month, {})[conv_id] = conv
    for month, convs in by_month.items():
        archive_path = os.path.join(os.path.dirname(path), f"history_{month}.json")
        arch = _load(archive_path)
        arch.setdefault("conversations", {}).update(convs)
        try:
            with open(archive_path, "w", encoding="utf-8") as f:
                json.dump(arch, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"conversations": {}}, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------- 接口契约

def save_turn(gateway_id, engine_id, conversation_id, role, content):
    """保存一轮对话（role=user/assistant），返回记录 dict（含 id 和 created_at）。"""
    role = role if role in ("user", "assistant") else "user"
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    path = _history_file(gateway_id)
    handle = _acquire(path)
    try:
        data = _load(path)
        conversations = data.setdefault("conversations", {})
        conv = conversations.get(conversation_id)
        if conv is None:
            conv = {"conversation_id": conversation_id, "engine": engine_id,
                    "created_at": now, "turns": []}
            conversations[conversation_id] = conv
        if "turns" not in conv:
            conv["turns"] = []
        conv.setdefault("engine", engine_id)
        existing_ids = {int(t.get("id", 0)) for t in conv["turns"] if isinstance(t, dict)}
        new_id = 1
        while new_id in existing_ids:
            new_id += 1
        record = {"id": new_id, "role": role, "content": content, "created_at": now}
        conv["turns"].append(record)
        _save(path, data)
        return record
    finally:
        _release(path, handle)


def get_conversation(gateway_id, conversation_id):
    """获取某对话的完整记录列表。"""
    path = _history_file(gateway_id)
    data = _load(path)
    conv = data.get("conversations", {}).get(conversation_id)
    if not conv:
        return []
    return conv.get("turns", [])


def list_conversations(gateway_id=None, engine_id=None, limit=50):
    """按网关/引擎筛选对话列表（不含 content 全文，只有摘要）。"""
    limit = max(1, int(limit or 50))
    paths = []
    if gateway_id:
        paths.append(_history_file(gateway_id))
    else:
        for d in _all_gateway_dirs():
            hp = os.path.join(d, "history.json")
            if os.path.exists(hp):
                paths.append(hp)
            for name in sorted(os.listdir(d)):
                if name.startswith("history_") and name.endswith(".json"):
                    paths.append(os.path.join(d, name))

    out, seen = [], set()
    for path in paths:
        data = _load(path)
        for conv_id, conv in data.get("conversations", {}).items():
            conv = conv or {}
            eng = conv.get("engine", "")
            if engine_id and eng != engine_id:
                continue
            key = (eng, conv_id)
            if key in seen:
                continue
            seen.add(key)
            turns = conv.get("turns", [])
            first_user = next((t.get("content") for t in turns
                               if isinstance(t, dict) and t.get("role") == "user"), "")
            out.append({
                "conversation_id": conv_id,
                "engine": eng,
                "created_at": conv.get("created_at", ""),
                "turns": len(turns),
                "last_content": (first_user or "")[:120],
            })
    out.sort(key=lambda c: c.get("created_at", ""), reverse=True)
    return out[:limit]


def delete_conversation(gateway_id, conversation_id):
    """删除对话。"""
    path = _history_file(gateway_id)
    handle = _acquire(path)
    try:
        data = _load(path)
        conversations = data.get("conversations", {})
        if conversation_id in conversations:
            del conversations[conversation_id]
            _save(path, data)
            return True
        return False
    finally:
        _release(path, handle)


def export_daily_stats(date=None):
    """导出指定日期（默认今天）各网关/引擎的对话数统计，供飞书 daily_stats 同步。

    输出字段与 ARCHITECTURE.md 的 daily_stats 表对齐：date/gateway/total_calls/active_users/error_count。
    """
    date = date or time.strftime("%Y-%m-%d")
    rows = []
    for d in _all_gateway_dirs():
        gw_id = os.path.basename(d)
        data = _load(os.path.join(d, "history.json"))
        date_turns = 0
        for conv in data.get("conversations", {}).values():
            conv = conv or {}
            if str(conv.get("created_at", "")).startswith(date):
                date_turns += len(conv.get("turns", [])) // 2
        if date_turns:
            rows.append({
                "date": date,
                "gateway": gw_id,
                "total_calls": date_turns,
                "active_users": 1,
                "error_count": 0,
            })
    return rows


if __name__ == "__main__":
    print("history.py 共享模块加载成功")