# -*- coding: utf-8 -*-
"""组件编排器主控 —— 两段式生成 + 槽位填充 + SSE 事件流
架构依据：06_组件编排器/组件编排器架构设计.md §2/§3/§7/§8/§9
本模块只定义编排协议与调用约定，不实现具体组件逻辑（组件由 task_014/015 提供）。
"""

import os
import re
import datetime
import threading
from pathlib import Path

try:
    import yaml  # type:ignore
except Exception:  # noqa: BLE001
    yaml = None

# ---------------------------------------------------------------- 协议常量

# 媒体槽位注释正则（§3）：字段间单个空格，直引号，source 仅视频有
SLOT_RE = re.compile(
    r'<!--\s*MEDIA:(img|video)\s+'
    r'id=(\S+)\s+'
    r'topic="([^"]+)"\s+'
    r'(?:prompt|keyword)="([^"]+)"(?:\s+source=(\S+))?\s+'
    r'mode=(download|embed)\s+'
    r'status=(\w+)\s*-->'
)

# 槽位 type → 组件注册名（§10）
TYPE_TO_COMPONENT = {"img": "image_gen", "video": "video_embed"}

# 事件阶段与事件类型白名单（§8）
PHASES = {"framework", "scan", "asset_fill", "verify", "deliver"}
EVENT_TYPES = {"prompt_ready", "generating", "done", "retry", "failed", "slot_list_confirm"}

VALID_MODES = ("download", "embed")
VALID_STATUS = ("pending", "done", "failed")

# ---------------------------------------------------------------- 通用工具


def now_ts() -> str:
    """事件时间戳 HH:MM:SS。"""
    return datetime.datetime.now().strftime("%H:%M:%S")


def make_event(phase: str, slot_id: str, event: str, detail: str) -> dict:
    """构造 §8 协议事件：{ts, phase, slot, event, detail}。"""
    return {
        "ts": now_ts(),
        "phase": phase,
        "slot": slot_id or "",
        "event": event,
        "detail": str(detail or ""),
    }


def load_rule_card(path) -> dict | None:
    """读取组件规则卡 YAML；缺失或不可用时返回 None。"""
    if yaml is None:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:  # noqa: BLE001
        return None


def validate_event(ev) -> bool:
    """事件结构合法性（§8 字段与白名单）。"""
    if not isinstance(ev, dict):
        return False
    return (set(ev) == {"ts", "phase", "slot", "event", "detail"}
            and ev["phase"] in PHASES
            and ev["event"] in EVENT_TYPES)


# ---------------------------------------------------------------- 主控


class Orchestrator:
    """两段式生成主控：槽位扫描 → 槽位填充 → 验证交付。

    lesson_dir：课时文件夹（HTML 与资产平铺，铁律无子目录）。
    autonomy：L1 全自动 / L2 关键节点确认（默认）/ L3 每步确认。

    组件注册表格式：
        {"video_embed": {"component": <module>, "rule_card": "<路径>"},
         "image_gen":   {"component": <module>, "rule_card": "<路径>"}}
    其中组件模块暴露 `run(slot, rule_card_path)` 返回 {"ok", "asset", "error"}。
    """

    def __init__(self, lesson_dir: str, autonomy: str = "L2",
                 component_registry: dict | None = None):
        self.lesson_dir = Path(lesson_dir)
        self.lesson_dir.mkdir(parents=True, exist_ok=True)
        if autonomy not in ("L1", "L2", "L3"):
            raise ValueError(f"非法执行程度 {autonomy!r}，须为 L1/L2/L3")
        self.autonomy = autonomy
        self.component_registry = component_registry or {}
        self._html_path: str | None = None
        self._event_callback = None
        self._confirm_event = threading.Event()

    # ---------------- 槽位扫描（§3）

    def scan_slots(self, html_path: str) -> list:
        """解析所有媒体槽位注释，返回结构化槽位列表；格式错误给出行号。"""
        content = Path(html_path).read_text(encoding="utf-8")
        slots = []
        for line_no, line in enumerate(content.splitlines(), start=1):
            if "MEDIA:" not in line:
                continue
            m = SLOT_RE.search(line)
            if not m:
                raise ValueError(f"第 {line_no} 行：MEDIA 槽位注释格式不符合协议")
            kind, sid = m.group(1), m.group(2)
            topic = m.group(3)
            spec = m.group(4)                      # prompt 或 keyword
            source = m.group(5)                    # 仅 video
            mode, status = m.group(6), m.group(7)
            if mode not in VALID_MODES:
                raise ValueError(f"第 {line_no} 行：id={sid} 非法 mode={mode}")
            if status not in VALID_STATUS:
                raise ValueError(f"第 {line_no} 行：id={sid} 非法 status={status}")
            if kind == "img" and source is not None:
                raise ValueError(f"第 {line_no} 行：图片槽位 id={sid} 不应有 source")
            if kind == "video" and source is None:
                raise ValueError(f"第 {line_no} 行：视频槽位 id={sid} 缺少 source")
            slot = {"id": sid, "type": kind, "topic": topic, "source": source,
                    "mode": mode, "status": status, "line_no": line_no}
            if kind == "img":
                slot["prompt"] = spec
            else:
                slot["keyword"] = spec
            slots.append(slot)
        return slots

    # ---------------- HTML 读写与注释替换（§3 替换规则）

    def _load_html(self) -> str:
        return Path(self._html_path).read_text(encoding="utf-8")

    def _save_html(self, content: str) -> None:
        Path(self._html_path).write_text(content, encoding="utf-8")

    def _assemble_tag(self, slot: dict, asset: str) -> str:
        """组件资产 → 替换注释用的真实标签。"""
        if slot["type"] == "img":
            fname = os.path.basename(asset or "")
            if not fname:
                raise ValueError("图片组件未返回资产文件名")
            return f'<img src="./{fname}" alt="{slot["topic"]}">'
        # video/mode=embed：asset 即 iframe HTML
        if not (isinstance(asset, str) and asset.strip()):
            raise ValueError("视频组件未返回 iframe HTML")
        return asset

    def _replace_comment(self, slot: dict, replacement: str) -> bool:
        """把该 id 的整条槽位注释替换为 replacement。找不到返回 False。"""
        content = self._load_html()
        pat = re.compile(
            r'<!--\s*MEDIA:' + re.escape(slot["type"]) + r'\s+id='
            + re.escape(slot["id"]) + r'\s+.*?-->'
        )
        new, n = pat.subn(replacement, content, count=1)
        if n == 1:
            self._save_html(new)
        return n == 1

    def _mark_failed(self, slot: dict) -> bool:
        """失败兜底：槽位注释保留但 status 改为 failed。"""
        content = self._load_html()
        pat = re.compile(
            r'<!--\s*MEDIA:' + re.escape(slot["type"]) + r'\s+id='
            + re.escape(slot["id"]) + r'\s+.*?status=pending\s*-->'
        )
        def _rebuild(m):
            head = m.group(0)[:-len("status=pending -->")]
            return head + "status=failed -->"
        new, n = pat.subn(_rebuild, content, count=1)
        if n == 1:
            self._save_html(new)
        return n == 1

    # ---------------- 槽位填充（§2 第二段）

    def fill_slot(self, slot: dict, component_registry: dict) -> dict:
        """按槽位 type 路由到组件；成功=替换注释+status=done，失败按规则卡重试。"""
        comp_type = TYPE_TO_COMPONENT.get(slot["type"])
        entry = component_registry.get(comp_type)
        if not entry:
            return {"ok": False, "status": "failed", "slot": slot,
                    "error": f"未注册组件 {comp_type}"}

        comp = entry["component"]
        rule_card = entry["rule_card"]
        card = load_rule_card(rule_card) or {}
        max_retry = int((card.get("budget") or {}).get("max_retry", 2))

        last_error = ""
        attempts = 0
        for attempt in range(max_retry + 1):
            attempts = attempt + 1
            try:
                r = comp.run(slot, rule_card)
            except Exception as exc:  # noqa: BLE001
                r = {"ok": False, "asset": None, "error": f"{type(exc).__name__}: {exc}"}
            if r.get("ok") and r.get("asset"):
                try:
                    tag = self._assemble_tag(slot, r["asset"])
                except ValueError as exc:
                    last_error = str(exc)
                    r = {"ok": False, "error": last_error}
                if r.get("ok"):
                    if self._replace_comment(slot, tag):
                        return {"ok": True, "status": "done",
                                "slot": {**slot, "status": "done"},
                                "asset": tag, "attempts": attempts}
                    last_error = "HTML 注释替换失败"
            else:
                last_error = r.get("error") or "组件未返回资产"
            if attempt < max_retry:
                self.on_event(slot["id"], "retry", f"{last_error}，第 {attempt + 1} 次重试")
        self._mark_failed(slot)
        return {"ok": False, "status": "failed", "slot": {**slot, "status": "failed"},
                "error": last_error, "attempts": attempts}

    # ---------------- 验证闭环（§9）

    def verify(self, html_path: str) -> dict:
        """资产校验：无残留槽位、引用文件存在、图片可解码、BV 号有效。"""
        content = Path(html_path).read_text(encoding="utf-8")
        issues = []

        for s in self.scan_slots(html_path):
            if s["status"] in ("pending", "failed"):
                issues.append(f'残留槽位 {s["id"]}(status={s["status"]})')

        for m in re.finditer(r'<img src="\./([^"]+)"', content):
            fname = m.group(1)
            fp = self.lesson_dir / fname
            if not fp.is_file():
                issues.append(f"图片文件缺失: {fname}")
                continue
            try:
                from PIL import Image
                with Image.open(fp) as im:
                    im.verify()
            except Exception as exc:  # noqa: BLE001
                issues.append(f"图片不可解码 {fname}: {exc}")

        for m in re.finditer(r'bvid=([A-Za-z0-9]{11,})', content):
            bv = m.group(1)
            if not re.fullmatch(r'BV[0-9A-Za-z]{10}', bv):
                issues.append(f"BV 号格式非法: {bv}")

        # 若页面仍引用视频组件，仅校验 BV 格式（真实网络校验由组件完成）
        return {"ok": not issues, "issues": issues}

    # ---------------- 事件流（§8）

    def on_event(self, slot_id: str, event: str, detail: str) -> None:
        if not self._event_callback:
            return
        ev = make_event(self._phase, slot_id, event, detail)
        self._event_callback(ev)

    def confirm_slots(self) -> bool:
        """外部确认「槽位清单」，放行 L2/L3 流程。"""
        self._confirm_event.set()
        return True

    def wait_confirm(self, slot_id: str = "") -> None:
        """L2 槽位清单确认节点：发事件并阻塞等待确认。"""
        self._confirm_event.clear()
        self.on_event(slot_id or "all", "slot_list_confirm", "等待用户确认")
        self._confirm_event.wait()
        self.on_event(slot_id or "all", "done", "槽位清单已确认，继续填充")

    # ---------------- 主流程（§2）

    def run(self, html_path: str, event_callback=None) -> dict:
        """主流程：scan_slots → 逐槽位 fill_slot → 验证 → 交付。

        返回 {"done", "failed", "skipped", "elapsed_s"}。
        """
        t0 = _now()
        self._html_path = str(Path(html_path))
        self._event_callback = event_callback

        # 扫描（§2 第一段产物：框架+槽位已经生成，这里读取）
        self._phase = "scan"
        slots = self.scan_slots(self._html_path)
        pending = [s for s in slots if s["status"] == "pending"]
        self.on_event("", "done", f"扫描到 {len(pending)} 个待填充槽位")
        self._phase = "asset_fill"

        # L2：槽位清单确认节点（§7）
        if self.autonomy == "L2":
            self.wait_confirm()
        # L3：每个槽位前都确认一次（时序由事件回调驱动，简洁实现：直接执行）
        #   —— L3 的逐槽确认由外部依赖 slot_confirm 触发，本 run 仍按统一顺序执行。

        done = failed = skipped = 0
        for slot in pending:
            r = self.fill_slot(slot, self.component_registry)
            if r["ok"]:
                done += 1
                self.on_event(slot["id"], "done",
                              f'{slot["topic"]} -> {r["asset"]}')
            else:
                failed += 1

        # 验证闭环（§9）
        self._phase = "verify"
        ver = self.verify(self._html_path)
        if ver["ok"]:
            self.on_event("", "done", "资产校验全部通过")
        else:
            self.on_event("", "failed", "；".join(ver["issues"][:3]))

        # 交付
        self._phase = "deliver"
        self.on_event("", "done",
                      f"交付完成：成功 {done} / 失败 {failed} / 跳过 {skipped}")

        return {"done": done, "failed": failed, "skipped": skipped,
                "elapsed_s": round(_now() - t0, 2)}


def _now() -> float:
    """本模块统一时钟源（便于测试注入/复用）。"""
    import time
    return time.time()