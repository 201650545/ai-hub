# 任务卡 009：GitHub 推送与仓库规范化

## 执行模型：OpenCode

## 目标
将 `D:\项目` 推送到 GitHub 私有仓库 `ai-hub`，并完成仓库规范化配置，使其可被 ChatGPT 网页版直接读取理解。

## 前置条件
- 用户已在 GitHub 网页创建私有仓库 `ai-hub`（201650545/ai-hub）
- 本机 git 已配置用户（201650545 / yongtaog767@gmail.com）

## 实现步骤

### 1. 远程关联与推送
```bash
cd D:\项目
git remote add origin https://github.com/201650545/ai-hub.git
git push -u origin main
```
- 若提示认证：引导用户配置 Personal Access Token 或 Git Credential Manager
- 若远程已有 README 冲突：`git pull --rebase origin main` 后再推

### 2. 仓库规范化
- 新增 `.gitattributes`：`* text=auto eol=crlf`（Windows 项目统一行尾，消除 LF/CRLF 警告）
- 检查 `.gitignore` 生效：`git ls-files | grep channels.json` 应为空
- 二次敏感扫描：`git grep -E "sk-[a-zA-Z0-9_-]{15,}"` 应只有占位符

### 3. README 增强（让 ChatGPT 快速读懂）
在现有 README.md 基础上补充：
- 项目状态徽章区（预留）
- 「给 AI 协作者的导读」小节：指向 ARCHITECTURE.md、04_任务卡/、05_执行指令/
- 当前进度表（哪些模块已完成、哪些待做）

### 4. 首次推送后验证
- `git ls-remote origin` 确认远程同步
- 仓库主页文件树完整（无 channels.json/auth.json/feishu.json）

## 验收标准
- `git push` 成功，GitHub 上可见全部文件
- 无敏感配置文件入库
- README 含 AI 协作者导读

## 完成记录
- 2026-08-06 完成（本地部分；push 待认证）
- 远程：`git remote add origin https://github.com/201650545/ai-hub.git` 已配置
- `.gitattributes`：`* text=auto eol=crlf` 统一行尾；`.gitignore` 已确认生效（channels/gateways/feishu/history/quota/*.json.lock 均不入库）
- 敏感扫描：`git grep sk-/AIza/Bearer` 仅命中示例/占位符，无真实 key
- README 增强：项目状态徽章、「给 AI 协作者的导读」、当前进度表、核心目录速览
- ⚠️ PUSH 未完成：本机无 credential manager / gh / token，git push 提示认证。需用户终端执行：
  `git config --global credential.helper manager && git push -u origin main`
- 本地已提交 4 张卡全部工作（008/009本地/010/011），待 push 一次性同步
- 遗留：push 成功前 remote 未同步；推送后建议 `git ls-remote origin` 复核文件树（应无 channels/auth/feishu/quota/history JSON）
