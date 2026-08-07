# 任务卡 011：本地额度统计模块

## 执行模型：OpenCode

## 目标
实现本地 API 调用量统计模块，记录每个渠道的调用次数与 token 用量，为渠道管理页和飞书同步提供数据。

## 背景
渠道层（channels.py）已有 7 渠道注册表和 fallback 链，但没有用量统计。本任务实现**本地计数**部分（不调用厂商账单 API——厂商侧余额查询为后续 DeepSeek 的可选增强任务）。

## 交付物
`D:\项目\03_共享组件\quota.py`

## 接口契约

```python
# -*- coding: utf-8 -*-
"""本地额度统计 — 按渠道记录调用次数与 token 用量"""

def record_call(gateway_id: str, channel: str, model: str,
                input_tokens: int = 0, output_tokens: int = 0,
                success: bool = True) -> None:
    """每次 API 调用后记录。线程安全。"""

def get_usage(gateway_id: str = None, channel: str = None,
              date: str = None) -> dict:
    """查询用量。date 默认今天。返回 {channel: {calls, input_tokens, output_tokens, errors}}"""

def get_daily_summary(date: str = None) -> list:
    """按日汇总，供飞书 daily_stats 表同步"""

def reset_daily() -> None:
    """跨天时清零当日计数（由定时任务调用）"""
```

## 存储设计
- 文件：`02_网关实例/{gateway_id}/quota.json`
- 结构：`{"2026-08-06": {"deepseek": {"calls": 12, "input_tokens": 5400, "output_tokens": 12800, "errors": 0}, ...}}`
- 保留最近 90 天数据，超出自动裁剪

## 集成点（改 2 处，不改对外接口）
1. `02_网关实例/ds_v4_cli/channels.py` 的转发函数：响应成功后从 `usage` 字段取 token 数，调用 `record_call()`
2. `02_网关实例/ds_v4_cli/unified_gateway.py`：新增 `GET /api/quota?date=` 端点

## 验收标准
- 发送一次 LLM 请求后，quota.json 正确累计 calls 和 token 数
- 失败请求计入 errors
- `GET /api/quota` 返回当日各渠道用量
- 并发 20 次请求计数无丢失（线程安全）
- `get_daily_summary()` 输出格式与飞书 daily_stats 表字段对齐（见 ARCHITECTURE.md 第 5 节）

## 完成记录
（执行后填写）
