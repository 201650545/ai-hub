# -*- coding: utf-8 -*-
"""ResourceConfigManager（阶段4 P4.2/P4.3，GPT 设计 2026-08-28 §7/§8/§10）。

:3100 对控制平面生成物 gateway_resources.json 的唯一消费入口：

- 拉取式：只读本地生成物文件；不持有飞书 token、不访问飞书、不知道 Base/Table ID；
- 热加载：每次访问 stat(mtime_ns,size) → sha256 去重 → 解析 → 二次校验 → 构建
  immutable snapshot → 一次性 pointer swap；PID 不变、不重启；
- fail-closed last-good：解析/校验任何失败都拒绝 swap，继续用上一个合法 snapshot，
  记 reload_failed，绝不把 :3100 主进程带死；
- 原子性：请求侧永远只看到完整 generation，不存在半版本；
- 迁移顺序（GPT §10）：本期只消费 status（含 expiry 计算态），且仅做
  (channel, unified_model) 精确配对级 gating——配对未覆盖的渠道零影响
  （channel 级语义待飞书数据治理对齐后再启用，避免 paused 语义误伤生产链路，
  现网 candidate 中 modelscope/dashscope 资源为 paused 而渠道在用）；limits 走
  shadow 对照（external precedence 可由生成物开关）；capabilities 要求新旧矩阵
  100% 一致才允许 external precedence，否则自动保持 static。

凭证解析口径（与 GPT §7 的差异，已记录，终审 D2 已修正命名）：生成物的
credential_ref 现网为账号级（cred:acc-*），无法在网关侧按渠道解析。status 中
credential_refs 的真实语义是"渠道名可映射计数"（该资源的 channel 名能在网关
渠道表中找到），绝不代表 credential provider 已解析出可用凭据——因此终审 D2
要求不得称 resolved，已改名为 mapped/unmapped，并携带 semantics=
channel_name_mapped 显式声明口径。未映射引用不阻断 swap（未知渠道本就不可
路由，无法影响路由），只计数并写日志；已知名渠道的引用缺失由控制平面 publish
前置校验拦截。per-key 真实 resolution 明确放入阶段5（GPT R3 裁定）。

失败保持链：live 文件 → 本模块内存 snapshot → gateway_resources.last_good.json。
"""
import hashlib
import json
import os
import re
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 与 rate_limit/quota 同一口径：D:\项目\data\search_gateway（服务数据目录）
DATA_DIR = os.path.normpath(os.path.join(os.path.dirname(BASE_DIR), "..", "data", "search_gateway"))

LIVE_FILE = os.environ.get("RESOURCE_CONFIG_FILE") or os.path.join(DATA_DIR, "gateway_resources.json")
LAST_GOOD_FILE = os.environ.get("RESOURCE_CONFIG_LAST_GOOD") or os.path.join(DATA_DIR, "gateway_resources.last_good.json")
LOG_FILE = os.environ.get("RESOURCE_CONFIG_LOG") or os.path.join(DATA_DIR, "resource_reload.log")

SCHEMA_VERSION = 1
REQUIRED_TOP = ["schema_version", "generation_id", "generated_at", "source", "resources"]
RESOURCE_REQUIRED = ["resource_id", "channel", "unified_model", "upstream_model",
                     "credential_ref", "status", "limits", "capabilities"]
STATUSES = ("active", "paused", "draining", "disabled")
CAP_STATES = ("supported", "unsupported", "unknown")
CAP_KEYS = ("tools", "vision", "json_schema")
RID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")
CRED_PATTERN = re.compile(r"^cred:[A-Za-z0-9_.:-]+$")
EXP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?(Z|[+-]\d{2}:?\d{2})?)?$")
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"Bearer [A-Za-z0-9._-]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
]
# 状态 → 路由封锁原因；越靠前优先级越高（disabled 最强）
_BLOCK_PRIORITY = ("resource_disabled", "resource_expired", "resource_paused", "resource_draining")
_LOG_MAX_BYTES = 512 * 1024


def _log(event, **kw):
    """reload 事件日志（JSONL，>512KB 轮转 .old）。绝不记录配置内容/凭证。"""
    try:
        try:
            if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > _LOG_MAX_BYTES:
                os.replace(LOG_FILE, LOG_FILE + ".old")
        except OSError:
            pass
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event}
        rec.update(kw)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 —— 日志失败绝不影响路由
        pass


def _atomic_write(path, data):
    tmp = path + (".tmp.%d" % os.getpid())
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _expiry_ts(expiry_at):
    """expiry_at → 墙钟秒；非法返回 None（视为未设）。date-only 按当天 23:59:59 本地。"""
    if not expiry_at:
        return None
    s = str(expiry_at).strip()
    if not EXP_PATTERN.match(s):
        return None
    if len(s) == 10:  # YYYY-MM-DD
        try:
            st = time.strptime(s, "%Y-%m-%d")
            return time.mktime((st.tm_year, st.tm_mon, st.tm_mday, 23, 59, 59, 0, 0, -1))
        except ValueError:
            return None
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.timestamp()
        return dt.timestamp()
    except ValueError:
        return None


def _model_variants(unified_model):
    """unified_model 允许逗号分隔多值（真实数据形态），拆成配对键变体。"""
    out = []
    for part in str(unified_model or "").split(","):
        part = part.strip()
        if part:
            out.append(part)
    return out


class ResourceConfigManager(object):
    """持 current/last-good 双 snapshot；所有请求侧访问经 snapshot()/channel_block()。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._stat = None          # (mtime_ns, size)
        self._sha = None
        self._current = None       # immutable snapshot（swap 后只读）
        self._last_good = None
        self._shadow_seen = set()
        self._meta = {
            "active_generation_id": None,
            "active_sha256": None,
            "loaded_at": None,
            "resource_count": 0,
            "last_reload_status": "no_file",   # ok | failed | no_file
            "last_reload_error": None,
            "reload_count": 0,
            "fail_count": 0,
        }

    # ---------- 内部：校验与构建 ----------

    def _validate(self, doc):
        """网关侧二次校验（GPT §7）。返回 error 字符串或 None。"""
        if not isinstance(doc, dict):
            return "顶层非 JSON 对象"
        if doc.get("schema_version") != SCHEMA_VERSION:
            return "schema_version 不支持=%r" % (doc.get("schema_version"),)
        for k in REQUIRED_TOP:
            if k not in doc:
                return "缺少顶层字段 " + k
        rs = doc.get("resources")
        if not isinstance(rs, list):
            return "resources 非数组"
        seen = set()
        for i, r in enumerate(rs):
            if not isinstance(r, dict):
                return "resources[%d] 非对象" % i
            for k in RESOURCE_REQUIRED:
                if k not in r:
                    return "resources[%d] 缺少字段 %s" % (i, k)
            rid = r.get("resource_id")
            if not isinstance(rid, str) or not RID_PATTERN.match(rid):
                return "resources[%d] resource_id 非法" % i
            if rid in seen:
                return "resource_id 重复 " + rid
            seen.add(rid)
            if r.get("status") not in STATUSES:
                return "%s status 非法=%r" % (rid, r.get("status"))
            if not isinstance(r.get("limits"), dict):
                return "%s limits 非对象" % rid
            for lk in ("rpm", "rpd", "concurrency"):
                v = r["limits"].get(lk)
                if v is None:
                    continue
                if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                    return "%s limits.%s 非法" % (rid, lk)
            caps = r.get("capabilities")
            if not isinstance(caps, dict):
                return "%s capabilities 非对象" % rid
            for ck in CAP_KEYS:
                if caps.get(ck) not in CAP_STATES:
                    return "%s capabilities.%s 非法=%r" % (rid, ck, caps.get(ck))
            cred = r.get("credential_ref")
            if not isinstance(cred, str) or not CRED_PATTERN.match(cred):
                return "%s credential_ref 格式非法" % rid
            exp = r.get("expiry_at")
            if exp is not None and not EXP_PATTERN.match(str(exp)):
                return "%s expiry_at 非法=%r" % (rid, exp)
        raw = json.dumps(doc, ensure_ascii=False, sort_keys=True)
        for pat in SECRET_PATTERNS:
            if pat.search(raw):
                return "secret 形态值出现在生成物中"
        return None

    def _build(self, doc):
        """由已过校验的 doc 构建只读 snapshot（含索引与 precedence 判定）。"""
        now = time.time()
        resources = []
        pair_index = {}
        channel_res = {}
        cred_total = cred_mapped = 0
        try:
            import channels as _ch
            known_channels = set((_ch.CHANNELS or {}).keys())
        except Exception:  # noqa: BLE001
            known_channels = set()
        for r in doc["resources"]:
            snap = dict(r)
            snap["limits"] = dict(r.get("limits") or {})
            snap["capabilities"] = dict(r.get("capabilities") or {})
            resources.append(snap)
            cred_total += 1
            if str(snap.get("channel")) in known_channels:
                cred_mapped += 1
            st = snap["status"]
            snap["_expiry_ts"] = _expiry_ts(snap.get("expiry_at"))
            if st == "active" and snap["_expiry_ts"] is not None and now >= snap["_expiry_ts"]:
                snap["_effective"] = "expired"
            else:
                snap["_effective"] = st
            for mv in _model_variants(snap.get("unified_model")):
                pair_index.setdefault((snap["channel"], mv), []).append(snap)
            channel_res.setdefault(snap["channel"], []).append(snap)

        lp = doc.get("limits_precedence")
        limits_precedence = lp if lp in ("shadow", "external") else "shadow"
        cp = doc.get("capabilities_precedence")
        caps_precedence = cp if cp in ("static", "external") else "static"
        caps_effective = "static"
        caps_refused_reason = None
        if caps_precedence == "external":
            conflict = self._matrix_conflict(doc)
            if conflict is None:
                caps_effective = "external"
            else:
                caps_refused_reason = conflict
                _log("capability_precedence_refused", detail=conflict)
        return {
            "resources": tuple(resources),
            "pair_index": pair_index,
            "channel_res": channel_res,
            "generation_id": doc["generation_id"],
            "generated_at": doc.get("generated_at"),
            "table_revisions": dict((doc.get("source") or {}).get("table_revisions") or {}),
            "limits_precedence": limits_precedence,
            "caps_precedence": caps_effective,
            "caps_refused_reason": caps_refused_reason,
            "cred": {"total": cred_total, "mapped": cred_mapped,
                     "unmapped": cred_total - cred_mapped,
                     "semantics": "channel_name_mapped"},
        }

    def _matrix_conflict(self, doc):
        """GPT §10-P4.6：external 能力矩阵必须与静态表 100% 一致才允许切换。

        比较 static 表声明的每个 (channel, model) 与生成物配对；三态映射
        True=supported / False=unsupported / None(未声明)=unknown。
        返回冲突描述或 None。
        """
        try:
            import capabilities as _cap
            static = _cap.load_model_capabilities()
        except Exception:  # noqa: BLE001
            return None
        ext = {}
        for r in doc["resources"]:
            for mv in _model_variants(r.get("unified_model")):
                ext[(str(r["channel"]), mv)] = r.get("capabilities") or {}
        pairs = set(ext.keys())
        for cid, chan in (static.get("channels") or {}).items():
            for mv in (chan.get("models") or {}).keys():
                pairs.add((cid, mv))
        tri = {True: "supported", False: "unsupported", None: "unknown"}
        for cid, mv in pairs:
            e = ext.get((cid, mv))
            s = (((static.get("channels") or {}).get(cid) or {}).get("models") or {}).get(mv)
            if e is None and s is None:
                continue
            for ck in CAP_KEYS:
                ev = (e or {}).get(ck)
                sv = (s or {}).get(ck)
                e_norm = ev if isinstance(ev, str) and ev in CAP_STATES else tri.get(ev, "unknown")
                s_norm = sv if isinstance(sv, str) and sv in CAP_STATES else tri.get(sv, "unknown")
                if e_norm != s_norm:
                    return "%s/%s.%s: external=%r static=%r" % (cid, mv, ck, e_norm, s_norm)
        return None

    # ---------- 内部：热加载 ----------

    def _maybe_reload(self):
        try:
            st = os.stat(LIVE_FILE)
            stat_key = (st.st_mtime_ns, st.st_size)
        except OSError:
            with self._lock:
                if self._stat is not None:
                    # live 文件消失：保留内存 last-good，不回退为空
                    self._meta["last_reload_status"] = "failed"
                    self._meta["last_reload_error"] = "live 文件消失，保持 last-good"
                    _log("reload_failed", reason="live_missing")
            return
        if stat_key == self._stat:
            return
        try:
            with open(LIVE_FILE, "rb") as f:
                raw = f.read()
        except OSError as e:
            self._fail("读取失败: %s" % e.__class__.__name__)
            return
        sha = hashlib.sha256(raw).hexdigest()
        with self._lock:
            if sha == self._sha:
                self._stat = stat_key  # 内容没变（mtime 抖动）
                return
        try:
            doc = json.loads(raw.decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            self._fail("JSON 解析失败: %s" % e.__class__.__name__)
            return
        err = self._validate(doc)
        if err:
            self._fail("二次校验失败: " + err)
            return
        snap = self._build(doc)
        with self._lock:
            self._current = snap
            self._last_good = snap
            self._sha = sha
            self._stat = stat_key
            m = self._meta
            m["active_generation_id"] = snap["generation_id"]
            m["active_sha256"] = sha
            m["loaded_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            m["resource_count"] = len(snap["resources"])
            m["last_reload_status"] = "ok"
            m["last_reload_error"] = None
            m["reload_count"] += 1
            try:
                _atomic_write(LAST_GOOD_FILE, raw)
            except OSError:
                pass
        _log("reload_ok", generation_id=snap["generation_id"],
             resource_count=len(snap["resources"]),
             limits_precedence=snap["limits_precedence"],
             capabilities_precedence=snap["caps_precedence"])

    def _fail(self, reason):
        with self._lock:
            m = self._meta
            m["last_reload_status"] = "failed"
            m["last_reload_error"] = reason
            m["fail_count"] += 1
        _log("reload_failed", reason=reason)

    # ---------- 请求侧 API（热路径） ----------

    def snapshot(self):
        """取当前 immutable snapshot；无合法生成物时返回 None。每次调用惰性热加载。"""
        self._maybe_reload()
        return self._current

    def channel_block(self, channel, model):
        """(channel, model) 配对级 gating（GPT §10 第一阶段）。

        返回 None=不封锁；否则 (reason, resource_id)。
        配对未被生成物覆盖 → 一律不封锁（unmanaged pairs fail-open）；
        配对被覆盖且存在任一 effective=active 资源 → 不封锁；
        全部非 active → 按优先级返回 resource_disabled/expired/paused/draining。
        """
        snap = self.snapshot()
        if not snap:
            return None
        rows = snap["pair_index"].get((channel, model))
        if not rows:
            return None
        best = None
        for r in rows:
            eff = r.get("_effective")
            if eff == "active":
                return None
            reason = "resource_" + eff
            if best is None or _BLOCK_PRIORITY.index(reason) < _BLOCK_PRIORITY.index(best[0]):
                best = (reason, r["resource_id"])
        return best

    def external_policy(self, cid):
        """rate_limit 准入的 external policy（GPT §10 第三步）。

        shadow 模式（默认）：与 legacy POLICIES 对照，差异记日志（每 generation+渠道
        一条），返回 None（legacy 保持权威）。external 模式：由 active 资源聚合出
        渠道级 rules（各资源取最严值），无限制时返回 None（与无静态规则渠道行为一致）。
        """
        snap = self.snapshot()
        if not snap:
            return None
        rows = [r for r in snap["channel_res"].get(cid, [])
                if r.get("_effective") == "active"]
        agg = {}
        for r in rows:
            lim = r.get("limits") or {}
            for lk, win in (("rpm", 60), ("rpd", 86400)):
                v = lim.get(lk)
                if v:
                    agg[win] = min(int(v), agg.get(win, int(v)))
        if not agg:
            return None
        policy = {"scope": "channel", "match": None,
                  "rules": [{"window": w, "limit": l, "source": "control_plane"}
                            for w, l in sorted(agg.items())],
                  "note": "control_plane generation=" + snap["generation_id"]}
        if snap["limits_precedence"] == "external":
            return policy
        # shadow：与 legacy 对照（每 generation+渠道只记一条）
        key = (snap["generation_id"], cid)
        if key not in self._shadow_seen:
            self._shadow_seen.add(key)
            try:
                from rate_limit import POLICIES as _P
                legacy = _P.get(cid)
            except Exception:  # noqa: BLE001
                legacy = None
            ext_map = {r["window"]: r["limit"] for r in policy["rules"]}
            leg_map = {r["window"]: r["limit"] for r in (legacy or {}).get("rules", [])} if legacy else {}
            if ext_map != leg_map:
                _log("limits_shadow_differs", channel=cid,
                     external=ext_map, legacy=leg_map)
        return None

    def external_capabilities(self, channel, model):
        """capabilities 外移（GPT §10 第四步）。返回 model_capabilities() 兼容 dict 或 None。

        仅当生成物声明 capabilities_precedence=external 且矩阵一致性检查通过时生效；
        配对未覆盖 → None（回落静态表）。
        """
        snap = self.snapshot()
        if not snap or snap["caps_precedence"] != "external":
            return None
        rows = snap["pair_index"].get((channel, model))
        if not rows:
            return None
        caps = {c: None for c in CAP_KEYS}
        for r in rows:
            for ck in CAP_KEYS:
                v = (r.get("capabilities") or {}).get(ck)
                if v == "supported":
                    caps[ck] = True
                elif v == "unsupported":
                    caps[ck] = False
        return {"known": True, "capabilities": caps, "source": "control_plane"}

    # ---------- 观测 ----------

    def status_payload(self):
        """只读状态端点载荷（GPT §8）：不含任何配置内容与凭证。"""
        self._maybe_reload()
        with self._lock:
            m = dict(self._meta)
        snap = self._current
        if snap:
            m["limits_precedence"] = snap["limits_precedence"]
            m["capabilities_precedence"] = snap["caps_precedence"]
            if snap.get("caps_refused_reason"):
                m["capabilities_refused_reason"] = snap["caps_refused_reason"]
            # 终审 D2：口径为渠道名映射计数（非真实凭据解析），semantics 字段自声明
            m["credential_refs"] = snap["cred"]
        else:
            m["limits_precedence"] = "shadow"
            m["capabilities_precedence"] = "static"
        return m


_manager = None
_manager_lock = threading.Lock()


def instance():
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = ResourceConfigManager()
    return _manager


def snapshot():
    return instance().snapshot()


def channel_block(channel, model):
    return instance().channel_block(channel, model)


def status_payload():
    return instance().status_payload()


def external_policy(cid):
    return instance().external_policy(cid)


def external_capabilities(channel, model):
    return instance().external_capabilities(channel, model)
