# -*- coding: utf-8 -*-
"""canvas_server.py — 画布观察窗 SSE 直播服务

编排器真实事件流 → HTTP SSE → 浏览器画布观察窗（canvas/index.html）。
职责：托管画布页面 + 课时目录 /media/ 预览图 + L2 确认端点。

用法：
  python canvas_server.py --topic "英文数字" --lesson L27 --card image_gen_doubao.yaml
  # 打开 http://127.0.0.1:8791/ 观看直播；L2 档位时点底部按钮确认放行

架构依据：06_组件编排器/组件编排器架构设计.md §7/§8（事件协议 {ts,phase,slot,event,detail}）
零第三方依赖：标准库 http.server + queue 广播。
"""

import argparse
import json
import mimetypes
import os
import queue
import re
import sys
import threading
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS_DIR))

from lesson_framework import write_lesson  # noqa: E402
from orchestrator import Orchestrator      # noqa: E402
from run_pipeline import _default_registry  # noqa: E402

try:
    import yaml  # type: ignore
except Exception:  # noqa: BLE001
    yaml = None

DEFAULT_PORT = 8791
CANVAS_DIR = _THIS_DIR / "canvas"

mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/avif", ".avif")

# ---------------------------------------------------------------- 事件广播中心


class SSEHub:
    """pipeline 事件回调 → 所有 SSE 客户端队列（每连接一队）。

    内置回放缓存（deque 最近 200 条）：晚打开画布页面的客户端先补发
    已发生的事件（framework/scan 阶段），再续接实时流，保证时间线完整。
    """

    _HISTORY_LEN = 200

    def __init__(self) -> None:
        self._clients: set[queue.Queue] = set()
        self._lock = threading.Lock()
        self._history: deque[dict] = deque(maxlen=self._HISTORY_LEN)

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            for ev in self._history:
                q.put(ev)
            self._clients.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._clients.discard(q)

    def broadcast(self, ev: dict) -> None:
        with self._lock:
            self._history.append(ev)
            clients = list(self._clients)
        for q in clients:
            q.put(ev)


# ---------------------------------------------------------------- 事件增强


_SITE_CACHE: dict[str, str] = {}


def _site_of(rule_card: str) -> str:
    """规则卡 site 字段（画布「调度站点」展示），带缓存。"""
    if rule_card not in _SITE_CACHE:
        site = ""
        if yaml:
            try:
                c = yaml.safe_load(Path(rule_card).read_text(encoding="utf-8"))
                site = (c or {}).get("site", "") or ""
            except Exception:  # noqa: BLE001
                site = ""
        _SITE_CACHE[rule_card] = site
    return _SITE_CACHE[rule_card]


def enrich(ev: dict, image_card: str) -> dict:
    """给事件补画布需要的可选字段（不动原始字段）：
    - asset_fill 阶段补 site（规则卡站点名）
    - 槽位 done 事件从 detail 的 <img src="./x"> 提取 preview 路径
    - scan done 事件解析槽位总数 total
    """
    ev = dict(ev)
    if ev.get("phase") == "asset_fill" and ev.get("slot"):
        site = _site_of(image_card)
        if site:
            ev["site"] = site
        if ev.get("event") == "done":
            m = re.search(r'src="\./([^"]+)"', ev.get("detail", ""))
            if m:
                ev["preview"] = f"/media/{m.group(1)}"
    if (ev.get("phase") == "scan" and ev.get("event") == "done" and not ev.get("slot")):
        m = re.search(r"扫描到 (\d+) 个待填充槽位", ev.get("detail", ""))
        if m:
            ev["total"] = int(m.group(1))
    return ev


# ---------------------------------------------------------------- HTTP 服务


class CanvasHandler(BaseHTTPRequestHandler):
    server: "CanvasHTTPServer"

    # ---------------- 静态资源

    def _serve_file(self, root: Path, rel: str) -> None:
        target = (root / rel).resolve()
        root_r = str(root.resolve())
        if not str(target).startswith(root_r) or not target.is_file():
            self.send_error(404)
            return
        ctype, _ = mimetypes.guess_type(str(target))
        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(target.stat().st_size))
        self.end_headers()
        with open(target, "rb") as f:
            self.wfile.write(f.read())

    # ---------------- 路由

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/health":
            # 统一健康检查（Monorepo runtime 约定）
            body = json.dumps({"status": "ok", "service": "orchestrator", "version": "1.0"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/orchestrator/stream":
            self._stream()
        elif path.startswith("/media/"):
            self._serve_file(self.server.lesson_dir, path[len("/media/"):])
        elif path in ("/", "/index.html"):
            self._serve_file(CANVAS_DIR, "index.html")
        else:
            self._serve_file(CANVAS_DIR, path.lstrip("/"))

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/orchestrator/confirm":
            orch = self.server.orchestrator
            ok = bool(orch and orch.confirm_slots())
            body = json.dumps({"ok": ok}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    # ---------------- SSE 端点

    def _stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = self.server.hub.subscribe()
        try:
            while True:
                try:
                    ev = q.get(timeout=15)
                    payload = f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                    self.wfile.write(payload.encode("utf-8"))
                    self.wfile.flush()
                    if ev.get("event") == "stream_end":
                        break
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # 客户端断开（关页/断网），静默退订
        finally:
            self.server.hub.unsubscribe(q)

    def log_message(self, fmt: str, *args) -> None:  # noqa: N802
        pass  # 安静模式：SSE 心跳与媒体请求不打日志


class CanvasHTTPServer(ThreadingHTTPServer):
    def __init__(self, addr, lesson_dir: Path, hub: SSEHub):
        self.lesson_dir = lesson_dir
        self.hub = hub
        self.orchestrator: Orchestrator | None = None
        super().__init__(addr, CanvasHandler)


# ---------------------------------------------------------------- pipeline 线程


def _now_ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def run_pipeline_live(topic: str, lesson_dir: Path, lesson: str, style: str,
                      autonomy: str, image_card: str, hub: SSEHub,
                      canvas_server: CanvasHTTPServer) -> dict:
    """后台线程：框架生成 → 编排器填充 → 事件广播 → stream_end。"""
    # 1. 第一段：框架（§2）
    hub.broadcast({"ts": _now_ts(), "phase": "framework", "slot": "main",
                   "event": "done", "detail": f"生成 7 段式课件骨架：{topic}"})
    fw = write_lesson(str(lesson_dir), topic, lesson, style)
    html_path = fw["html_path"]
    hub.broadcast({"ts": _now_ts(), "phase": "framework", "slot": "main",
                   "event": "done",
                   "detail": f"框架完成：{Path(html_path).name}，含 {len(fw['slots'])} 个媒体槽位"})

    # 2. 第二段：编排器（引用挂到 server 上，供 L2 确认端点调用）
    registry = _default_registry(image_card)
    orch = Orchestrator(str(lesson_dir), autonomy, registry)
    canvas_server.orchestrator = orch

    def cb(ev: dict) -> None:
        hub.broadcast(enrich(ev, os.path.join(_THIS_DIR, "rules", image_card)))

    result = orch.run(html_path, event_callback=cb)

    # 3. 收尾：stream_end 事件 → 客户端 es.close()（不会触发 mock 回退）
    hub.broadcast({
        "ts": _now_ts(), "phase": "deliver", "slot": "main", "event": "stream_end",
        "detail": f"管线完成：成功 {result['done']} / 失败 {result['failed']}"
                  f" / 耗时 {result['elapsed_s']}s",
    })
    return result


# ---------------------------------------------------------------- 入口


def main() -> None:
    ap = argparse.ArgumentParser(
        description="画布观察窗 SSE 直播服务 — 编排器真实事件流",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="启动后打开 http://127.0.0.1:<port>/ 观看画布直播。",
    )
    ap.add_argument("--topic", "-t", default="", help="课程主题")
    ap.add_argument("--serve-only", action="store_true",
                    help="只起画布服务不跑 pipeline（runtime 常驻模式）")
    ap.add_argument("--lesson", "-l", default="", help="课时号，如 L27；缺省自动生成")
    ap.add_argument("--style", "-s", default="flat cartoon, 儿童教材插画风, 明亮色调",
                    help="图片风格锁")
    ap.add_argument("--autonomy", "-a", default="L2", choices=["L1", "L2", "L3"],
                    help="执行档位 (L1=全自动, L2=关键节点确认, L3=每步确认)")
    ap.add_argument("--card", "-c", default="image_gen_doubao.yaml",
                    help="图片规则卡文件名")
    ap.add_argument("--dir", "-d", default=None, help="课时输出目录（缺省自动创建）")
    ap.add_argument("--port", "-p", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()

    if not args.topic and not args.serve_only:
        ap.error("--topic 必填（或使用 --serve-only 只起画布服务）")

    lid = args.lesson.strip() or f"L{datetime.now().strftime('%Y%m%d%H%M%S')}"
    # 产物默认输出到 仓库根/data/orchestrator/（数据与代码分离；--dir 可指定）
    _DATA_DIR = _THIS_DIR.parent.parent / "data" / "orchestrator"
    lesson_dir = Path(args.dir) if args.dir else _DATA_DIR / lid
    lesson_dir.mkdir(parents=True, exist_ok=True)

    hub = SSEHub()
    server = CanvasHTTPServer(("127.0.0.1", args.port), lesson_dir, hub)
    print(f"🎬 画布观察窗直播：http://127.0.0.1:{args.port}/")
    print(f"   课时目录：{lesson_dir}")
    print(f"   主题：{args.topic or '(serve-only)'} | 档位：{args.autonomy} | 规则卡：{args.card}")
    print("   画布页面先打开会显示空白，pipeline 事件到达后自动渲染。")

    if not args.serve_only:
        threading.Thread(
            target=run_pipeline_live,
            args=(args.topic, lesson_dir, lid, args.style, args.autonomy,
                  args.card, hub, server),
            daemon=True,
        ).start()

    # 心跳上报到中央平台（:8000），让「组件编排器画布」卡片显示在线
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "search_gateway"))
        import heartbeat as _hb
        _hb.start_heartbeat(
            gateway_id="canvas_orchestrator", name="组件编排器画布", icon="🎬",
            description="画布观察窗 SSE 直播 — 课件生成实时事件流", port=args.port)
        print("❤️  心跳上报已启动 (central " + _hb.CENTRAL_URL + ")")
    except Exception as _e:  # noqa: BLE001
        print("⚠️  心跳上报未启动: " + str(_e)[:80])

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
