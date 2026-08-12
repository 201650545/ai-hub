# -*- coding: utf-8 -*-
"""
AI Hub Runtime CLI — 读 config/runtime.yaml（Desired State）启停三服务。

用法:
  python -m runtime.cli status           查看三服务状态
  python -m runtime.cli start --all      按序启动全部服务
  python -m runtime.cli start central    启动指定服务
  python -m runtime.cli stop --all       停止全部服务
  python -m runtime.cli restart --all    重启全部服务
  python -m runtime.cli doctor           全面诊断

设计约定:
  - runtime.yaml 是唯一静态真源，运行程序绝不改写它
  - 动态状态（PID/status/started_at）写 data/runtime/state.json
  - PID 文件在 data/runtime/pids/<name>.pid，按 PID 停止（不用 taskkill 端口）
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None
try:
    import psutil
except ImportError:
    psutil = None

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT / "config" / "runtime.yaml"
PID_DIR = ROOT / "data" / "runtime" / "pids"
STATE_FILE = ROOT / "data" / "runtime" / "state.json"
LOG_DIR = ROOT / "logs"
HEALTH_TIMEOUT = 90  # 单服务健康等待上限（秒，search_gateway 冷启动可达 60s+）
HEALTH_INTERVAL = 2  # 轮询间隔


# ---------------------------------------------------------------- 配置

def load_config():
    if yaml is None:
        print("❌ 缺少 pyyaml，请先: pip install pyyaml")
        sys.exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not cfg or "services" not in cfg:
        print(f"❌ {CONFIG_FILE} 缺少 services 段")
        sys.exit(1)
    return cfg


def ordered_services(cfg):
    """按 startup.order 排序的服务名列表。"""
    services = cfg["services"]
    return sorted(services.keys(), key=lambda n: services[n]["startup"]["order"])


def project_python(cfg):
    return cfg.get("project", {}).get("python", "python")


# ---------------------------------------------------------------- 状态

def _pid_file(name):
    return PID_DIR / f"{name}.pid"


def _read_pid(name):
    p = _pid_file(name)
    if not p.exists():
        return None
    try:
        return int(p.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def _is_alive(pid):
    if pid is None:
        return False
    try:
        if psutil is not None:
            return psutil.pid_exists(pid)
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def _set_state(name, status, pid=None, started_at=None, error=""):
    state = _load_state()
    entry = {"status": status, "pid": pid, "started_at": started_at, "error": error}
    if status == "stopped":
        entry = {"status": status, "pid": None, "started_at": None, "error": error}
    state[name] = entry
    _save_state(state)


# ---------------------------------------------------------------- 健康检查

def health_url(svc):
    base = svc["url"].rstrip("/")
    path = svc.get("health", {}).get("path", "/health")
    return f"{base}{path}"


def check_health(svc, timeout=6):
    url = health_url(svc)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.getcode() == svc.get("health", {}).get("ok", 200)
    except Exception:  # noqa: BLE001
        return False


def _log_path(name):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / f"{name}.log"


# ---------------------------------------------------------------- 动作

def do_start(cfg, names):
    services = cfg["services"]
    py = project_python(cfg)
    PID_DIR.mkdir(parents=True, exist_ok=True)
    started = []
    for name in names:
        svc = services[name]
        if check_health(svc):
            print(f"  ✅ {name} 已在运行（健康检查通过），跳过")
            continue
        pid = _read_pid(name)
        if pid and _is_alive(pid):
            print(f"  ⚠️ {name} PID {pid} 存在但健康检查未过，先停止旧进程")
            _kill(pid)
            time.sleep(1)
        log = open(_log_path(name), "a", encoding="utf-8")
        cwd = ROOT / svc["cwd"]
        if not cwd.exists():
            print(f"  ❌ {name} 工作目录不存在: {cwd}")
            continue
        print(f"  ▶ 启动 {name}（{svc['label']} :{svc['port']}）...")
        cmd = shlex.split(svc["command"]) if isinstance(svc["command"], str) else list(svc["command"])
        proc = subprocess.Popen(
            [py] + cmd,
            cwd=str(cwd),
            stdout=log, stderr=log,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        _pid_file(name).write_text(str(proc.pid), encoding="utf-8")
        _set_state(name, "starting", pid=proc.pid,
                   started_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        # 等待健康
        ok = False
        deadline = time.time() + HEALTH_TIMEOUT
        while time.time() < deadline:
            if check_health(svc):
                ok = True
                break
            if proc.poll() is not None:
                break  # 进程退出了，别干等
            time.sleep(HEALTH_INTERVAL)
        if ok:
            _set_state(name, "running", pid=proc.pid,
                       started_at=time.strftime("%Y-%m-%d %H:%M:%S"))
            print(f"  ✅ {name} 就绪 ({svc['url']})")
        else:
            _set_state(name, "failed", pid=proc.pid,
                       error=f"健康检查未通过（{HEALTH_TIMEOUT}s）")
            print(f"  ❌ {name} 健康检查未通过，详见 {_log_path(name)}")
        started.append(name)
    return started


def _kill(pid):
    """按 PID 停止（psutil 优先，兜底 taskkill）。"""
    if psutil is not None and psutil.pid_exists(pid):
        try:
            p = psutil.Process(pid)
            p.terminate()
            p.wait(timeout=8)
            return
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
            try:
                p.kill()
                return
            except Exception:  # noqa: BLE001
                pass
    os.system(f'taskkill /PID {pid} /F >nul 2>&1')


def do_stop(cfg, names):
    services = cfg["services"]
    for name in names:
        pid = _read_pid(name)
        svc = services[name]
        if pid and _is_alive(pid):
            _kill(pid)
            print(f"  ⏹ 已停止 {name}（PID {pid}）")
        else:
            print(f"  — {name} 未在运行")
        _set_state(name, "stopped")
        p = _pid_file(name)
        if p.exists():
            p.unlink()


def do_status(cfg):
    services = cfg["services"]
    print(f"{'服务':<16}{'端口':<7}{'PID':<8}{'健康':<6}状态")
    print("-" * 50)
    all_ok = True
    for name in ordered_services(cfg):
        svc = services[name]
        pid = _read_pid(name)
        healthy = check_health(svc)
        if pid and _is_alive(pid) and healthy:
            status = "运行中"
            _set_state(name, "running", pid=pid,
                       started_at=_load_state().get(name, {}).get("started_at") or
                       time.strftime("%Y-%m-%d %H:%M:%S"))
        elif pid and _is_alive(pid):
            status = "进程在,健康未过"
        elif healthy:
            status = "健康但无PID"
        else:
            status = "已停止"
            all_ok = False
        print(f"{name:<16}{svc['port']:<7}{(str(pid) if pid else '-'):<8}{'✅' if healthy else '❌':<6}{status}")
    return all_ok


def do_doctor(cfg):
    print("🔍 AI Hub Runtime Doctor")
    print("=" * 50)
    # 1. 配置文件
    if CONFIG_FILE.exists():
        print(f"  ✅ 配置: {CONFIG_FILE}")
    else:
        print(f"  ❌ 配置缺失: {CONFIG_FILE}")
        return
    # 2. 目录
    for d in (ROOT / "services", PID_DIR, LOG_DIR):
        print(f"  {'✅' if d.exists() else '❌'} 目录: {d.relative_to(ROOT) if d.is_relative_to(ROOT) else d}")
    # 3. 依赖
    print(f"  {'✅' if yaml else '❌'} pyyaml")
    print(f"  {'✅' if psutil else '❌'} psutil")
    # 4. 服务健康
    for name in ordered_services(cfg):
        svc = cfg["services"][name]
        ok = check_health(svc)
        print(f"  {'✅' if ok else '❌'} {name} {svc['url']}{health_url(svc)}")
    print("=" * 50)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="AI Hub Runtime CLI")
    ap.add_argument("action", choices=["start", "stop", "restart", "status", "doctor"])
    ap.add_argument("names", nargs="*", default=[], help="服务名（缺省或 --all = 全部）")
    ap.add_argument("--all", action="store_true", help="全部服务")
    args = ap.parse_args()

    cfg = load_config()
    all_names = ordered_services(cfg)

    if args.action == "status":
        do_status(cfg)
        return

    if args.action == "doctor":
        do_doctor(cfg)
        return

    names = [n for n in args.names if n in cfg["services"]]
    if args.all or not args.names:
        names = all_names
    if not names:
        print("❌ 没有匹配的服务名（可选: " + ", ".join(all_names) + " 或 --all）")
        sys.exit(1)

    if args.action == "start":
        do_start(cfg, names)
    elif args.action == "stop":
        do_stop(cfg, names)
    elif args.action == "restart":
        do_stop(cfg, names)
        print("  — 等待 1 秒后重启...")
        time.sleep(1)
        do_start(cfg, names)


if __name__ == "__main__":
    main()
