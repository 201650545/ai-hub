# 搜索网关优化上下文（给 GPT 强读）

> 用途：让 GPT 基于系统真实代码与实测数据给出针对性方案。本文件 = 上下文 + 部分提示词，聊天窗口只留一句话引用。

## 1. 系统链路
- DSH（AI 客户端）→ hub-web-search 插件 → `GET :3000/api/search_json?q=&engines=` → `content_pool.run_search` → 各引擎浏览器会话提问抓答 → `llm_summarize`（走 :3100 的 deepseek-v4-flash）→ 返回 records + summary
- 8 引擎：yuanbao(元宝) / doubao(豆包) / kimi(月之暗面) / qianwen(通义千问) / metaso(秘塔) / grok(xAI) / perplexity / zai(智谱 GLM)。每个引擎 = opencli 控制的浏览器网页会话，真实打开 AI 搜索站、自动填问题、点发送、轮询提取正文
- 单引擎超时：默认约 90s 轮询上限；zai 300s（深度思考低档也可能 >4 分钟）
- `run_search`：对选定引擎各起一个线程，`join(timeout=150)` 等所有线程结束（或各自超时），然后 `llm_summarize`，返回 records+summary

## 2. 2026-08-30 实测（8 引擎一次真实搜索）

| 渠道 | 状态 | 耗时 | 回答长度 |
|------|------|------|---------|
| yuanbao | ok | 43.9s | 1819 |
| doubao | ok | 38.9s | 28（太短，几乎无内容）|
| kimi | timeout | 156.0s | 0 |
| qianwen | timeout | 173.7s | 0 |
| metaso | ok | 36.1s | 505 |
| grok | ok | 59.9s | 905 |
| perplexity | ok | 39.3s | 1699 |
| zai | ok | 107.2s | 242 |

**关键结论**：默认 4 引擎组合（yuanbao+doubao+kimi+qianwen）里 kimi/qianwen 双双超时、doubao 只回 28 字——组合质量差；稳定且快的渠道是 metaso(36s)/perplexity(39s)/yuanbao(44s)/grok(60s)/zai(107s)。

## 3. 四个待解决问题
1. **渠道选定**：基于上述实测，默认组合应换成哪些？GPT 之前建议"默认 yuanbao+doubao+kimi+qianwen"与实测矛盾，请结合实测修订，给出：默认组合 / 深度组合 / 手动 full 的选定表。
2. **总结触发**：GPT 方案 = record 状态统一 STARTED→SENT→ANSWERED，失败态 EMPTY/ERROR/TIMEOUT，只有 ANSWERED 算成功；默认 4 路 quorum=3，扩展 6-8 路 ceil(n*0.6)；soft_deadline=120s（达 quorum 立即总结），hard_deadline=145s（无论数量强制总结，给 DSH 180s 留余量）。请确认是否最优，并给出 `run_search` 的改法要点。
3. **插件 hub-web-search 健壮性**：GPT 方案 = 每条 record 带 engine/status/answer/urls/elapsed/error；过滤空回答、URL 去重；content 前置"成功 3/4，qianwen timeout"避免模型误以为全量；summary 失败 fallback 为成功渠道拼接；零成功返回明确错误而非空内容。请确认 + 补充。
4. **资讯结合**：GPT 方案 = 独立 aihot provider（aihot.virxact.com 匿名 API），仅"AI 新闻/模型发布/融资/产品更新/今日热点"等意图触发，不默认混入普通搜索；与网页引擎共同送 summarizer，标记 source_type=ai_news；支持显式 `engines=["kimi","aihot"]`。请确认设计。

## 4. 约束
- 网关 = 单机 Python `http.server` + 线程模型；引擎是网页会话（非 API），"快"受浏览器渲染/反爬影响；DSH 同步 HTTP 调用，180s 超时。
- 请给出：修订后渠道选定表、总结触发最终策略（含 run_search 代码改法）、插件改法、aihot provider 设计。中文、可执行优先、600 字内。
