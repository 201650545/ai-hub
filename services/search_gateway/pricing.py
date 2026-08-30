# -*- coding: utf-8 -*-
"""per-model 价格闸门判定层（设计稿 v0.5 §4.1/§4.2/§4.3/§4.6，P1-2 判定 + P1-4 运维态/写侧）。

定位与 `capabilities.py` 同层：纯函数 + mtime 热载，无进程内定时器。但计费语义
与能力层**相反**——能力层未知默认放行（fail-open），计费层未知/陈旧/缺文件/解析失败
一律默认拦截（fail-closed），这是 Q1/Q2 拍板与网关全线 fail-closed 哲学的要求。

核心判定：
    verdict(channel_id, upstream_model) -> {"allow", "class", "reason", ...}
      class=free          -> allow
      class=paid          -> deny，除非条目级 `authorized` 显式授权（未撤销）-> authorized_paid
      class=unknown       -> 按 PRICING_UNKNOWN_POLICY（缺省 "deny"，Q2 fail-closed）

新鲜度（§4.1，N4 防陈旧化悬崖）：
    条目级 `verified_at` 超过窗口自动降为 unknown（fail-closed）：
      account_bound 或 billing_model=quota -> QUOTA_STALE_DAYS（默认 7）
      其余                                  -> PRICING_STALE_DAYS（默认 30）
    窗口作用于**模型条目**（含 paid/authorized 条目，见下）；渠道级/全局默认
    （无时间戳）不受新鲜度影响。

授权（§4.3，M5）：
    `authorized.revoked_at` 非空即授权失效、回到 deny 侧（可撤回）。
    **一条刻意且已记录的取舍**：新鲜度对 authorized 条目同样生效——即一个已授权的
    paid 条目若 verified_at 超窗也会先降 unknown 再被拦。理由是「授权」回答“是否被
    批准”，而“新鲜度”回答“我们的定价数据是否仍可信”，两者正交；宁可保守拦截，由
    复核流程（§4.1 M3 / 组成员离线核对）负责保鲜。若日后希望授权豁免新鲜度，改
    `_entry_class` 一处即可，属单点可回退决策。

加载（§4.6，M4）：
    mtime 感知热载，读路径不加锁（单引用赋值在 GIL 下原子）。**运行期解析失败不保留
    last-known-good**——放行错方向的代价不对称，直接进 `pricing-invalid`（kind=invalid）
    fail-closed，直到读到下一份合法配置。写侧走 `write_pricing_atomic`：先校验、写同目录
    临时文件、回读校验、`os.replace` 原子替换，坏数据永远落不到真源上。

运维态（§4.3 N1/M2，P1-4）：
    `effective_verdict()` 在计费判定外再套一层闸门模式，模式来自环境变量：
      PRICING_MODE = off | observe | enforce（**缺省 enforce**）
      PRICING_OBSERVE_UNTIL = YYYY-MM-DD（observe 必填，窗口 ≤ OBSERVE_MAX_DAYS=7 天）
    缺省取 enforce 而不是 off，是为了 fail-closed：忘配 env 的后果是“拦多了”（可观测、
    可补配），而不是“悄悄全放”。observe 只在**有效窗口内**把 deny 转成 allow 并打
    `observe_would_deny:<原reason>` 留痕；窗口一旦到期即视为配置失效，**不静默续观**——
    到期后一律 deny，并需显式改 enforce 或重新批准一个新窗口。
    启动期硬错误（mode 非法 / observe 缺 UNTIL / 超窗 / 已过期 / 真源损坏）由
    `validate_startup_config()` 判为退出码 `EXIT_PRICING_CONFIG=3106`，拒绝启动；
    运行中到期则只转 deny + 打 `pricing_config_invalid` 标签，服务不退出，避免 crash-loop。
    本节仅提供判定能力，P1 不接线进 `api_gateway`。
"""
import datetime
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.normpath(os.path.join(os.path.dirname(BASE_DIR), "..", "data", "search_gateway"))
PRICING_JSON = os.path.join(DATA_DIR, "model_pricing.json")

# 新鲜度窗口（天）。配额/账户绑定型走短窗；其余走长窗。均为可配常量，勿在运行中热改。
PRICING_STALE_DAYS = 30
QUOTA_STALE_DAYS = 7

CLASS_FREE = "free"
CLASS_PAID = "paid"
CLASS_UNKNOWN = "unknown"
_VALID_CLASSES = (CLASS_FREE, CLASS_PAID, CLASS_UNKNOWN)

# 定价文档结构版本（schema 版本，与条目 class 无关；不等即视为不兼容配置）。
DOC_VERSION = 1

# 闸门模式（§4.3 N1）。缺省 enforce：忘配 env 只会拦多，不会悄悄放。
MODE_OFF = "off"
MODE_OBSERVE = "observe"
MODE_ENFORCE = "enforce"
MODES = (MODE_OFF, MODE_OBSERVE, MODE_ENFORCE)
MODE_DEFAULT = MODE_ENFORCE
OBSERVE_MAX_DAYS = 7

# 启动期定价配置硬错误的退出码（Q5：3105 已被 watchdog 事件源占用）。
EXIT_PRICING_CONFIG = 3106

# path -> {"mtime": float|None, "kind": "ok"|"missing"|"invalid", "data": dict|None, "error": str|None}
_cache = {}


def _parse_date(s):
    """ISO 日期（YYYY-MM-DD）-> date；非法/缺失返回 None。"""
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(str(s).strip())
    except (ValueError, TypeError):
        return None


def _validate_doc(data):
    """定价文档结构校验：返回错误描述，合法返回 None。

    读侧（`load_pricing`）与写侧（`write_pricing_atomic`）共用同一份校验，杜绝双逻辑。
    只校验结构，不校验定价语义（语义由 `_entry_class`/新鲜度在判定时处理）。
    """
    if not isinstance(data, dict):
        return "pricing root is not an object"
    version = data.get("version")
    if version is not None and version != DOC_VERSION:
        return "unsupported pricing version %r (expect %d)" % (version, DOC_VERSION)
    channels = data.get("channels", {})
    if not isinstance(channels, dict):
        return "pricing.channels is not an object"
    for cid, chan in channels.items():
        if not isinstance(chan, dict):
            return "pricing.channels.%s is not an object" % cid
        models = chan.get("models", {})
        if not isinstance(models, dict):
            return "pricing.channels.%s.models is not an object" % cid
    gdef = data.get("global_default_class", CLASS_UNKNOWN)
    if gdef not in _VALID_CLASSES:
        return "pricing.global_default_class %r not in %s" % (gdef, "/".join(_VALID_CLASSES))
    return None


def load_pricing(path=None):
    """mtime 感知加载定价真源，返回状态字典。

    返回 {"mtime", "kind", "data", "error"}，kind ∈ ok|missing|invalid。
    - 文件缺失      -> kind=missing（等价“全部 unknown”，默认拦）
    - 解析/结构失败 -> kind=invalid（**不**保留 last-known-good，M4 fail-closed）；
      结构细则见 `_validate_doc`（version 不等于 DOC_VERSION、channels/渠道条目/models
      形状非法、global_default_class 非法，均判 invalid）
    - 正常          -> kind=ok，data=完整新 dict（单次引用赋值，读路径免锁）
    """
    path = os.path.abspath(path or PRICING_JSON)
    try:
        mt = os.path.getmtime(path)
    except OSError:
        mt = None
    ent = _cache.get(path)
    if ent is not None and ent["mtime"] == mt:
        return ent
    if mt is None:
        st = {"mtime": None, "kind": "missing", "data": None, "error": None}
    else:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            err = _validate_doc(data)
            if err:
                raise ValueError(err)
            st = {"mtime": mt, "kind": "ok", "data": data, "error": None}
        except Exception as e:  # noqa: BLE001  M4: 解析失败不得沿用旧数据
            st = {"mtime": mt, "kind": "invalid", "data": None, "error": str(e)[:200]}
    _cache[path] = st
    return st


def _entry_class(entry, chan, doc):
    """解析 (channel, model) 的有效 class 与来源。

    返回 (class, source, entry_or_None)。source ∈ model|channel_default|global_default。
    模型条目缺失或 class 非法时，回退渠道默认 -> 全局默认 -> unknown。
    """
    if isinstance(entry, dict) and entry.get("class") in _VALID_CLASSES:
        return entry.get("class"), "model", entry
    cdef = chan.get("default_class") if isinstance(chan, dict) else None
    if cdef in _VALID_CLASSES:
        return cdef, "channel_default", None
    gdef = doc.get("global_default_class", CLASS_UNKNOWN) if isinstance(doc, dict) else CLASS_UNKNOWN
    if gdef not in _VALID_CLASSES:
        gdef = CLASS_UNKNOWN
    return gdef, "global_default", None


def _is_stale(entry, now):
    """条目新鲜度。返回 (stale: bool, window_days: int)。

    verified_at 缺失/非法一律视为陈旧（fail-closed）。配额/账户绑定走短窗。
    """
    if not isinstance(entry, dict):
        return False, PRICING_STALE_DAYS
    quota = bool(entry.get("account_bound")) or entry.get("billing_model") == "quota"
    window = QUOTA_STALE_DAYS if quota else PRICING_STALE_DAYS
    d = _parse_date(entry.get("verified_at"))
    if d is None:
        return True, window
    return (now - d).days > window, window


def verdict(channel_id, upstream_model, now=None, path=None):
    """计费准入判定（计费面，fail-closed）。

    返回至少含 {"allow": bool, "class": str, "reason": str}，另附
    {"detail", "authorized", "stale", "source"} 供日志/响应头使用。
    `class` 为**降级后**的有效 class（陈旧条目报 unknown）。
    """
    now = now or datetime.date.today()
    st = load_pricing(path)
    kind = st.get("kind")
    if kind == "missing":
        return _deny(CLASS_UNKNOWN, "pricing_missing",
                     detail="model_pricing.json 缺失，按 Q2 全部 unknown 处理",
                     source="missing")
    if kind == "invalid":
        return _deny(CLASS_UNKNOWN, "pricing_invalid",
                     detail="model_pricing.json 解析失败（M4 fail-closed，不沿用旧数据）: %s" % st.get("error"),
                     source="invalid")

    doc = st.get("data") or {}
    channels = doc.get("channels") or {}
    chan = channels.get(channel_id) or {}
    models = chan.get("models") or {}
    entry = models.get(upstream_model)

    cls, source, eff_entry = _entry_class(entry, chan, doc)
    stale = False
    window = None
    if source == "model" and cls in (CLASS_FREE, CLASS_PAID):
        stale, window = _is_stale(eff_entry, now)
        if stale:
            cls = CLASS_UNKNOWN  # 新鲜度降级（含 paid/authorized 条目）

    if cls == CLASS_FREE:
        return _allow(CLASS_FREE, "free", source=source,
                      detail="已验证免费")
    if cls == CLASS_PAID:
        auth = eff_entry.get("authorized") if isinstance(eff_entry, dict) else None
        revoked = isinstance(auth, dict) and auth.get("revoked_at") not in (None, "")
        if isinstance(auth, dict) and not revoked:
            return _allow(CLASS_PAID, "authorized_paid", source=source, authorized=True,
                          detail="条目级显式授权放行（日志标 authorized_paid）")
        if revoked:
            return _deny(CLASS_PAID, "authorized_revoked", source=source,
                         detail="授权已被撤销（revoked_at 非空），回到拦截侧")
        return _deny(CLASS_PAID, "paid", source=source, detail="已验证收费且未授权")

    # unknown
    policy = (os.environ.get("PRICING_UNKNOWN_POLICY") or "deny").strip().lower()
    if policy == "allow":
        return _allow(CLASS_UNKNOWN, "unknown_policy_allow", source=source,
                      detail="PRICING_UNKNOWN_POLICY=allow，unknown 放行（仅观察/排障用）")
    if stale:
        return _deny(CLASS_UNKNOWN, "stale", source=source, stale=True,
                     detail="verified_at 超 %s 天窗口，降为 unknown 拦截" % window)
    return _deny(CLASS_UNKNOWN, "unknown", source=source,
                 detail="未验证定价，默认拦截（Q2 fail-closed）")


def peek_class(channel_id, upstream_model, now=None, path=None):
    """纯观测：只回答「这个候选是什么价格类别」，不判准入、不读任何 PRICING_* 环境变量。

    与 verdict() 共用同一套类别解析（三级回退 + 新鲜度降级），但**没有 allow/deny 语义**，
    因此本函数不可作为放行依据。任何异常返回 None —— 观测失败绝不影响调用方。
    """
    try:
        now = now or datetime.date.today()
        st = load_pricing(path)
        kind = st.get("kind")
        if kind != "ok":
            return {"class": CLASS_UNKNOWN, "source": kind or "unknown", "stale": False}
        doc = st.get("data") or {}
        chan = (doc.get("channels") or {}).get(channel_id) or {}
        entry = (chan.get("models") or {}).get(upstream_model)
        cls, source, eff_entry = _entry_class(entry, chan, doc)
        stale = False
        if source == "model" and cls in (CLASS_FREE, CLASS_PAID):
            stale, _window = _is_stale(eff_entry, now)
            if stale:
                cls = CLASS_UNKNOWN
        return {"class": cls, "source": source, "stale": stale}
    except Exception:  # noqa: BLE001  观测面：任何失败静默降级为 None
        return None


def _allow(cls, reason, source="", authorized=False, detail=""):
    return {"allow": True, "class": cls, "reason": reason, "detail": detail,
            "authorized": authorized, "stale": False, "source": source}


def _deny(cls, reason, source="", stale=False, detail=""):
    return {"allow": False, "class": cls, "reason": reason, "detail": detail,
            "authorized": False, "stale": stale, "source": source}


# ---------------------------------------------------------------- 闸门模式（§4.3 N1/M2）

def resolve_mode(now=None):
    """解析价格闸门模式。返回 {"mode", "observe_until", "status", "error"}。

    status ∈ "ok" | "expired" | "invalid:<标签>"，invalid 时 error 给出人类可读原因。
    env 缺失按 MODE_DEFAULT（enforce）；observe 必须带合法且窗口 ≤ OBSERVE_MAX_DAYS 的
    PRICING_OBSERVE_UNTIL；窗口已过为 expired（到期不静默续观），剩余 0 天当天仍算 ok。
    """
    now = now or datetime.date.today()
    mode = (os.environ.get("PRICING_MODE") or MODE_DEFAULT).strip().lower()
    info = {"mode": mode, "observe_until": None, "status": "ok", "error": ""}
    if mode not in MODES:
        info["status"] = "invalid:mode"
        info["error"] = "PRICING_MODE 取值非法（应为 %s）" % "/".join(MODES)
        return info
    if mode != MODE_OBSERVE:
        return info
    until = _parse_date(os.environ.get("PRICING_OBSERVE_UNTIL"))
    info["observe_until"] = until.isoformat() if until else None
    if until is None:
        info["status"] = "invalid:observe_until_missing"
        info["error"] = "observe 模式必须配置合法的 PRICING_OBSERVE_UNTIL（YYYY-MM-DD，M2）"
        return info
    remaining = (until - now).days
    if remaining > OBSERVE_MAX_DAYS:
        info["status"] = "invalid:observe_until_too_long"
        info["error"] = "observe 窗口 %d 天，超过 %d 天上限" % (remaining, OBSERVE_MAX_DAYS)
        return info
    if remaining < 0:
        info["status"] = "expired"
        info["error"] = "observe 窗口已于 %s 到期" % info["observe_until"]
    return info


def effective_verdict(channel_id, upstream_model, now=None, path=None, mode_info=None):
    """闸门模式 + 计费判定后的最终准入结论（P2 准入序应调本函数，而非 verdict）。

    off     -> 一律放行（reason=pricing_off，闸门关闭）
    配置失效 -> 一律拦截（reason=pricing_config_invalid，fail-closed，不猜测模式）
    observe -> 有效窗口内把 deny 转 allow，reason 前缀 observe_would_deny: 留痕
    enforce -> verdict() 原样
    """
    mode_info = mode_info or resolve_mode(now)
    mode = mode_info.get("mode")
    if mode == MODE_OFF:
        return _allow(CLASS_UNKNOWN, "pricing_off", source="mode",
                      detail="PRICING_MODE=off，计费闸门关闭")
    v = verdict(channel_id, upstream_model, now=now, path=path)
    status = mode_info.get("status") or "ok"
    if status != "ok":
        return _deny(v["class"], "pricing_config_invalid", source="mode",
                     stale=bool(v.get("stale")),
                     detail="定价闸门配置不可信（%s），fail-closed 拦截；底层判定：%s"
                            % (status, v.get("detail") or v.get("reason")))
    if mode == MODE_OBSERVE and not v["allow"]:
        a = _allow(v["class"], "observe_would_deny:%s" % v["reason"], source=v.get("source", ""),
                   detail="observe 窗口内放行；若 enforce 将被拦（%s）"
                          % (v.get("detail") or v.get("reason")))
        a["stale"] = bool(v.get("stale"))
        return a
    return v


def validate_startup_config(now=None, pricing_path=None):
    """启动期定价闸门自检。返回 (ok, exit_code, message)。

    硬错误（模式非法 / observe 缺 UNTIL / 超窗 / 已过期 / 真源结构损坏）→ 拒启动，
    退出码 EXIT_PRICING_CONFIG(3106)：带着不可信的闸门配置起服务比不起更危险。
    真源缺失 → 放行启动但返回警告（运行期每条按 unknown 拦，行为可观测）。
    本函数供 P2 的 api_gateway 启动时调用，P1 不接线。
    """
    mode_info = resolve_mode(now)
    status = mode_info.get("status") or "ok"
    if status != "ok":
        return False, EXIT_PRICING_CONFIG, "pricing-config-invalid: %s" % mode_info.get("error")
    st = load_pricing(pricing_path)
    if st.get("kind") == "invalid":
        return False, EXIT_PRICING_CONFIG, "pricing-invalid: model_pricing.json 不可用: %s" % st.get("error")
    if st.get("kind") == "missing":
        return True, None, "警告: model_pricing.json 缺失，全部按 unknown 默认拦截"
    return True, None, ""


# ---------------------------------------------------------------- 写侧原子替换（§4.6 M4）

def write_pricing_atomic(doc, path=None):
    """校验后原子写入定价真源，返回目标绝对路径；校验不通过抛 ValueError。

    临时文件与目标同目录（保证 `os.replace` 同卷原子），写后回读再校验一次，
    失败则不替换目标——真源永远不会停留在半截或被拒绝的内容上。写完清掉该路径的
    读缓存，让 mtime 热载立刻看到新数据。
    """
    target = os.path.abspath(path or PRICING_JSON)
    err = _validate_doc(doc)
    if err:
        raise ValueError(err)
    tmp = "%s.tmp.%d" % (target, os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
            f.flush()
            os.fsync(f.fileno())
        with open(tmp, "r", encoding="utf-8") as f:
            reload_err = _validate_doc(json.load(f))
        if reload_err:
            raise ValueError("回读校验失败: %s" % reload_err)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    _cache.pop(target, None)
    return target
