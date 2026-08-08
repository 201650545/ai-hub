# 任务卡 013：编排器核心（槽位扫描 / 管线执行 / 事件流）

## 执行模型：⚪ OpenCode

## 目标
实现组件编排器主控模块，完成「框架→槽位扫描→资产填充→事件推送→验证交付」的两段式生成主流程。

## 架构依据
`D:\项目\06_组件编排器\组件编排器架构设计.md`（v1.0）——重点精读 §2 总体流程、§3 媒体槽位协议、§7 执行程度、§8 画布观察窗事件流协议、§9 验证闭环。**严格按文档实现，不得自创协议。**

## 交付物
`D:\项目\06_组件编排器\orchestrator.py`

## 接口契约

```python
# -*- coding: utf-8 -*-
"""组件编排器主控 —— 两段式生成 + 槽位填充 + SSE 事件流"""

class Orchestrator:
    def __init__(self, lesson_dir: str, autonomy: str = "L2"):
        """lesson_dir=课时文件夹（HTML 与资产平铺）；autonomy=L1/L2/L3"""

    def scan_slots(self, html_path: str) -> list:
        """扫描 HTML 中所有 <!-- MEDIA:... --> 槽位注释，返回结构化槽位列表
        槽位 dict：{id, type(img|video), topic, prompt|keyword, source, mode, status, line_no}"""

    def fill_slot(self, slot: dict, component_registry) -> dict:
        """按槽位 type 路由到对应组件（image_gen / video_embed），
        组件成功后：资产写入 lesson_dir、HTML 注释替换为真实标签、status=done
        失败：按规则卡 fallback 重试（≤max_retry），仍失败 status=failed 并推送事件"""

    def run(self, html_path: str, event_callback=None) -> dict:
        """主流程：scan_slots → 逐槽位 fill_slot → 验证闭环
        每个阶段通过 event_callback 推送 SSE 事件（协议见架构 §8）
        autonomy=L2 时在「槽位清单确认」节点暂停等待确认信号
        返回 {done, failed, skipped, elapsed_s}"""

    def verify(self, html_path: str) -> dict:
        """资产校验：无 pending/failed 残留、引用文件存在、图片可解码、BV 号有效"""
```

## 槽位解析正则（协议 §3）
```
<!-- MEDIA:(img|video) id=(\S+) topic="([^"]+)" (prompt|keyword)="([^"]+)" source=(\S+)? mode=(download|embed) status=(\w+) -->
```
注意：字段间为单个空格，引号为英文直引号，source 仅 video 有。解析失败要给出明确行号报错。

## 事件流（协议 §8）
每条事件 JSON：`{"ts","phase","slot","event","detail"}`，phase ∈ framework/scan/asset_fill/verify/deliver，event ∈ prompt_ready/generating/done/retry/failed/slot_list_confirm。

## 集成约定
- 组件注册表：`06_组件编排器\components\` 下的组件模块由 task_014/015 实现，本任务只定义调用约定：`component.run(slot, rule_card_path) -> {"ok": bool, "asset": str|None, "error": str}`
- 规则卡加载：PyYAML 读取 `06_组件编排器\组件规则卡\*.yaml`
- 不实现具体组件逻辑（那是 014/015 的事），用 mock 组件做联调自测

## 验收标准
- 构造含 3 图 1 视频槽位的测试 HTML，mock 组件下 run() 全流程走通
- 槽位替换后 HTML 中无 `status=pending` 残留
- 事件序列与 §8 协议字段完全一致
- L2 档位在槽位清单节点正确暂停/恢复
- `python -m py_compile orchestrator.py` 通过

## 完成记录
（执行后填写）
