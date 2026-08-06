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

## 完成记录
- 完成时间：2026-08-06 09:00
- 执行模型：DeepSeek V4 Flash 0731
- 完成内容：
  1. github_manager.py 增补：
     - 仓库文件读取：get_repo_contents（支持目录遍历列表 + 文件 Base64 解码，可选 ref）
     - Issue 完整管理：close_issue、add_issue_comment、list_issue_comments、add_issue_labels；保留原有 create_issue / list_issues / create_repo
     - PR 管理：list_pull_requests、get_pull_request、create_pull_request、merge_pull_request
     - token 读取改造：环境变量 GITHUB_TOKEN > config/github.json（gitignore）；网络异常/请求/解析错误统一兜底返回而非抛异常
  2. server.py 的 GitHub 路由改为调用 github_manager（原内联 /api/github/repos 保持稳定），新增：
     - GET/POST /api/github/repos
     - GET contents /contents/{path}
     - GET/POST issues、PATCH 关闭、POST comments、GET comments、POST labels
     - GET/POST pulls、GET pulls/{number}、PUT pulls/{number}/merge
- 验收结果（真实仓库 201650545/web-tag-classifier）：
   - 仓库列表返回 3 个仓库
   - 目录遍历 / 文件读取成功（README.md → Base64 解码正常）
   - Issue 全链路实测：创建 #3 → 加评论 → 列评论 → 关闭（含关闭说明）→ 验证 state=closed ✅
   - PR 列表返回 2 条
   - 全部 7 类 API 路由经中央平台 :8000 回归通过
- 遗留问题：PR 创建/合并依赖 head 分支存在，未针对该仓库做破坏性合并测试（仅列表/详情验证）；Webhook 事件接收未实现（任务卡标注可选）。
