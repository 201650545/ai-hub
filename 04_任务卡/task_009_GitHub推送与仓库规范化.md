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
（执行后填写）
