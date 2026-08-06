# -*- coding: utf-8 -*-
"""
GitHub 项目管理模块
对接 GitHub API，提供仓库列表、Issue 管理、创建仓库等功能

依赖: pip install httpx
认证: 环境变量 GITHUB_TOKEN (Personal Access Token)
"""

import json
import os
from pathlib import Path

import httpx

# token 优先级：环境变量 GITHUB_TOKEN > config/github.json（gitignore 不入库）
CONFIG_DIR = Path(__file__).parent.parent / "config"


def _load_github_token():
    env_tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if env_tok:
        return env_tok
    try:
        with open(CONFIG_DIR / "github.json", "r", encoding="utf-8") as f:
            return json.load(f).get("token", "").strip()
    except (FileNotFoundError, json.JSONDecodeError):
        return ""


GITHUB_TOKEN = _load_github_token()
GITHUB_API = "https://api.github.com"


def _headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


async def list_repos(per_page=30, sort="updated"):
    """获取用户仓库列表。"""
    if not GITHUB_TOKEN:
        return {"error": "未配置 GITHUB_TOKEN", "repos": []}
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GITHUB_API}/user/repos",
            params={"per_page": per_page, "sort": sort},
            headers=_headers(),
        )
        if r.status_code == 200:
            return {
                "repos": [
                    {
                        "name": x["name"],
                        "full_name": x["full_name"],
                        "url": x["html_url"],
                        "description": x.get("description"),
                        "language": x.get("language"),
                        "stars": x.get("stargazers_count", 0),
                        "forks": x.get("forks_count", 0),
                        "updated_at": x["updated_at"],
                        "private": x["private"],
                    }
                    for x in r.json()
                ]
            }
        return {"error": f"GitHub API 错误: {r.status_code}", "repos": []}


async def get_repo(owner, repo):
    """获取单个仓库详情。"""
    if not GITHUB_TOKEN:
        return {"error": "未配置 GITHUB_TOKEN"}
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{GITHUB_API}/repos/{owner}/{repo}", headers=_headers())
        if r.status_code == 200:
            x = r.json()
            return {
                "name": x["name"],
                "full_name": x["full_name"],
                "url": x["html_url"],
                "description": x.get("description"),
                "language": x.get("language"),
                "stars": x.get("stargazers_count", 0),
                "forks": x.get("forks_count", 0),
                "open_issues": x.get("open_issues_count", 0),
                "default_branch": x.get("default_branch", "main"),
                "created_at": x["created_at"],
                "updated_at": x["updated_at"],
            }
        return {"error": f"GitHub API 错误: {r.status_code}"}


async def list_issues(owner, repo, state="open", per_page=20):
    """获取仓库 Issue 列表。"""
    if not GITHUB_TOKEN:
        return {"error": "未配置 GITHUB_TOKEN", "issues": []}
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/issues",
            params={"state": state, "per_page": per_page},
            headers=_headers(),
        )
        if r.status_code == 200:
            return {
                "issues": [
                    {
                        "number": x["number"],
                        "title": x["title"],
                        "state": x["state"],
                        "url": x["html_url"],
                        "created_at": x["created_at"],
                        "labels": [l["name"] for l in x.get("labels", [])],
                    }
                    for x in r.json()
                    if "pull_request" not in x  # 排除 PR
                ]
            }
        return {"error": f"GitHub API 错误: {r.status_code}", "issues": []}


async def create_repo(name, description="", private=True):
    """创建新仓库。"""
    if not GITHUB_TOKEN:
        return {"error": "未配置 GITHUB_TOKEN"}
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{GITHUB_API}/user/repos",
            json={"name": name, "description": description, "private": private},
            headers=_headers(),
        )
        if r.status_code == 201:
            x = r.json()
            return {"ok": True, "name": x["name"], "url": x["html_url"]}
        return {"error": f"GitHub API 错误: {r.status_code}", "detail": r.json()}


async def create_issue(owner, repo, title, body=""):
    """创建 Issue。"""
    if not GITHUB_TOKEN:
        return {"error": "未配置 GITHUB_TOKEN"}
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{GITHUB_API}/repos/{owner}/{repo}/issues",
            json={"title": title, "body": body},
            headers=_headers(),
        )
        if r.status_code == 201:
            x = r.json()
            return {"ok": True, "number": x["number"], "url": x["html_url"]}
        return {"error": f"GitHub API 错误: {r.status_code}"}


# ---------------------------------------------------------------- task_004：仓库文件读取

async def get_repo_contents(owner, repo, path="", ref=""):
    """读取仓库文件/目录内容（供 ChatGPT 分析）。支持目录遍历与文件 Base64 解码。"""
    if not GITHUB_TOKEN:
        return {"error": "未配置 GITHUB_TOKEN"}
    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
    params = {}
    if ref:
        params["ref"] = ref
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, params=params, headers=_headers())
    except Exception as e:  # noqa: BLE001  网络异常（DNS/代理/连接）
        return {"error": f"网络异常: {type(e).__name__}: {str(e)[:120]}"}
    try:
        if r.status_code not in (200, 201):
            return {"error": f"GitHub API 错误: {r.status_code}", "detail": r.json()}

        data = r.json()
    except Exception as e:  # noqa: BLE001
        return {"error": f"响应解析失败: {type(e).__name__}: {str(e)[:120]}"}

    if isinstance(data, list):  # 目录
        items = [{
            "name": x["name"],
            "type": x["type"],  # file / dir
            "path": x["path"],
            "size": x.get("size", 0),
            "url": x["html_url"],
        } for x in data]
        return {"type": "dir", "path": path, "items": items}

    import base64
    content = data.get("content", "")
    try:
        text = base64.b64decode(content).decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        text = ""
    return {
        "type": "file",
        "path": data.get("path"),
        "name": data.get("name"),
        "size": data.get("size", 0),
        "content": text,
        "sha": data.get("sha"),
        "url": data.get("html_url"),
    }


# ---------------------------------------------------------------- task_004：Issue 完整管理

async def close_issue(owner, repo, number, comment=""):
    """关闭 Issue，可选附带关闭说明。"""
    if not GITHUB_TOKEN:
        return {"error": "未配置 GITHUB_TOKEN"}
    async with httpx.AsyncClient() as client:
        r = await client.patch(
            f"{GITHUB_API}/repos/{owner}/{repo}/issues/{number}",
            json={"state": "closed"}, headers=_headers(),
        )
        if r.status_code in (200, 201):
            result = {"ok": True, "number": number, "state": "closed"}
            if comment:
                cc = await add_issue_comment(owner, repo, number, comment)
                result["comment"] = cc
            return result
        return {"error": f"GitHub API 错误: {r.status_code}", "detail": r.json()}


async def add_issue_comment(owner, repo, number, body):
    """给 Issue 添加评论。"""
    if not GITHUB_TOKEN:
        return {"error": "未配置 GITHUB_TOKEN"}
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{GITHUB_API}/repos/{owner}/{repo}/issues/{number}/comments",
            json={"body": body}, headers=_headers(),
        )
        if r.status_code in (200, 201):
            return {"ok": True, "id": r.json()["id"], "url": r.json()["html_url"]}
        return {"error": f"GitHub API 错误: {r.status_code}", "detail": r.json()}


async def list_issue_comments(owner, repo, number):
    """列出 Issue 全部评论。"""
    if not GITHUB_TOKEN:
        return {"error": "未配置 GITHUB_TOKEN", "comments": []}
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/issues/{number}/comments",
            headers=_headers())
        if r.status_code == 200:
            return {"comments": [{
                "id": c["id"], "body": c["body"], "user": c["user"]["login"],
                "created_at": c["created_at"],
            } for c in r.json()]}
        return {"error": f"GitHub API 错误: {r.status_code}", "comments": []}


async def add_issue_labels(owner, repo, number, labels):
    """给 Issue 添加标签。"""
    if not GITHUB_TOKEN:
        return {"error": "未配置 GITHUB_TOKEN"}
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{GITHUB_API}/repos/{owner}/{repo}/issues/{number}/labels",
            json={"labels": labels}, headers=_headers())
        if r.status_code == 200:
            x = r.json()
            return {"ok": True, "labels": [l["name"] for l in x]}
        return {"error": f"GitHub API 错误: {r.status_code}", "detail": r.json()}


# ---------------------------------------------------------------- task_004：PR 管理

async def list_pull_requests(owner, repo, state="open", per_page=20):
    """列出 Pull Requests。"""
    if not GITHUB_TOKEN:
        return {"error": "未配置 GITHUB_TOKEN", "pulls": []}
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls",
            params={"state": state, "per_page": per_page}, headers=_headers())
        if r.status_code == 200:
            return {"pulls": [{
                "number": x["number"],
                "title": x["title"],
                "state": x["state"],
                "user": x["user"]["login"],
                "branch": x["head"]["ref"],
                "base": x["base"]["ref"],
                "url": x["html_url"],
                "created_at": x["created_at"],
            } for x in r.json()]}
        return {"error": f"GitHub API 错误: {r.status_code}", "pulls": []}


async def create_pull_request(owner, repo, title, head, base="main", body=""):
    """创建 PR。"""
    if not GITHUB_TOKEN:
        return {"error": "未配置 GITHUB_TOKEN"}
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls",
            json={"title": title, "head": head, "base": base, "body": body},
            headers=_headers())
        if r.status_code in (201, 200):
            x = r.json()
            return {"ok": True, "number": x["number"], "url": x["html_url"]}
        return {"error": f"GitHub API 错误: {r.status_code}", "detail": r.json()}


async def merge_pull_request(owner, repo, number, commit_title="", merge_method="merge"):
    """合并 PR。"""
    if not GITHUB_TOKEN:
        return {"error": "未配置 GITHUB_TOKEN"}
    payload = {"merge_method": merge_method}
    if commit_title:
        payload["commit_title"] = commit_title
    async with httpx.AsyncClient() as client:
        r = await client.put(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}/merge",
            json=payload, headers=_headers())
        if r.status_code == 200:
            x = r.json()
            return {"ok": True, "merged": x.get("merged", False),
                    "message": x.get("message", "merged")}
        return {"error": f"GitHub API 错误: {r.status_code}", "detail": r.json()}


async def get_pull_request(owner, repo, number):
    """PR 详情（含合并状态）。"""
    if not GITHUB_TOKEN:
        return {"error": "未配置 GITHUB_TOKEN"}
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}", headers=_headers())
        if r.status_code == 200:
            x = r.json()
            return {
                "number": x["number"], "title": x["title"], "state": x["state"],
                "body": x.get("body", ""), "merged": x.get("merged", False),
                "head": x["head"]["ref"], "base": x["base"]["ref"],
                "url": x["html_url"],
            }
        return {"error": f"GitHub API 错误: {r.status_code}"}
