# AI Hub — 统一 AI 聚合管理平台

多网关 AI 服务管理平台，支持 API 聚合中转、多引擎 AI 搜索、GitHub 项目管理、飞书数据同步。

## 项目状态

![Status](https://img.shields.io/badge/status-活跃开发-blue)
![Platform](https://img.shields.io/badge/platform-Windows_ChatGPT-2e77bc)
![Python](https://img.shields.io/badge/python-3.10+-lightgrey)

## 给 AI 协作者的导读

这是一个按**多 Agent 任务卡**推进的项目。如果你是要接手或协助开发的 AI 协作者（或人类开发者），请按以下顺序阅读：

1. **[架构设计](ARCHITECTURE.md)** — 模块划分、数据流、全部接口定义（必读）
2. **[任务卡](04_任务卡/)** — 每张卡描述一个独立模块/子系统的目标、交付物、接口契约与验收标准
3. **[执行指令](05_执行指令/)** — 每种执行模型（DeepSeek / Gemini / OpenCode）的运行约定
4. **[验收测试](tests/)** — E2E 测试套件，改动后执行 `python tests/run_all.py` 一键回归

### 核心目录速览

| 目录 | 作用 |
|------|------|
| `00_中央平台/` | FastAPI 中央服务（:8000）：网关注册/发现、统计、飞书同步、面板 |
| `01_网关模板/` | 网关生成器 + 模板（新网关从这里生成） |
| `02_网关实例/` | 各网关实例（:3000+），如 `ds_v4_cli` |
| `03_共享组件/` | 跨网关共享代码（`history.py` 历史、`quota.py` 额度等） |
| `04_任务卡/`    | 各 Agent 的任务卡（含完成记录） |
| `05_执行指令/`  | 各执行模型的运行约定 |
| `tests/`        | E2E 验收测试套件（run_all.py 一键回归） |

### 当前进度

| 编号 | 模块 | 状态 |
|------|------|------|
| task_001 | 网关模板实现 | ✅ |
| task_002 | 管理面板 UI | ✅ |
| task_003 | 飞书同步实现 | ✅ |
| task_004 | GitHub 集成 | ✅ |
| task_005 | 网关迁移 | ✅ |
| task_006 | 补齐渠道 | ✅ |
| task_007 | 多轮对话搜索 | ✅ |
| task_008 | E2E 验收测试套件 | ✅ |
| task_009 | GitHub 推送与仓库规范化 | ✅ |
| task_010 | 对话历史管理模块 | ✅ |
| task_011 | 本地额度统计模块 | ✅ |
| task_013 | 编排器核心（组件编排器） | ✅ |
| task_014 | B站视频嵌入组件（组件编排器） | ✅ |

> 第三阶段组件编排器其余卡片：task_012 / 015 / 016（🟢 Gemini 范围）

## 项目结构

```
D:\项目\
├── 00_中央平台/          # FastAPI 中央管理服务（:8000）
│   ├── server.py         # 主服务入口
│   ├── registry.py       # 网关注册/发现/监控
│   ├── auth.py           # 简单认证（token）
│   ├── github_manager.py # GitHub 项目管理
│   ├── feishu_sync.py    # 飞书多维表格同步
│   └── dashboard/        # 管理面板（静态文件）
├── 01_网关模板/          # 网关生成器 + 模板
├── 02_网关实例/          # 各网关实例（:3000+）
├── 03_共享组件/          # 跨网关共享代码
├── 04_任务卡/            # 其他 Agent 的任务卡
├── config/               # 配置模板（不含真实 key）
└── ARCHITECTURE.md       # 架构设计文档
```

## 快速开始

```bash
# 1. 安装依赖
pip install fastapi uvicorn httpx

# 2. 配置
cp config/channels.example.json config/channels.json
# 编辑 channels.json，填入你的 API key

# 3. 启动中央平台
cd 00_中央平台
python server.py

# 4. 启动网关实例（另一个终端）
cd 02_网关实例/ds_v4_cli
python unified_gateway.py
```

## 访问

- 中央平台导航：`http://localhost:8000`
- 网关实例：`http://localhost:3000`（ds_v4_cli）
- API 文档：`http://localhost:8000/docs`

## 规模

- 当前：个人局域网
- 目标：最多 50 人共享使用
- 认证：简单 token 验证

## 数据存储

- 本地：JSON 文件（channels.json / gateways.json / history.json）
- 远程：飞书多维表格（定时同步）
- 代码：GitHub（版本管理 + ChatGPT 协作）

## 相关文档

- [架构设计](ARCHITECTURE.md) — 模块划分、数据流、接口定义
- [任务卡](04_任务卡/) — 其他 Agent 的实现任务
