# -*- coding: utf-8 -*-
"""渠道限流准入闸门（v2，task_045）—— 原子 admission gate。

v1（task_044）是纯台账：入口 hit() 打点 + ledger() 观察。GPT Extended 评审指出三个核心修正：
1. 「先 ledger() 查再 hit()」有并发穿透（10 线程同读到 94% 就全打进去）→ 改成 try_acquire()：
   同一把锁内 清窗口→判断→预占，路由关键路径调用；观察接口不再参与决策。
2. 记账按「真实 HTTP attempt」——key 池轮换一圈是 N 次上游请求，不是 1 次。
3. 429 不反推永久上限（容易把偶发上游拥堵学成错误数字），只做 blocked_until 熔断：
   Retry-After 优先，否则指数退避 15/30/60/120/300s，成功一次清零。

滞后区间用整数门槛：trip_at=ceil(limit*0.95) 触发跳过、resume_at=floor(limit*0.85) 才恢复，
不用固定冷却——滑动窗口自己会说容量什么时候释放。事件只在状态翻转时记一条，
skipped 走累计计数，避免高流量刷爆日志。

scope 决定桶的粒度："channel"=整渠道一桶；"credential"=每把 key 一桶
（openrouter 的池内 key 是不同账号，free 额度各自算，不互相乘也不共享）。
静态规则只配已知渠道；unknown 渠道没有静态阈值，但照样享受 429 熔断保护。

时间轴用 time.time()（墙钟）而非 monotonic：24h 日额度窗口要落盘跨重启，
monotonic 重启后无意义；NTP 微调对分钟级滑窗影响可忽略。
日额度计数落盘 DATA_DIR/rate_limit_day.json（tmp+rename 原子替换，~1KB 无感知延迟）；
1m/1h 窗口纯内存，重启丢了也只丢最近一分钟。
"""

import hashlib
import json
import math
import os
import threading
import time
from collections import deque

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.normpath(os.path.join(os.path.dirname(BASE_DIR), "..", "data", "search_gateway"))
DAY_FILE = os.path.join(DATA_DIR, "rate_limit_day.json")

WINDOW_H = 3600   # 展示粒度：1 小时实测窗
WINDOW_M = 60     # 展示粒度：1 分钟
DAY_WINDOW = 86400
TRIP_PCT = 0.95   # ≥95% 触发提前切换
RESUME_PCT = 0.85 # 回落到 ≤85% 才恢复（滞后防抖）
BACKOFF_STEPS = [15, 30, 60, 120, 300]  # 无 Retry-After 时的指数退避（秒）

# 静态规则（2026-08-26 GPT 评审后口径）。改这里即可更新台账口径。
POLICIES = {
    "xiaohongshu": {
        "scope": "channel", "match": None,
        "rules": [{"window": WINDOW_M, "limit": 60, "source": "est"}],
        "note": "用户口径 ~60 次/分钟（dots3-note-prev），待压测核实",
    },
    "openrouter": {
        "scope": "credential", "match": "free",
        "rules": [{"window": WINDOW_M, "limit": 20, "source": "doc"},
                  {"window": DAY_WINDOW, "limit": 50, "source": "doc"}],
        "note": "官方文档：free 模型 20/min + 50/day（曾购 $10 credits 则 1000/day）；"
                "池内 key 为不同账号，额度各自计",
    },
}
NOTES = {
    "zenmux": "聚合器，实际限流随上游走（z-ai 免费档常态 429 即上游拥挤）",
    "modelscope": "免费档未公开明确 rpm，观测中（仅 429 熔断保护）",
    "sensetime": "日日新免费额度未见公开 rpm，观测中（仅 429 熔断保护）",
    "agnes": "观测中（仅 429 熔断保护）",
    "zscc": "镜像站接口，观测中（禁主动压测，仅 429 熔断保护）",
    "opencode": "观测中（上游间歇不稳，仅 429 熔断保护）",
}

_lock = threading.Lock()
_buckets = {}   # bkey -> bucket dict（见 _new_bucket）；credential 粒度键为 "cid#k指纹"
_events = deque(maxlen=50)  # 状态翻转事件（throttle/recover/blocked），不含每次 skip
_day_loaded = False


def _new_bucket(rules):
    return {
        "rules": [(r["window"], r["limit"]) for r in rules],
        "wins": [deque() for _ in rules],
        "obs": deque(),           # 观测窗（3600s）：无静态规则的渠道也有 1m/1h 用量可看
        "state": "open",          # open | throttled（静态阈值触发）
        "blocked_until": 0.0,     # 429 熔断截止（墙钟秒）
        "consec429": 0,
        "skipped": 0,
    }


def _is_free_model(model):
    m = model or ""
    return m.endswith(":free") or m == "openrouter/free"


def _key_tag(key):
    """key 指纹（md5 前 6 位）：桶键与前端展示用，不落明文。"""
    return hashlib.md5((key or "").encode("utf-8")).hexdigest()[:6]


def _resolve(cid, model, key):
    """该次 attempt 相关的桶键列表。粒度跟随 policy.scope；无 policy 渠道只有熔断桶。
    返回 [(bkey, pol或None)]——pol=None 表示该桶只有 429 熔断、没有静态阈值。
    credential 粒度下 free 池与非 free 请求分桶（后缀 |free）：20/min+50/day 只属于
    free 模型，付费模型不占 free 桶，也不被 free 阈值误伤。"""
    pol = POLICIES.get(cid)
    if pol and pol["scope"] == "credential":
        match_free = pol.get("match") == "free"
        has_static = not (match_free and not _is_free_model(model))
        bkey = cid + "#" + _key_tag(key or "") + ("|free" if has_static else "")
        return [(bkey, pol if has_static else None)]
    if pol:
        return [(cid, pol)]
    return [(cid, None)]


def _bucket(bkey, pol):
    b = _buckets.get(bkey)
    if b is None:
        rules = (pol or {}).get("rules", []) if pol else []
        b = _buckets[bkey] = _new_bucket(rules)
    return b


def _event(ev, bkey, detail=""):
    _events.appendleft({"ts": time.strftime("%H:%M:%S"), "event": ev,
                        "bucket": bkey, "detail": detail})


def _prune(q, now, win):
    while q and now - q[0] > win:
        q.popleft()


def _persist_day():
    """把所有带日窗口的桶时间戳原子落盘。调用方持有 _lock。"""
    out = {}
    for bkey, b in _buckets.items():
        for i, (win, _lim) in enumerate(b["rules"]):
            if win == DAY_WINDOW:
                out[bkey] = list(b["wins"][i])
                break
    tmp = DAY_FILE + ".tmp"
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f)
        os.replace(tmp, DAY_FILE)
    except Exception:  # noqa: BLE001
        pass  # 落盘失败不挡转发：最坏情况重启后日额度从零重计


def try_acquire(cid, model=None, key=None):
    """路由关键路径的准入判定 + 预占（原子）。False = 该渠道/key 本轮应跳过。
    锁内只有 prune/len/append 与一次小 JSON 落盘，绝无网络 IO，不产生可感知延迟。"""
    global _day_loaded
    now = time.time()
    with _lock:
        if not _day_loaded:
            _day_loaded = True
            try:
                with open(DAY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for bkey, stamps in data.items():
                    b = _buckets.get(bkey)
                    if not b:
                        continue
                    for i, (win, _lim) in enumerate(b["rules"]):
                        if win == DAY_WINDOW:
                            b["wins"][i].extend(
                                t for t in (stamps or []) if now - t <= DAY_WINDOW)
            except Exception:  # noqa: BLE001
                pass  # 无文件/损坏 → 从零计（保守方向是少放行，可接受）
        pairs = []
        for bkey, pol in _resolve(cid, model, key):
            b = _bucket(bkey, pol)
            pairs.append((bkey, b))
            if now < b["blocked_until"]:
                b["skipped"] += 1
                return False
            used = []
            for q, (win, lim) in zip(b["wins"], b["rules"]):
                _prune(q, now, win)
                used.append((len(q), lim))
            if b["state"] == "throttled" and all(
                    u <= math.floor(l * RESUME_PCT) for u, l in used):
                b["state"] = "open"
                _event("recover", bkey,
                       "used=" + "/".join(str(u) for u, _ in used))
            if any(u >= math.ceil(l * TRIP_PCT) for u, l in used):
                if b["state"] != "throttled":
                    b["state"] = "throttled"
                    _event("throttle", bkey,
                           "used=" + "/".join(str(u) for u, l in used))
                b["skipped"] += 1
                return False
        # 全部相关桶可放行 → 预占一次真实 attempt
        day_dirty = False
        for _bkey, b in pairs:
            b["obs"].append(now)
            for i, (win, _lim) in enumerate(b["rules"]):
                b["wins"][i].append(now)
                if win == DAY_WINDOW:
                    day_dirty = True
        if day_dirty:
            _persist_day()
        return True


def record_result(cid, model=None, key=None, status=0, retry_after=None):
    """attempt 出结果后回填：429 → 熔断 blocked_until（Retry-After 优先，否则指数退避）；
    2xx → 连续 429 计数清零（不清 blocked_until，封禁到点自然解除）。"""
    now = time.time()
    ra = None
    if retry_after:
        try:
            ra = min(int(float(retry_after)), 600)
        except (TypeError, ValueError):
            ra = None
    with _lock:
        for bkey, pol in _resolve(cid, model, key):
            b = _bucket(bkey, pol)
            if status == 429:
                b["consec429"] += 1
                delay = ra if ra else BACKOFF_STEPS[min(
                    b["consec429"] - 1, len(BACKOFF_STEPS) - 1)]
                until = now + delay
                if until > b["blocked_until"]:
                    b["blocked_until"] = until
                    _event("blocked", bkey, ("Retry-After %ds" % ra) if ra
                           else "backoff %ds" % delay)
            elif 200 <= status < 300:
                b["consec429"] = 0


class RateLimitSkip(Exception):
    """渠道所有配额桶都拒绝放行时由 channels.chat_completion 抛出；
    route_completion 捕获后记一条错误并走用户顺序里的下一渠道。"""


def _counts(b, now):
    """桶的三层用量 (used_1m, used_1h, used_day)。调用方须持有 _lock。
    有对应静态规则用规则窗，否则回退观测窗（3600s）——unknown 渠道也有用量可看。"""
    _prune(b["obs"], now, WINDOW_H)
    used_m = used_h = used_d = None
    for i, (win, _lim) in enumerate(b["rules"]):
        _prune(b["wins"][i], now, win)
        if win == WINDOW_M and used_m is None:
            used_m = len(b["wins"][i])
        elif win == WINDOW_H and used_h is None:
            used_h = len(b["wins"][i])
        elif win == DAY_WINDOW:
            if used_d is None:
                used_d = len(b["wins"][i])
            if used_h is None:
                used_h = sum(1 for t in b["wins"][i] if now - t <= WINDOW_H)
    if used_m is None:
        used_m = sum(1 for t in b["obs"] if now - t <= WINDOW_M)
    if used_h is None:
        used_h = len(b["obs"])
    return used_m, used_h, used_d or 0


def ledger():
    """台账行：兼容 v1 列（limit_rpm/used_1m/used_1h/pct_1m/source/note），
    新增 state/skipped/blocked_in/limit_day/used_day 等；credential 粒度渠道附 keys 明细。"""
    now = time.time()
    rows = {}
    rank = {"open": 0, "throttled": 1, "blocked": 2}
    with _lock:
        cids = set(NOTES) | set(POLICIES) | {bk.split("#")[0] for bk in _buckets}
        for cid in sorted(cids):
            pol = POLICIES.get(cid)
            members = {bk: b for bk, b in _buckets.items()
                       if bk == cid or bk.startswith(cid + "#")}
            if pol is None:
                members.setdefault(cid, _bucket(cid, None))
            row = {
                "limit_rpm": None, "limit_rph": None, "limit_day": None,
                "used_1m": 0, "used_1h": 0, "used_day": None,
                "pct_1m": None, "pct_day": None,
                "state": "open", "skipped": 0, "blocked_in": None,
                "source": "unknown",
                "note": NOTES.get(cid, "观测中"),
                "keys": [],
            }
            if pol:
                row["source"] = pol["rules"][0].get("source", "unknown")
                row["note"] = pol.get("note") or NOTES.get(cid, "观测中")
            for bkey, b in members.items():
                um, uh, ud = _counts(b, now)
                st = ("blocked" if now < b["blocked_until"]
                      else b["state"] if b["state"] == "throttled" else "open")
                if pol and pol.get("scope") == "credential":
                    ktag, _, kpool = bkey.split("#", 1)[1].partition("|")
                    row["keys"].append({"tag": ktag, "pool": kpool or "std",
                                        "state": st,
                                        "used_1m": um, "used_day": ud,
                                        "skipped": b["skipped"]})
                    row["used_1m"] += um
                    row["used_1h"] += uh
                    row["used_day"] = (row["used_day"] or 0) + ud
                else:
                    row["used_1m"], row["used_1h"], row["used_day"] = um, uh, (ud or None)
                row["skipped"] += b["skipped"]
                remain = int(b["blocked_until"] - now)
                if st == "blocked" and remain > 0:
                    row["blocked_in"] = max(row["blocked_in"] or 0, remain)
                if rank[st] > rank[row["state"]]:
                    row["state"] = st
            if pol:
                rpm_rule = next((r for r in pol["rules"] if r["window"] == WINDOW_M), None)
                day_rule = next((r for r in pol["rules"] if r["window"] == DAY_WINDOW), None)
                per_key = pol.get("scope") == "credential"
                if rpm_rule:
                    row["limit_rpm"] = rpm_rule["limit"]
                    if per_key and row["keys"]:
                        row["pct_1m"] = max(round(100 * k["used_1m"] / rpm_rule["limit"], 1)
                                            for k in row["keys"])
                    elif not per_key:
                        row["pct_1m"] = round(100 * row["used_1m"] / rpm_rule["limit"], 1)
                if day_rule:
                    row["limit_day"] = day_rule["limit"]
                    if per_key and row["keys"]:
                        row["pct_day"] = max(round(100 * k["used_day"] / day_rule["limit"], 1)
                                             for k in row["keys"])
                    elif not per_key:
                        row["pct_day"] = round(100 * (row["used_day"] or 0)
                                               / day_rule["limit"], 1)
                if per_key:
                    row["note"] += "；用量=各key合计，百分比=单key最满值"
            rows[cid] = row
    return rows


def events(limit=20):
    with _lock:
        return list(_events)[:limit]


if __name__ == "__main__":
    print(json.dumps({"channels": ledger(), "events": events()}, ensure_ascii=False,
                     indent=2))
