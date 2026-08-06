# AI Hub 架构设计

## 1. 整体架构

```
┌─────────────────────────────────────────────────────┐
│                  中央平台 (:8000)                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │ 导航面板  │ │ 网关注册  │ │ GitHub   │ │ 飞书    │ │
│  │ dashboard│ │ registry │ │ manager  │ │ sync   │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────┘ │
│  ┌─────────────────────────────────────────────────┐│
│  │              FastAPI server.py                   ││
│  │  /api/gateways  /api/github  /api/feishu  /api/stats│
│  └─────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────┘
         │              │              │
         ▼              ▼              ▼
   ┌──────────┐  ┌──────────┐  ┌──────────┐
   │ 网关 A    │  │ 网关 B    │  │ 网关 C    │
   │ :3000    │  │ :3001    │  │ :3002    │
   │ ds_v4_cli│  │ ...      │  │ ...      │
   └──────────┘  └──────────┘  └──────────┘
         │              │              │
         └──────────────┼──────────────┘
                        ▼
              ┌──────────────────┐
              │  飞书多维表格      │
              │  gateways        │
              │  api_channels    │
              │  conversations   │
              │  daily_stats     │
              └──────────────────┘
```

## 2. 模块划分

### 2.1 中央平台（00_中央平台/）

| 模块 | 文件 | 职责 |
|------|------|------|
| 主服务 | server.py | FastAPI 入口，路由分发，静态文件服务 |
| 网关注册 | registry.py | 网关注册/发现/心跳/健康检查 |
| 认证 | auth.py | Token 验证（简单共享密码） |
| GitHub | github_manager.py | 仓库列表、Issue 管理、创建仓库 |
| 飞书同步 | feishu_sync.py | 定时同步本地 JSON → 飞书多维表格 |
| 面板 | dashboard/ | 静态 HTML/JS/CSS 管理界面 |

### 2.2 网关模板（01_网关模板/）

| 文件 | 职责 |
|------|------|
| create_gateway.py | 网关生成器，按模板创建新网关实例 |
| template/ | 模板文件（unified_gateway.py / channels.py / engines.py / hub_page.html） |

### 2.3 网关实例（02_网关实例/）

每个网关是一个独立文件夹，包含：
- `unified_gateway.py` — 网关主服务（:3000+）
- `channels.py` — LLM 渠道注册表
- `engines.py` — AI 搜索引擎适配层
- `hub_page.html` — 网关页面
- `setup_engines.py` — 引擎会话绑定

### 2.4 共享组件（03_共享组件/）

跨网关共享的代码，通过符号链接或复制到各网关实例：
- `channels.py` — 渠道注册表（统一版本）
- `engines.py` — 引擎适配层（统一版本）
- `feishu_client.py` — 飞书 API 客户端

## 3. 数据流

### 3.1 网关注册流程

```
网关启动 → POST /api/gateways/register → registry.py 记录
                                        → 写入 config/gateways.json
                                        → 同步到飞书 gateways 表
网关心跳 → POST /api/gateways/{id}/heartbeat → 更新最后在线时间
网关停止 → POST /api/gateways/{id}/unregister → 标记离线
```

### 3.2 数据同步流程

```
定时任务（每5分钟）→ feishu_sync.py
  → 读取 config/gateways.json
  → 读取 02_网关实例/*/channels.json
  → 读取 02_网关实例/*/history.json
  → 推送到飞书多维表格对应表
```

### 3.3 GitHub 集成流程

```
用户请求 → GET /api/github/repos → github_manager.py
  → 调用 GitHub API（PyGithub / REST）
  → 返回仓库列表
  → 可选：同步到飞书 github_repos 表
```

## 4. API 接口定义

### 4.1 网关管理

| 端点 | 方法 | 说明 |
|------|------|------|
| /api/gateways | GET | 网关列表 |
| /api/gateways | POST | 注册新网关 |
| /api/gateways/{id} | GET | 网关详情 |
| /api/gateways/{id}/start | POST | 启动网关 |
| /api/gateways/{id}/stop | POST | 停止网关 |
| /api/gateways/{id}/health | GET | 健康检查 |
| /api/gateways/{id}/heartbeat | POST | 心跳上报 |

### 4.2 GitHub

| 端点 | 方法 | 说明 |
|------|------|------|
| /api/github/repos | GET | 仓库列表 |
| /api/github/repos | POST | 创建仓库 |
| /api/github/repos/{owner}/{repo}/issues | GET | Issue 列表 |

### 4.3 飞书

| 端点 | 方法 | 说明 |
|------|------|------|
| /api/feishu/tables | GET | 表格列表 |
| /api/feishu/sync | POST | 手动触发同步 |

### 4.4 统计

| 端点 | 方法 | 说明 |
|------|------|------|
| /api/stats | GET | 全局统计 |
| /api/stats/gateways/{id} | GET | 单网关统计 |

## 5. 飞书多维表格结构

### gateways 表
| 字段 | 类型 | 说明 |
|------|------|------|
| name | 文本 | 网关名称 |
| port | 数字 | 端口号 |
| status | 单选 | online / offline / error |
| url | 文本 | 访问地址 |
| created_at | 日期 | 创建时间 |
| last_seen | 日期 | 最后在线时间 |

### api_channels 表
| 字段 | 类型 | 说明 |
|------|------|------|
| gateway | 文本 | 所属网关 |
| channel | 文本 | 渠道名 |
| key_prefix | 文本 | Key 前缀（脱敏） |
| today_calls | 数字 | 今日调用次数 |
| quota_remaining | 数字 | 剩余额度 |
| status | 单选 | active / exhausted / error |

### conversations 表
| 字段 | 类型 | 说明 |
|------|------|------|
| gateway | 文本 | 所属网关 |
| engine | 文本 | 搜索引擎 |
| question | 文本 | 用户问题 |
| answer | 文本 | AI 回答 |
| created_at | 日期 | 时间戳 |

### daily_stats 表
| 字段 | 类型 | 说明 |
|------|------|------|
| date | 日期 | 日期 |
| gateway | 文本 | 网关 |
| total_calls | 数字 | 总调用数 |
| active_users | 数字 | 活跃用户 |
| error_count | 数字 | 错误数 |

## 6. 认证设计

- 小规模（≤50人）：共享 token 认证
- 中央平台启动时生成随机 token，写入 config/auth.json
- 所有 API 请求需带 `Authorization: Bearer <token>`
- 可选：按用户分配不同 token，实现简单的权限隔离

## 7. 扩展性考虑

- 网关数量增加：registry.py 支持动态注册，无需重启中央平台
- 用户量增加：token 认证可升级为 JWT + 用户数据库
- 数据量增加：本地 JSON 可迁移到 SQLite → PostgreSQL
- 功能扩展：新增网关类型（如图像生成、语音合成）只需实现统一接口
