# -*- coding: utf-8 -*-
"""渠道限流台账 —— 记录阶段（task_044），只记账不切换。

每个渠道两层数据：
1. LIMITS 调研上限：rpm/rph 数字 + source 标注来源（doc=官方文档 / est=估计待核实 /
   unknown=未公开，观测中）；不确定的宁可留 None，不编数字。
2. 滑动窗口实测：chat_completion 入口打点 hit()，维护最近 3600s 时间戳队列，
   导出 used_1m / used_1h。

查询：GET /api/rate-limits（api_gateway.py）→ ledger()。
后续「95% 提前切换」策略另行决策，本模块不参与路由判断。
"""

import threading
import time
from collections import defaultdict, deque

WINDOW_H = 3600  # 实测窗口：1 小时
WINDOW_M = 60    # 展示粒度：1 分钟

# 调研上限（2026-08-25 起）。改这里即可更新台账口径。
LIMITS = {
    "xiaohongshu": {
        "rpm": 60, "rph": None, "source": "est",
        "note": "用户口径 ~60 次/分钟（dots3-note-prev），待压测核实",
    },
    "openrouter": {
        "rpm": 20, "rph": None, "source": "doc",
        "note": ":free 模型 20 req/min；账户余额 <$10 时另有 50 次/天日限额",
    },
    "zenmux": {
        "rpm": None, "rph": None, "source": "unknown",
        "note": "聚合器，实际限流随上游走（z-ai 免费档常态 429 即上游拥挤）",
    },
    "modelscope": {"rpm": None, "rph": None, "source": "unknown", "note": "免费档未公开明确 rpm，观测中"},
    "sensetime":  {"rpm": None, "rph": None, "source": "unknown", "note": "日日新免费额度未见公开 rpm，观测中"},
    "agnes":      {"rpm": None, "rph": None, "source": "unknown", "note": "观测中"},
    "zscc":       {"rpm": None, "rph": None, "source": "unknown", "note": "镜像站接口，观测中（禁主动压测）"},
    "opencode":   {"rpm": None, "rph": None, "source": "unknown", "note": "观测中（上游间歇不稳）"},
}

_lock = threading.Lock()
_hits = defaultdict(deque)  # channel_id -> deque[float 秒时间戳]


def hit(channel_id):
    """每次转发请求入口打点（无论成败——限流数的是请求数）。"""
    if not channel_id:
        return
    now = time.time()
    with _lock:
        q = _hits[channel_id]
        q.append(now)
        while q and now - q[0] > WINDOW_H:
            q.popleft()


def _prune(q, now):
    while q and now - q[0] > WINDOW_H:
        q.popleft()


def snapshot(channel_id=None):
    """{cid: {used_1m, used_1h}}，只统计窗口内。"""
    now = time.time()
    out = {}
    with _lock:
        for c, q in _hits.items():
            if channel_id and c != channel_id:
                continue
            _prune(q, now)
            out[c] = {
                "used_1m": sum(1 for t in q if now - t <= WINDOW_M),
                "used_1h": len(q),
            }
    return out


def ledger():
    """台账行：调研上限 + 实测用量 + 百分比。未知上限 pct 为 null。"""
    snap = snapshot()
    rows = {}
    for c in sorted(set(LIMITS) | set(snap)):
        lim = LIMITS.get(c, {})
        s = snap.get(c, {"used_1m": 0, "used_1h": 0})
        rpm = lim.get("rpm")
        rows[c] = {
            "limit_rpm": rpm,
            "limit_rph": lim.get("rph"),
            "used_1m": s["used_1m"],
            "used_1h": s["used_1h"],
            "pct_1m": round(100 * s["used_1m"] / rpm, 1) if rpm else None,
            "source": lim.get("source", "unknown"),
            "note": lim.get("note", ""),
        }
    return rows


if __name__ == "__main__":
    import json
    print(json.dumps(ledger(), ensure_ascii=False, indent=2))
