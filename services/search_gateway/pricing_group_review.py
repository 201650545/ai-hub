# -*- coding: utf-8 -*-
"""编排组成员离线核对脚本（设计稿 v0.5 §4.2 B1+M1 / §6 P1-3，周期 N3=7 天）。

定位：**提前发现 + 留痕**，不是最后防线——M1 改判后运行时 fresh-free 候选校验才是
防线。本脚本在人类还能处理的窗口里把即将失效的条目挑出来。

只读纪律：只读 unified_models.json 与 model_pricing.json，**绝不写组配置**
（不自动摘除/新增成员）；唯一写入物是自身报告日志 pricing_review.log（追加留痕）。

四类输出：
  [BLOCKED]   组成员当前 verdict 不放行（paid/unknown/stale/缺文件/损坏）——
              enforce 后 M1 会将其剔除，须复核或补登记；
  [NOTE]      组成员靠显式授权放行（authorized_paid）——信息项，不计入异常；
  [REVIEW]    class=free 条目 last_reviewed_ok 超 7 天或缺失（M3 节奏审计，
              覆盖全部 free 条目含配额型）；
  [EXPIRING]  非配额条目距降级窗口 ≤7 天（N4 到期前预警；配额型走 7 天短窗，
              其"预警"就是逐周 REVIEW，不重复报）。

退出码：0=无异常 1=有告警（BLOCKED/REVIEW/EXPIRING 任一） 2=真源或组文件不可读
建议挂法：计划任务每 7 天一次（注册需提权脚本，另行授权）；或人工周检时手跑。
"""
import argparse
import datetime
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import pricing  # noqa: E402

DATA_DIR = pricing.DATA_DIR
DEFAULT_UNIFIED = os.path.join(DATA_DIR, "unified_models.json")
DEFAULT_LOG = os.path.join(DATA_DIR, "pricing_review.log")

REVIEW_CYCLE_DAYS = 7   # M3：全部 free 条目统一 ≤7 天复核
PREWARN_DAYS = 7        # N4：到期前 7 天起预警，不在过期当天硬翻转


def run(now=None, unified_path=DEFAULT_UNIFIED, pricing_path=None):
    """执行一次核对。返回 (exit_code, report_lines)。纯读，任何情况下不改组文件。"""
    now = now or datetime.date.today()
    lines = []
    counts = {"blocked": 0, "review": 0, "expiring": 0, "note": 0}

    st = pricing.load_pricing(pricing_path)
    if st["kind"] != "ok":
        lines.append("FATAL 定价真源不可读（kind=%s error=%s）——闸门与核对同为 fail-closed 面"
                     % (st["kind"], st.get("error")))
        return 2, lines
    doc = st["data"]

    try:
        with open(unified_path, "r", encoding="utf-8") as f:
            unified = json.load(f)
        if not isinstance(unified, dict):
            raise ValueError("unified root is not an object")
    except Exception as e:  # noqa: BLE001
        lines.append("FATAL unified_models.json 不可读：%s" % str(e)[:200])
        return 2, lines

    # 1) 组成员逐个 verdict 核对（与运行时 M1 同一判定函数，杜绝双逻辑）
    member_n = 0
    for gid in sorted(unified):
        members = (unified[gid] or {}).get("members") or {}
        for cid in sorted(members):
            model = members[cid]
            member_n += 1
            if not isinstance(model, str) or not model:
                counts["blocked"] += 1
                lines.append("[BLOCKED] %s %s/%s — 成员名非法(%r)" % (gid, cid, model, model))
                continue
            v = pricing.verdict(cid, model, now=now, path=pricing_path)
            tag = "%s %s/%s" % (gid, cid, model)
            if v["allow"]:
                if v.get("authorized"):
                    counts["note"] += 1
                    lines.append("[NOTE] %s — 靠显式授权放行（authorized_paid），授权撤销即拦" % tag)
                continue
            counts["blocked"] += 1
            lines.append("[BLOCKED] %s class=%s reason=%s — enforce 后按 M1 被剔除，须复核/补登记"
                         % (tag, v["class"], v["reason"]))

    # 2) 定价条目审计：M3 复核节奏 + N4 到期预警
    for cid in sorted(doc.get("channels") or {}):
        ch = (doc.get("channels") or {}).get(cid) or {}
        for model in sorted(ch.get("models") or {}):
            entry = (ch.get("models") or {}).get(model) or {}
            if not isinstance(entry, dict):
                continue
            tag = "%s/%s" % (cid, model)
            quota = bool(entry.get("account_bound")) or entry.get("billing_model") == "quota"
            window = pricing.QUOTA_STALE_DAYS if quota else pricing.PRICING_STALE_DAYS
            if entry.get("class") == "free":
                lr = pricing._parse_date(entry.get("last_reviewed_ok"))
                if lr is None or (now - lr).days > REVIEW_CYCLE_DAYS:
                    counts["review"] += 1
                    lines.append("[REVIEW] %s last_reviewed_ok=%s 超 %d 天或缺失（M3 节奏）"
                                 % (tag, entry.get("last_reviewed_ok"), REVIEW_CYCLE_DAYS))
            if not quota:
                vd = pricing._parse_date(entry.get("verified_at"))
                if vd is not None:
                    days_left = window - (now - vd).days
                    if 0 <= days_left <= PREWARN_DAYS:
                        counts["expiring"] += 1
                        lines.append("[EXPIRING] %s %d 天后降 unknown（窗口 %dd，N4）"
                                     % (tag, days_left, window))

    header = ("==== 组定价核对 %s | 组=%d 成员=%d | BLOCKED=%d REVIEW=%d EXPIRING=%d NOTE=%d ===="
              % (now.isoformat(), len(unified), member_n,
                 counts["blocked"], counts["review"], counts["expiring"], counts["note"]))
    lines.insert(0, header)
    warn_total = counts["blocked"] + counts["review"] + counts["expiring"]
    return (1 if warn_total else 0), lines


def main(argv=None):
    ap = argparse.ArgumentParser(description="编排组成员离线核对（只告警留痕，绝不改组）")
    ap.add_argument("--unified", default=DEFAULT_UNIFIED)
    ap.add_argument("--pricing", default=None, help="默认定价真源路径（测试/演练用）")
    ap.add_argument("--now", default=None, help="ISO 日期，覆盖'今天'（测试用）")
    ap.add_argument("--log", default=DEFAULT_LOG)
    ap.add_argument("--no-log", action="store_true", help="只打印不落盘")
    a = ap.parse_args(argv)
    now = datetime.date.fromisoformat(a.now) if a.now else None

    code, lines = run(now=now, unified_path=a.unified, pricing_path=a.pricing)
    for ln in lines:
        print(ln)
    if not a.no_log:
        try:
            with open(a.log, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n\n")
            print("(已留痕: %s)" % a.log)
        except OSError as e:
            print("WARN 留痕失败: %s" % e)
    return code


if __name__ == "__main__":
    sys.exit(main())
