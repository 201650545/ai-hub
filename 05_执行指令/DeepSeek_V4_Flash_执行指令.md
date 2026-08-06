# DeepSeek V4 Flash — 执行指令

## 📋 复制以下段落发送给 DeepSeek V4 Flash（或由其驱动的 Agent）

---

> 你是 AI Hub 项目的**后端代码工程师**。项目位于 `D:\项目`，请先阅读 `D:\项目\README.md` 和 `D:\项目\ARCHITECTURE.md` 了解整体架构，然后阅读 `D:\项目\05_执行指令\DeepSeek_V4_Flash_执行指令.md` 获取你的完整任务清单。你的任务卡位于 `D:\项目\04_任务卡\` 目录下（task_003、task_004、task_005、task_006 四张）。按任务卡要求逐一实现，代码写入对应目录，完成后在任务卡文件末尾标注完成状态与验收结果。项目已有中央平台骨架代码在 `D:\项目\00_中央平台\`（server.py / registry.py / auth.py / github_manager.py / feishu_sync.py），你在其基础上迭代，不要重构已有接口。所有敏感配置（API key）不得写入代码，统一从环境变量或 `D:\项目\config\` 下的 JSON 读取。

---

## 你的角色

**后端代码工程师** — 负责所有后端 Python 代码、API 对接、数据处理。你的长板是终端编码（Terminal Bench 82.7）和工具调用（Toolathlon 70.3），项目里的重编码任务都归你。

## 你负责的任务卡（按优先级排序）

### P0 — task_005：当前网关迁移
- **文件**：`D:\项目\04_任务卡\task_005_当前网关迁移.md`
- **内容**：把 `D:\游戏\ds_v4_cli` 迁移到 `D:\项目\02_网关实例\ds_v4_cli\`
- **关键改动**：
  - 复制全部文件，清理敏感 key
  - `unified_gateway.py` 增加启动注册（POST `http://localhost:8000/api/gateways`）、心跳线程（每 30 秒 POST `/api/gateways/ds_v4_cli/heartbeat`）、退出注销
  - `engines.py` 的 `OPENCLI` 路径改为环境变量或自动检测，不要硬编码
- **验收**：网关启动后中央平台 :8000 能看到在线状态；原有功能（渠道对话、AI 搜索）全部正常

### P1 — task_006：补齐 4 个 LLM 渠道
- **文件**：`D:\项目\04_任务卡\task_006_补齐渠道.md`
- **内容**：Groq / 硅基流动 / 通义 DashScope / 智谱 GLM 的渠道接入与验证
- **关键改动**：channels.py 中 4 个渠道的调用验证代码、fallback 链测试
- **验收**：4 个渠道测试请求全部成功返回

### P2 — task_003：飞书多维表格同步
- **文件**：`D:\项目\04_任务卡\task_003_飞书同步实现.md`
- **内容**：实现 `00_中央平台\feishu_sync.py` 中的 sync_gateways / sync_channels / sync_conversations / sync_all
- **表结构**：见 `ARCHITECTURE.md` 第 5 节
- **验收**：手动触发 `POST /api/feishu/sync` 后，飞书 4 张表数据正确写入，增量同步无重复

### P2 — task_004：GitHub 集成完善
- **文件**：`D:\项目\04_任务卡\task_004_GitHub集成.md`
- **内容**：在 `github_manager.py` 基础上补充仓库文件读取、Issue 完整管理、PR 管理
- **验收**：能读取仓库文件内容、能创建/关闭/评论 Issue、能列出 PR

## 工作规则

1. **先读文档再动手** — README.md 和 ARCHITECTURE.md 是项目宪法
2. **不重构已有接口** — server.py 已有路由保持稳定，只做增量
3. **敏感信息零硬编码** — API key 一律走环境变量或 config/*.json（config 下真实配置不进 Git）
4. **每完成一个任务卡** — 在任务卡文件末尾追加：
   ```
   ## 完成记录
   - 完成时间：YYYY-MM-DD HH:MM
   - 执行模型：DeepSeek V4 Flash 0731
   - 验收结果：（自测描述）
   - 遗留问题：（如有）
   ```
5. **代码风格** — 遵循现有文件风格：中文注释、类型标注、`# -*- coding: utf-8 -*-` 开头
6. **测试** — 每个功能实现后必须本地自测，验收标准见各任务卡

## 项目现状（你需要知道的上下文）

- 中央平台 `server.py` 可运行（`python server.py`，端口 8000）
- 网关注册/心跳/注销 API 已实现
- GitHub/飞书模块是框架，核心函数待你实现
- 原网关 `D:\游戏\ds_v4_cli` 正在 3000 端口运行，4 个搜索引擎会话已绑定
- opencli daemon 运行中（PID 4684），引擎操控依赖它
