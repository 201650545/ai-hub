# -*- coding: utf-8 -*-
"""
AI Hub 中央管理平台 — FastAPI 主服务
端口: 8000
功能: 网关注册/导航/GitHub 集成/飞书同步/统一入口

依赖: pip install fastapi uvicorn httpx
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).parent
PROJECT_DIR = BASE_DIR.parent.parent
CONFIG_DIR = PROJECT_DIR / "config"

# 确保配置目录存在
CONFIG_DIR.mkdir(exist_ok=True)

app = FastAPI(title="AI Hub 中央平台", version="1.0.0")

# 挂载静态文件（管理面板）
dashboard_dir = BASE_DIR / "dashboard"
if dashboard_dir.exists():
    app.mount("/dashboard", StaticFiles(directory=str(dashboard_dir)), name="dashboard")

# 挂载共享设计系统（theme.css 唯一真源）
static_dir = BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# 挂载应用（AI 画布 / 词境挖空 等前端应用，静态单页）
apps_dir = PROJECT_DIR / "apps"
if apps_dir.exists():
    for app_name in ("ai-canvas", "word-cloze"):
        app_path = apps_dir / app_name
        if app_path.exists():
            app.mount(f"/{app_name}", StaticFiles(directory=str(app_path)), name=app_name)


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

@app.get("/health")
async def health():
    """统一健康检查（Monorepo runtime 约定）。"""
    return {"status": "ok", "service": "central", "version": "1.0"}


@app.get("/", response_class=HTMLResponse)
async def index():
    """导航首页 — 苹果官网风极简线条。"""
    gateways = get_gateways().get("gateways", {})
    cards = []
    for gid, gw in gateways.items():
        status = gw.get("status", "offline")
        is_online = status == "online"
        dot_cls = "dot-on" if is_online else "dot-off"
        status_text = "在线" if is_online else "离线"
        cards.append(f"""
        <div class="gw-card" onclick="window.open('{gw.get('url', '')}', '_blank')">
            <div class="gw-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/></svg>
            </div>
            <div class="gw-body">
                <div class="gw-name">{gw.get('name', gid)}</div>
                <div class="gw-desc">{gw.get('description', '')}</div>
                <div class="gw-status"><span class="status-dot {dot_cls}"></span>{status_text} · 端口 {gw.get('port', '?')}</div>
            </div>
        </div>""")

    cards_html = "\n".join(cards) if cards else '<p class="empty">暂无已注册的网关</p>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Hub — 中央导航</title>
<link rel="stylesheet" href="/static/theme.css">
<link rel="stylesheet" href="/static/nav-skins.css">
<script>document.documentElement.setAttribute('data-theme',localStorage.getItem('theme')||'light')</script>
<style>
  body {{ padding: 0 24px 64px; }}
  .theme-toggle {{ position: fixed; top: 24px; right: 24px; z-index: 200; box-shadow: var(--shadow-sm); }}
  .hero {{ text-align: center; padding: 112px 0 64px; max-width: 980px; margin: 0 auto; }}
  .hero h1 {{ font-size: 56px; font-weight: 700; letter-spacing: -0.015em; color: var(--text-primary); margin-bottom: 16px; }}
  .hero p {{ font-size: 21px; color: var(--text-secondary); font-weight: 400; max-width: 640px; margin: 0 auto 32px; line-height: 1.4; }}
  .hero .cta {{ display: inline-flex; align-items: center; gap: 8px; }}
  .hero .meta {{ margin-top: 14px; font-size: 14px; color: var(--text-tertiary); }}

  .section {{ max-width: 1080px; margin: 0 auto 64px; }}
  .section-label {{ font-size: 12px; font-weight: 600; color: var(--accent); letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 8px; }}
  .section-title {{ font-size: 32px; font-weight: 700; letter-spacing: -0.01em; color: var(--text-primary); margin-bottom: 32px; }}

  .app-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 24px; }}
  .app-card {{ background: var(--bg-elevated); border: 1px solid var(--line); border-radius: var(--radius-lg);
              padding: 32px; cursor: pointer; transition: transform var(--duration-fast) var(--ease), border-color var(--duration-fast) var(--ease); box-shadow: var(--shadow-sm); }}
  .app-card:hover {{ transform: translateY(-3px); border-color: var(--line-strong); }}
  .app-card .ico {{ width: 40px; height: 40px; color: var(--accent); margin-bottom: 20px; }}
  .app-card .ico svg {{ width: 40px; height: 40px; }}
  .app-card h3 {{ font-size: 21px; font-weight: 600; color: var(--text-primary); margin-bottom: 6px; }}
  .app-card p {{ font-size: 14px; color: var(--text-secondary); line-height: 1.5; margin-bottom: 16px; }}
  .app-card .tag {{ font-size: 12px; color: var(--text-tertiary); }}

  .gw-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 20px; }}
  .gw-card {{ display: flex; gap: 16px; background: var(--bg-elevated); border: 1px solid var(--line);
             border-radius: var(--radius-lg); padding: 20px 24px; cursor: pointer; transition: transform var(--duration-fast) var(--ease), border-color var(--duration-fast) var(--ease); box-shadow: var(--shadow-sm); }}
  .gw-card:hover {{ transform: translateY(-2px); border-color: var(--line-strong); }}
  .gw-icon {{ width: 40px; height: 40px; flex-shrink: 0; display: flex; align-items: center; justify-content: center;
             background: var(--bg-subtle); border-radius: var(--radius-md); color: var(--accent); }}
  .gw-icon svg {{ width: 22px; height: 22px; }}
  .gw-body {{ flex: 1; min-width: 0; }}
  .gw-name {{ font-size: 17px; font-weight: 600; color: var(--text-primary); margin-bottom: 4px; }}
  .gw-desc {{ font-size: 13px; color: var(--text-secondary); line-height: 1.45; margin-bottom: 10px; }}
  .gw-status {{ display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-tertiary); }}
  .status-dot {{ width: 7px; height: 7px; border-radius: 50%; }}
  .dot-on {{ background: var(--success); }}
  .dot-off {{ background: var(--danger); }}
  .empty {{ color: var(--text-tertiary); font-size: 14px; }}

  .footer {{ text-align: center; padding: 32px 0 0; border-top: 1px solid var(--line); max-width: 1080px; margin: 0 auto;
            font-size: 14px; color: var(--text-tertiary); }}
  .footer a {{ color: var(--text-secondary); }}
  @media (max-width: 734px) {{
    .hero h1 {{ font-size: 40px; }}
    .hero p {{ font-size: 17px; }}
    body {{ padding: 0 16px 48px; }}
  }}
</style>
</head>
<body>
<button class="theme-toggle" id="theme-toggle" aria-label="切换深色模式" title="切换深色模式">
    <svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
    <svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
</button>
<section class="hero">
    <h1>AI Hub</h1>
    <p>统一 AI 聚合管理平台 · 把你的每一个 AI 能力收拢到一个入口</p>
    <a href="/dashboard/index.html" class="btn-primary cta">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>
        进入管理面板
    </a>
    <div class="meta">网关管理 · GitHub 项目 · 飞书同步 · 统计分析 · 资源清单</div>
</section>

<div class="section">
    <div class="section-label">应用</div>
    <div class="section-title">AI 工具</div>
    <div class="app-grid">
        <div class="app-card" onclick="window.open('/ai-canvas/index.html','_blank')">
            <div class="ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19l7-7-3-3-7 7v3h3z"/><path d="M5 21h14"/></svg></div>
            <h3>AI 画布</h3>
            <p>白板画图 → AI 识别 → 生成动态图解。在无限白板上自由画写，让 AI 把抽象概念画成动态图给你看。</p>
            <span class="tag">应用 · 接真实 AI</span>
        </div>
        <div class="app-card" onclick="window.open('/word-cloze/index.html','_blank')">
            <div class="ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h16M4 20V6a2 2 0 012-2h12a2 2 0 012 2v14M9 10h6M9 14h4"/></svg></div>
            <h3>词境挖空</h3>
            <p>把喜欢的内容变成填空练习，主动写出来比认出来记得更牢。AI 供给内容、随机挖空、即时判定。</p>
            <span class="tag">应用 · AI 内容供给</span>
        </div>
    </div>
</div>

<div class="section">
    <div class="section-label">网关</div>
    <div class="section-title">已接入节点</div>
    <div class="gw-grid">{cards_html}</div>
</div>

<div class="section">
    <div class="section-label">数据</div>
    <div class="section-title">多维表格管理</div>
    <div id="bases-grid" class="gw-grid">
        <p class="empty">加载中...</p>
    </div>
    <div style="margin-top: 16px; display: flex; gap: 12px; align-items: center; flex-wrap: wrap;">
        <button class="btn-secondary" onclick="refreshBases()" style="display: inline-flex; align-items: center; gap: 6px; padding: 8px 16px; border-radius: 8px; border: 1px solid var(--line); background: var(--bg-elevated); color: var(--text-primary); cursor: pointer; font-size: 14px;">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 0 1-9 9m9-9a9 9 0 0 0-9-9m9 9h-4m-5 9a9 9 0 0 1-9-9m9 9v-4m-9-5a9 9 0 0 1 9-9m-9 9h4m5-9v4"/></svg>
            刷新
        </button>
        <button class="btn-secondary" onclick="showAddBase()" style="display: inline-flex; align-items: center; gap: 6px; padding: 8px 16px; border-radius: 8px; border: 1px solid var(--line); background: var(--bg-elevated); color: var(--text-primary); cursor: pointer; font-size: 14px;">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            添加 Base
        </button>
        <span id="bases-status" style="font-size: 13px; color: var(--text-tertiary);"></span>
    </div>
</div>

<script>
async function loadBases() {{
    try {{
        const r = await fetch('/api/bases');
        const data = await r.json();
        const grid = document.getElementById('bases-grid');
        if (!data.bases || data.bases.length === 0) {{
            grid.innerHTML = '<p class="empty">暂无已记录的多维表格</p>';
            return;
        }}
        let html = '';
        for (let i = 0; i < data.bases.length; i++) {{
            const b = data.bases[i];
            const tables = (b.tables || []).join(' · ');
            html += '<div class="gw-card" style="cursor: default;">'
                + '<div class="gw-icon" style="color: var(--success);">'
                + '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>'
                + '</div><div class="gw-body">'
                + '<div class="gw-name">' + (b.name || b.token) + '</div>'
                + '<div class="gw-desc">' + (b.description || '') + '</div>'
                + '<div class="gw-status" style="margin-top: 6px;">'
                + '<span style="font-size: 11px; background: var(--bg-subtle); padding: 2px 8px; border-radius: 4px; color: var(--text-tertiary);">' + b.token + '</span>'
                + (tables ? '<span style="font-size: 11px; color: var(--text-tertiary); margin-left: 8px;">' + tables + '</span>' : '')
                + '<button onclick="deleteBase(\'' + b.token + '\')" style="margin-left: auto; background: none; border: none; color: var(--danger); cursor: pointer; font-size: 12px; opacity: 0.6;">删除</button>'
                + '</div></div></div>';
        }}
        grid.innerHTML = html;
        document.getElementById('bases-status').textContent = '共 ' + data.bases.length + ' 个 Base · ' + (data.updated_at || '');
    }} catch(e) {{
        document.getElementById('bases-grid').innerHTML = '<p class="empty">加载失败</p>';
    }}
}}

async function refreshBases() {{
    const btn = event.target.closest('button');
    btn.disabled = true; btn.textContent = '刷新中...';
    try {{
        const r = await fetch('/api/bases/refresh', {{ method: 'POST' }});
        const data = await r.json();
        document.getElementById('bases-status').textContent = '✅ ' + (data.message || '已刷新');
        loadBases();
    }} catch(e) {{
        document.getElementById('bases-status').textContent = '❌ 刷新失败';
    }}
    btn.disabled = false; btn.innerHTML = '... 刷新';
}}

async function deleteBase(token) {{
    if (!confirm('确定删除这个 Base 记录？')) return;
    await fetch('/api/bases/' + token, {{ method: 'DELETE' }});
    loadBases();
}}

function showAddBase() {{
    const token = prompt('输入 Base Token：');
    if (!token) return;
    const name = prompt('输入名称（可选）：');
    fetch('/api/bases', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ token: token, name: name || undefined }})
    }}).then(function() {{ loadBases(); }});
}}

loadBases();
</script>

<div class="footer">AI Hub v1.0 · 局域网模式 · <a href="/dashboard/index.html">管理面板</a> · <a href="/docs">API 文档</a></div>
<script src="/static/theme-toggle.js"></script>
<script src="/static/nav-skins.js"></script>
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

import github_manager


@app.get("/api/github/repos")
async def github_repos():
    """GitHub 仓库列表。"""
    return await github_manager.list_repos()


@app.post("/api/github/repos")
async def github_create_repo(request: Request):
    """创建仓库。"""
    body = await request.json()
    return await github_manager.create_repo(body.get("name", ""),
                                            body.get("description", ""),
                                            body.get("private", True))


@app.post("/api/github/repos/update_description")
async def github_update_repo_description(request: Request):
    """更新仓库描述。"""
    body = await request.json()
    name = body.get("name", "")
    desc = body.get("description", "")
    if not name:
        raise HTTPException(400, "缺少仓库名称")
    return await github_manager.update_repo_description(name, desc)



# ---- task_004：仓库文件读取 ----

@app.get("/api/github/repos/{owner}/{repo}/contents")
async def github_repo_contents(owner: str, repo: str, path: str = "", ref: str = ""):
    """读取仓库文件/目录内容（供分析）。"""
    return await github_manager.get_repo_contents(owner, repo, path, ref)


@app.get("/api/github/repos/{owner}/{repo}/contents/{path:path}")
async def github_repo_contents_path(owner: str, repo: str, path: str, ref: str = ""):
    """读取仓库指定路径内容（支持多级路径）。"""
    return await github_manager.get_repo_contents(owner, repo, path, ref)


# ---- task_004：Issue 管理 ----

@app.get("/api/github/repos/{owner}/{repo}/issues")
async def github_issues(owner: str, repo: str, state: str = "open"):
    """Issue 列表。"""
    return await github_manager.list_issues(owner, repo, state)


@app.post("/api/github/repos/{owner}/{repo}/issues")
async def github_create_issue(owner: str, repo: str, request: Request):
    """创建 Issue。"""
    body = await request.json()
    return await github_manager.create_issue(owner, repo, body.get("title", ""),
                                             body.get("body", ""))


@app.patch("/api/github/repos/{owner}/{repo}/issues/{number}")
async def github_update_issue(owner: str, repo: str, number: int, request: Request):
    """更新 Issue（关闭等）。"""
    body = await request.json()
    if body.get("state") == "closed":
        return await github_manager.close_issue(owner, repo, number,
                                                body.get("comment", ""))
    return {"error": "仅支持 state=closed"}


@app.post("/api/github/repos/{owner}/{repo}/issues/{number}/comments")
async def github_issue_comment(owner: str, repo: str, number: int, request: Request):
    """添加 Issue 评论。"""
    body = await request.json()
    return await github_manager.add_issue_comment(owner, repo, number, body.get("body", ""))


@app.get("/api/github/repos/{owner}/{repo}/issues/{number}/comments")
async def github_issue_comments(owner: str, repo: str, number: int):
    """列出 Issue 评论。"""
    return await github_manager.list_issue_comments(owner, repo, number)


@app.post("/api/github/repos/{owner}/{repo}/issues/{number}/labels")
async def github_issue_labels(owner: str, repo: str, number: int, request: Request):
    """添加 Issue 标签。"""
    body = await request.json()
    return await github_manager.add_issue_labels(owner, repo, number,
                                                 body.get("labels", []))


# ---- task_004：PR 管理 ----

@app.get("/api/github/repos/{owner}/{repo}/pulls")
async def github_pulls(owner: str, repo: str, state: str = "open"):
    """PR 列表。"""
    return await github_manager.list_pull_requests(owner, repo, state)


@app.get("/api/github/repos/{owner}/{repo}/pulls/{number}")
async def github_pull_detail(owner: str, repo: str, number: int):
    """PR 详情。"""
    return await github_manager.get_pull_request(owner, repo, number)


@app.post("/api/github/repos/{owner}/{repo}/pulls")
async def github_create_pull(owner: str, repo: str, request: Request):
    """创建 PR。"""
    body = await request.json()
    return await github_manager.create_pull_request(owner, repo,
                                                    body.get("title", ""),
                                                    body.get("head", ""),
                                                    body.get("base", "main"),
                                                    body.get("body", ""))


@app.put("/api/github/repos/{owner}/{repo}/pulls/{number}/merge")
async def github_merge_pull(owner: str, repo: str, number: int, request: Request):
    """合并 PR。"""
    body = await request.json()
    return await github_manager.merge_pull_request(owner, repo, number,
                                                   body.get("commit_title", ""),
                                                   body.get("merge_method", "merge"))


# ---------------------------------------------------------------- 资源清单（ai-resource-hub 数据桥）

import resources_bridge


# ---------------------------------------------------------------- 飞书同步

import feishu_sync


@app.post("/api/feishu/sync")
async def feishu_sync_trigger():
    """手动触发飞书数据同步。"""
    result = await feishu_sync.sync_all()
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@app.get("/api/feishu/tables")
async def feishu_tables():
    """飞书表格配置信息（脱敏）。"""
    cfg = feishu_sync.load_feishu_config()
    return {
        "app_token": cfg.get("app_token", ""),
        "tables": cfg.get("tables", {}),
        "configured": bool(cfg.get("app_token") and cfg.get("tables", {}).get("gateways")),
    }


# ---------------------------------------------------------------- 资源清单（ai-resource-hub 数据桥）

@app.get("/api/resources")
async def api_resources(source: Literal["auto", "remote", "local"] = "auto"):
    """ai-resource-hub 公开数据桥代理：能力清单 + 实例清单（线上优先，本地回退）。

    source 已收紧为枚举：拼写错误返回 422，不再静默落进 auto 造成"看似成功、实际测错路径"。
    失败状态码：remote 上游不可用 → 502；local 缺失 / 双失败 → 503。
    """
    data = await resources_bridge.get_resources(source)
    if not data.get("ok"):
        status = 502 if data.get("source") == "remote" else 503
        raise HTTPException(status, data.get("error", "数据桥不可用"))
    return data


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


# ---------------------------------------------------------------- 多维表格管理

BASES_JSON = CONFIG_DIR / "bases.json"

# 已知初始数据（从记忆中恢复）
SEED_BASES = [
    {
        "token": "RaqVbiwkbaCh5csWhO0c6Wagnlc",
        "name": "技能注册中心",
        "description": "Agent 技能注册与安装状态管理",
        "tables": ["技能注册表", "Agent安装状态"],
        "source": "memory"
    },
    {
        "token": "StmDbTXQWaujshs9NpIc3UFpnAc",
        "name": "ai-resource-hub 数据桥",
        "description": "AI 资源公开数据桥（工具资产/能力规格/实例）",
        "tables": ["工具资产明细表", "资源能力规格表", "资源实例表"],
        "source": "memory"
    },
    {
        "token": "K15hbHNwtaY3BWs1STLcG092n4g",
        "name": "英语学习系统",
        "description": "英语学习追踪（词汇/学习日志/计划）",
        "tables": ["learning-log", "vocabulary", "学习计划表"],
        "source": "memory"
    }
]


def get_bases():
    data = load_json(BASES_JSON, {"bases": []})
    # 首次启动时种子数据
    if not data.get("bases"):
        data["bases"] = SEED_BASES
        data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        save_json(BASES_JSON, data)
    return data


def save_bases(data):
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    save_json(BASES_JSON, data)


@app.get("/api/bases")
async def list_bases():
    """列出所有已记录的多维表格。"""
    return get_bases()


@app.post("/api/bases")
async def add_base(request: Request):
    """手动添加一个多维表格。"""
    body = await request.json()
    token = body.get("token", "")
    if not token:
        raise HTTPException(400, "缺少 base token")
    data = get_bases()
    # 去重
    for b in data["bases"]:
        if b["token"] == token:
            b.update({k: v for k, v in body.items() if v})
            b["source"] = "manual"
            save_bases(data)
            return {"ok": True, "token": token, "action": "updated"}
    data["bases"].append({
        "token": token,
        "name": body.get("name", token),
        "description": body.get("description", ""),
        "tables": body.get("tables", []),
        "source": "manual",
    })
    save_bases(data)
    return {"ok": True, "token": token, "action": "added"}


@app.delete("/api/bases/{token}")
async def delete_base(token: str):
    """删除一个多维表格记录。"""
    data = get_bases()
    data["bases"] = [b for b in data["bases"] if b["token"] != token]
    save_bases(data)
    return {"ok": True}


@app.post("/api/bases/refresh")
async def refresh_bases():
    """尝试通过飞书 API 发现更多多维表格（需要用户登录态）。"""
    import subprocess
    # 尝试通过 lark-cli 探测已知 base 的详情
    data = get_bases()
    lark = os.path.expandvars(r"%APPDATA%\npm\lark-cli.cmd")
    home = os.path.expandvars(r"%USERPROFILE%")
    for b in data["bases"]:
        try:
            env = os.environ.copy()
            env["HOME"] = home
            env["USERPROFILE"] = home
            r = subprocess.run(
                [lark, "base", "+base-get", "--base-token", b["token"], "--format", "json"],
                capture_output=True, text=True, timeout=15, env=env
            )
            if r.returncode == 0:
                info = json.loads(r.stdout)
                if info.get("ok") and info.get("data"):
                    b["name"] = info["data"].get("name", b["name"])
                    b["description"] = info["data"].get("description", b.get("description", ""))
        except Exception:
            pass
    save_bases(data)
    return {"ok": True, "count": len(data["bases"]), "message": "已刷新 Base 信息，可用飞书 CLI 补充更多"}


# ---------------------------------------------------------------- 启动

@app.on_event("startup")
async def on_startup():
    """启动时注册：每 5 分钟自动飞书同步一次（后台任务，失败不阻塞）。"""
    loop = asyncio.get_event_loop()
    feishu_sync.schedule_sync(interval_seconds=300, loop=loop)


if __name__ == "__main__":
    print("🌐 AI Hub 中央平台启动中...")
    print(f"   导航首页: http://localhost:8000")
    print(f"   API 文档: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)
