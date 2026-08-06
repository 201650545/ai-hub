# 任务卡 003：飞书多维表格同步实现

## 目标
实现 `00_中央平台/feishu_sync.py`，将本地 JSON 数据定时同步到飞书多维表格。

## 前置条件
1. 已创建飞书应用（获取 APP_ID / APP_SECRET）
2. 已创建飞书多维表格，并获取 app_token
3. 已创建 4 张表：gateways / api_channels / conversations / daily_stats

## 飞书多维表格结构（已定义在 ARCHITECTURE.md）

### gateways 表
| 字段 | 类型 |
|------|------|
| name | 文本 |
| port | 数字 |
| status | 单选(online/offline/error) |
| url | 文本 |
| created_at | 日期 |
| last_seen | 日期 |

### api_channels 表
| 字段 | 类型 |
|------|------|
| gateway | 文本 |
| channel | 文本 |
| key_prefix | 文本 |
| today_calls | 数字 |
| quota_remaining | 数字 |
| status | 单选(active/exhausted/error) |

### conversations 表
| 字段 | 类型 |
|------|------|
| gateway | 文本 |
| engine | 文本 |
| question | 文本 |
| answer | 文本 |
| created_at | 日期 |

### daily_stats 表
| 字段 | 类型 |
|------|------|
| date | 日期 |
| gateway | 文本 |
| total_calls | 数字 |
| active_users | 数字 |
| error_count | 数字 |

## 实现要点
1. 获取 tenant_access_token（已实现 `get_tenant_token()`）
2. 读取本地 JSON 文件（gateways.json / channels.json / history.json）
3. 对比飞书已有记录，增量更新（避免重复写入）
4. 定时任务：每 5 分钟自动同步一次
5. 支持手动触发（POST /api/feishu/sync）

## 飞书 API 参考
- 写入记录：`POST /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records`
- 查询记录：`GET /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records`
- 更新记录：`PUT /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}`

## 验收标准
- 能成功获取 tenant_access_token
- 能正确写入/更新 4 张表的数据
- 增量同步不产生重复记录
- 定时任务正常运行
