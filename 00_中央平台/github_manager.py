# -*- coding: utf-8 -*-
"""
GitHub 项目管理模块
对接 GitHub API，提供仓库列表、Issue 管理、创建仓库等功能

依赖: pip install httpx
认证: 环境变量 GITHUB_TOKEN (Personal Access Token)
"""

import os

import httpx

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
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
