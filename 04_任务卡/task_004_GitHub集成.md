# 任务卡 004：GitHub 集成实现

## 目标
完善 `00_中央平台/github_manager.py`，实现完整的 GitHub 项目管理功能。

## 前置条件
1. 已创建 GitHub Personal Access Token（repo 权限）
2. 设置环境变量 `GITHUB_TOKEN`

## 已实现（框架）
- `list_repos()` — 仓库列表
- `get_repo()` — 仓库详情
- `list_issues()` — Issue 列表
- `create_repo()` — 创建仓库
- `create_issue()` — 创建 Issue

## 待实现
1. **仓库文件读取** — 读取仓库中的文件内容（供 ChatGPT 分析）
   - `GET /repos/{owner}/{repo}/contents/{path}`
   - 支持目录遍历和文件内容获取

2. **Issue 管理** — 完整的 Issue 操作
   - 创建 Issue（已实现）
   - 关闭 Issue
   - 添加评论
   - 添加标签

3. **PR 管理** — Pull Request 操作
   - 列表
   - 创建
   - 合并

4. **Webhook** — 接收 GitHub 事件（可选）
   - push 事件通知
   - Issue 事件通知

## 验收标准
- 能正确读取仓库文件内容
- 能完整管理 Issue（创建/关闭/评论）
- 能查看和管理 PR
- 错误处理完善（网络异常、权限不足等）
