# 任务卡 010：对话历史管理模块

## 执行模型：OpenCode

## 目标
实现独立的对话历史持久化模块，供网关的多轮对话功能（task_007 已实现接口）调用，并同步到中央平台统计。

## 背景
Gemini 已在 `engines.py` 实现多轮对话 4 函数（start/ask/history/end），但对话记录目前只在内存。需要持久化到本地 JSON，并暴露查询接口。

## 交付物
`D:\项目\03_共享组件\history.py`

## 接口契约

```python
# -*- coding: utf-8 -*-
"""对话历史管理 — JSON 持久化，供网关与中央平台共用"""

def save_turn(gateway_id: str, engine_id: str, conversation_id: str,
              role: str, content: str) -> dict:
    """保存一轮对话（role=user/assistant），返回记录 dict（含 id 和 created_at）"""

def get_conversation(gateway_id: str, conversation_id: str) -> list:
    """获取某对话的完整记录列表"""

def list_conversations(gateway_id: str = None, engine_id: str = None,
                       limit: int = 50) -> list:
    """按网关/引擎筛选对话列表（不含 content 全文，只有摘要）"""

def delete_conversation(gateway_id: str, conversation_id: str) -> bool:
    """删除对话"""

def export_daily_stats(date: str = None) -> list:
    """导出指定日期（默认今天）各网关/引擎的对话数统计，供飞书 daily_stats 同步"""
```

## 存储设计
- 文件：`02_网关实例/{gateway_id}/history.json`
- 结构：`{"conversations": {"<conv_id>": {"engine": "...", "created_at": "...", "turns": [{"id": 1, "role": "user", "content": "...", "created_at": "..."}]}}}`
- 并发安全：写入用文件锁（msvcrt.locking 或 portalocker）
- 容量控制：单文件超 10MB 时按月份归档为 history_2026-08.json

## 集成点（改 2 处，不改接口）
1. `02_网关实例/ds_v4_cli/engines.py` 的 `ask_conversation()`：回答提取成功后调用 `save_turn()` 存 user + assistant 两轮
2. `02_网关实例/ds_v4_cli/unified_gateway.py`：新增 `GET /api/history?engine=&limit=` 端点，调用 `list_conversations()`

## 验收标准
- 多轮对话后 history.json 正确写入
- `GET /api/history` 返回对话列表
- 删除/导出功能正常
- 连续写入 100 轮无文件损坏

## 完成记录
（执行后填写）
