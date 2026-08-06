# -*- coding: utf-8 -*-
"""
AI Hub 中央管理平台 — FastAPI 主服务
端口: 8000
功能: 网关注册/导航/GitHub 集成/飞书同步/统一入口

依赖: pip install fastapi uvicorn httpx
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).parent
PROJECT_DIR = BASE_DIR.parent
CONFIG_DIR = PROJECT_DIR / "config"
GATEWAYS_DIR = PROJECT_DIR / "02_网关实例"

# 确保配置目录存在
CONFIG_DIR.mkdir(exist_ok=True)

app = FastAPI(title="AI Hub 中央平台", version="1.0.0")

# 挂载静态文件（管理面板）
dashboard_dir = BASE_DIR / "dashboard"
if dashboard_dir.exists():
    app.mount("/dashboard", StaticFiles(directory=str(dashboard_dir)), name="dashboard")

# 挂载各网关实例的静态页面（通过 /gateway/{name}/ 访问）
if GATEWAYS_DIR.exists():
    for gw in GATEWAYS_DIR.iterdir():
        if gw.is_dir():
            html_file = gw / "hub_page.html"
            if html_file.exists():
                app.mount(f"/gateway/{gw.name}", StaticFiles(directory=str(gw)), name=f"gw_{gw.name}")


# ---------------------------------------------------------------- 配置读写

def load_json(path, default=None):
    """读取 JSON 配置文件。"""
    if default is None:
        default = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    """保存 JSON 配置文件。"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 网关注册表

GATEWAYS_JSON = CONFIG_DIR / "gateways.json"


def get_gateways():
    return load_json(GATEWAYS_JSON, {"gateways": {}})


def save_gateways(data):
    save_json(GATEWAYS_JSON, data)


# ---------------------------------------------------------------- 路由

@app.get("/", response_class=HTMLResponse)
async def index():
    """导航首页 — 所有网关卡片。"""
    gateways = get_gateways().get("gateways", {})
    cards = []
    for gid, gw in gateways.items():
        status = gw.get("status", "offline")
        status_class = "online" if status == "online" else "offline"
        status_text = "在线" if status == "online" else "离线"
        cards.append(f"""
        <div class="card {status_class}" onclick="window.open('{gw.get('url', '')}', '_blank')">
            <div class="card-icon">{gw.get('icon', '🔗')}</div>
            <div class="card-name">{gw.get('name', gid)}</div>
            <div class="card-desc">{gw.get('description', '')}</div>
            <div class="card-status">{status_text} · 端口 {gw.get('port', '?')}</div>
        </div>""")

    cards_html = "\n".join(cards) if cards else '<p style="color:#888">暂无已注册的网关</p>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Hub — 中央导航</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       background:#0a0a0f; color:#e0e0e0; min-height:100vh; padding:40px; }}
.header {{ text-align:center; margin-bottom:48px; }}
.header h1 {{ font-size:32px; font-weight:700; color:#fff; margin-bottom:8px; }}
.header p {{ color:#888; font-size:14px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr));
         gap:20px; max-width:1200px; margin:0 auto; }}
.card {{ background:#14141f; border:1px solid #222; border-radius:16px;
         padding:24px; cursor:pointer; transition:all .2s; }}
.card:hover {{ border-color:#444; transform:translateY(-2px); }}
.card.online {{ border-left:3px solid #4ade80; }}
.card.offline {{ border-left:3px solid #666; opacity:.6; }}
.card-icon {{ font-size:32px; margin-bottom:12px; }}
.card-name {{ font-size:18px; font-weight:600; color:#fff; margin-bottom:6px; }}
.card-desc {{ font-size:13px; color:#888; margin-bottom:12px; }}
.card-status {{ font-size:12px; color:#666; }}
.footer {{ text-align:center; margin-top:48px; color:#444; font-size:12px; }}
</style>
</head>
<body>
<div class="header">
    <h1>🌐 AI Hub</h1>
    <p>统一 AI 聚合管理平台 · 中央导航</p>
</div>
<div class="grid">{cards_html}</div>
<div class="footer">AI Hub v1.0 · 局域网模式 · <a href="/docs" style="color:#666">API 文档</a></div>
</body>
</html>"""


@app.get("/api/gateways")
async def list_gateways():
    """网关列表。"""
    return get_gateways()


@app.post("/api/gateways")
async def register_gateway(request: Request):
    """注册新网关。"""
    body = await request.json()
    gid = body.get("id") or body.get("name", "").lower().replace(" ", "_")
    if not gid:
        raise HTTPException(400, "缺少网关 id 或 name")

    data = get_gateways()
    data["gateways"][gid] = {
        "name": body.get("name", gid),
        "icon": body.get("icon", "🔗"),
        "description": body.get("description", ""),
        "port": body.get("port", 3000),
        "url": body.get("url", f"http://localhost:{body.get('port', 3000)}"),
        "status": "online",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "last_seen": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    save_gateways(data)
    return {"ok": True, "id": gid}


@app.post("/api/gateways/{gid}/heartbeat")
async def heartbeat(gid: str):
    """网关心跳上报。"""
    data = get_gateways()
    if gid not in data["gateways"]:
        raise HTTPException(404, f"网关 {gid} 未注册")
    data["gateways"][gid]["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    data["gateways"][gid]["status"] = "online"
    save_gateways(data)
    return {"ok": True}


@app.post("/api/gateways/{gid}/unregister")
async def unregister_gateway(gid: str):
    """注销网关。"""
    data = get_gateways()
    if gid in data["gateways"]:
        data["gateways"][gid]["status"] = "offline"
        save_gateways(data)
    return {"ok": True}


@app.get("/api/gateways/{gid}/health")
async def gateway_health(gid: str):
    """检查网关健康状态。"""
    import httpx
    data = get_gateways()
    gw = data["gateways"].get(gid)
    if not gw:
        raise HTTPException(404, f"网关 {gid} 未注册")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{gw['url']}/api/health")
            return {"id": gid, "status": "online", "detail": r.json()}
    except Exception as e:
        return {"id": gid, "status": "offline", "error": str(e)[:100]}


# ---------------------------------------------------------------- GitHub 集成

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")


@app.get("/api/github/repos")
async def github_repos():
    """GitHub 仓库列表。"""
    import httpx
    if not GITHUB_TOKEN:
        return {"error": "未配置 GITHUB_TOKEN 环境变量", "repos": []}
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://api.github.com/user/repos?per_page=30&sort=updated",
            headers={"Authorization": f"token {GITHUB_TOKEN}",
                     "Accept": "application/vnd.github.v3+json"}
        )
        if r.status_code == 200:
            repos = [{"name": x["name"], "url": x["html_url"],
                      "language": x.get("language"), "description": x.get("description"),
                      "updated_at": x["updated_at"]} for x in r.json()]
            return {"repos": repos}
        return {"error": f"GitHub API 错误: {r.status_code}", "repos": []}


# ---------------------------------------------------------------- 飞书同步

@app.post("/api/feishu/sync")
async def feishu_sync():
    """手动触发飞书数据同步。"""
    # TODO: 实现飞书同步逻辑
    return {"ok": True, "message": "同步功能待实现"}


# ---------------------------------------------------------------- 统计

@app.get("/api/stats")
async def stats():
    """全局统计。"""
    gateways = get_gateways().get("gateways", {})
    online = sum(1 for g in gateways.values() if g.get("status") == "online")
    return {
        "total_gateways": len(gateways),
        "online_gateways": online,
        "offline_gateways": len(gateways) - online,
    }


# ---------------------------------------------------------------- 启动

if __name__ == "__main__":
    print("🌐 AI Hub 中央平台启动中...")
    print(f"   导航首页: http://localhost:8000")
    print(f"   API 文档: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)
