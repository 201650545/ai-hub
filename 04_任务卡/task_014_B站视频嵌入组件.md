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
- 2026-08-07 完成（OpenCode）
- 交付 `06_组件编排器\components\video_embed_bilibili.py`：`run / search_candidates / validate_bv / build_iframe`
- 检索主路径：规则卡 search_url_tpl（`search.bilibili.com/all`）搜索页 HTML 解析视频卡片（BV via href、标题 via img alt、时长 via duration span），规避官方 API 的 412 风控；`_search_api` JSON API 作降级通道
- 儿童内容偏好排序：标题含教学/儿歌/动画/英文关键词优先，其次时长 ≤10 分钟（`_sort_kid_preferred`）
- `validate_bv`：请求视频页校验 200 + 排除「视频不见了/出错了/已删除/仅限/无法播放」等失效标记；伪造 BV / 格式错返回 False
- `build_iframe`：按规则卡 embed_tpl 渲染响应式 iframe（16:9、autoplay=0、danmaku=0）；无卡片模板时用架构 §5 兜底模板
- `run` 契约：`{"ok","asset"(iframe),"bv","error"}`，缺 keyword 拒绝；候选逐个 validate_bv，均不可嵌入时走 AI Hub 网关 AI 搜索辅助选型降级
- orchestrator.fill_slot 兼容组件模块（.run）与可调用对象；编排器↔真实组件联调通过（iframe 回填 + verify 全绿）
- 测试 `tests\test_video_embed.py` 8 用例全过（BV 正则/排序/模板/非法BV/validate/search/run/缺keyword）；全套 run_all 42/42
- 遗留：AI 搜索降级仅在候选全空时触发；B站搜索页结构若大幅改版需按规则卡 search_url_tpl 巡检更新
