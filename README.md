# AI Hub — 统一 AI 聚合管理平台

多网关 AI 服务管理平台，支持 API 聚合中转、多引擎 AI 搜索、GitHub 项目管理、飞书数据同步。

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
