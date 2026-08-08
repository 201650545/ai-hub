# 任务卡 014：B站视频嵌入组件

## 执行模型：⚪ OpenCode

## 目标
实现 video_embed 组件，按槽位 keyword 检索 B站视频、提取 BV 号、生成 iframe 嵌入代码并回填 HTML。

## 架构依据
`D:\项目\06_组件编排器\组件编排器架构设计.md` §5（已定案：只嵌入不下载，autoplay=0，响应式 16:9）。
规则卡：`D:\项目\06_组件编排器\组件规则卡\video_embed_bilibili.yaml`（模板与选择器以此为准）。

## 交付物
`D:\项目\06_组件编排器\components\video_embed_bilibili.py`

## 接口契约（与 task_013 编排器对齐）

```python
# -*- coding: utf-8 -*-
"""B站视频嵌入组件 —— 检索 → BV 校验 → iframe 回填"""

def run(slot: dict, rule_card_path: str) -> dict:
    """slot 含 {id, keyword, mode=embed, source=bilibili}
    返回 {"ok": bool, "asset": "<iframe html 字符串>"|None, "bv": str|None, "error": str}"""

def search_candidates(keyword: str, limit: int = 5) -> list:
    """B站搜索页检索候选，返回 [{bv, title, duration, url}]
    实现方式：httpx 请求 search_url_tpl，正则提取 BV 与标题；
    若搜索页结构变动，降级为通过 AI Hub 网关的 AI 搜索引擎辅助选型（http://localhost:3000）"""

def validate_bv(bv: str) -> bool:
    """校验视频存在且允许嵌入（请求视频页，检查 404/区域限制/禁止站外播放标记）"""

def build_iframe(bv: str) -> str:
    """按规则卡 embed_tpl 生成响应式 iframe 代码（16:9、autoplay=0、danmaku=0）"""
```

## 实现要点
1. **BV 号正则**：`BV[0-9A-Za-z]{10}`，注意区分大小写
2. **嵌入校验**：部分视频禁止站外播放（response 含「-404」或地区限制提示），遇此换下一个候选
3. **儿童内容偏好**：课件场景优先选择时长 ≤10 分钟、标题含教学/儿歌/动画关键词的候选
4. **fallback**：连续 2 个关键词检索无可用结果 → 返回 ok=False, error 说明，由编排器标红
5. 不登录态实现；如搜索被风控（412），加随机 User-Agent 与 1-2s 间隔

## 验收标准
- `search_candidates("English number song kids")` 返回 ≥3 个候选且含 BV 号
- `validate_bv` 对已知有效 BV 返回 True，对伪造 BV 返回 False
- `build_iframe` 输出与规则卡模板一致
- 单测文件 `tests\test_video_embed.py` 全部通过
- `python -m py_compile` 通过

## 完成记录
（执行后填写）
