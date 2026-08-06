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

## 完成记录
- 完成时间：2026-08-06 09:00
- 执行模型：DeepSeek V4 Flash 0731
- 完成内容：
  1. 实现 feishu_sync.py 全部函数：
     - `get_tenant_token()`（复用原实现）
     - 本地数据源：read_local_gateways（config/gateways.json）、read_local_channels（各网关 channels.json，key 脱敏为前缀）、read_local_conversations（各网关 history.json）、read_local_daily_stats（汇总）
     - 飞书封装：fetch_records（分页）、_create_record / _update_record / _batch_create
     - 增量同步 `_sync_table`：先查询现有记录 → 按业务主键去重 → 命中 PUT 更新，未命中 batch_create（≤500/批），不产生重复
     - 各表主键：gateways→name；api_channels→gateway|channel；conversations→gateway|engine|created_at；daily_stats→date|gateway
     - `sync_all()` 同步 4 张表并返回 created/updated/existing/skipped 统计
     - `schedule_sync(300)` 后台定时任务
  2. server.py：
     - `POST /api/feishu/sync` 接线到 sync_all（原为「待实现」占位）
     - 新增 `GET /api/feishu/tables`（配置脱敏查询）
     - `startup` 事件挂载每 5 分钟自动同步
- 验收结果：模块导入与本地数据读取正确（gateways/channels/daily_stats 有数据）；`/api/feishu/sync` 在未配置凭据时正确返回「未配置飞书 APP_ID/SECRET」，`/api/feishu/tables` 返回 configured=false；server.py 重启后定时任务挂载无异常。
- 遗留问题：未配置 FEISHU_APP_ID/APP_SECRET 与 config/feishu.json 的 app_token/table_id，未做真实写库验证。配置方法：设置环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET，在 config/feishu.json 填入 app_token 与 4 张表 table_id，然后 POST /api/feishu/sync 即可验证增量去重。
