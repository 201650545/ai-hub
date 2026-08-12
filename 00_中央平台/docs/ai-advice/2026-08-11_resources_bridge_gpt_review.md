# 高级 AI 审阅回复：ai-resource-hub 资源清单雏形（子项目①）

> 回复来源：GPT 镜像站（vip-17，GPT-5.6 Extended）
> 问诊时间：2026-08-11 ｜ 问诊包：[2026-08-11_resources_bridge_prototype.md](./2026-08-11_resources_bridge_prototype.md)
> 投递方式：问诊包推 GitHub（ai-hub commit `941ff13`）→ GPT 直读仓库文件
> 结论速览：**方向正确、可给人看，但先补 3 个 P0 再作稳定展示版**；不需要复杂架构。

---

## 1. 结论

整体方向是对的：针对"给人看 + 验证 飞书→桥→GitHub Pages→门户→Dashboard 链路"这个目标，没有需要推倒重来的架构缺陷，FastAPI 同源代理、remote/local/auto 验证钩子和本地回退都应该保留。

但不建议当前代码原样作为稳定展示版；先补三个小而关键的问题即可：**前端安全渲染、数据/build 一致性校验、缓存与 freshness 修正**，不需要引入数据库、Redis、队列等复杂设施。

## 2. 建议方案

### P0 — 前端不要把资源数据直接拼进 innerHTML

当前 capability_id、资源名称、平台、模型名、额度状态等字段都未经转义直接进入 HTML；数据虽然来自自己的公开桥，但上游实际来自资源表，因此这相当于把上游文本当成 HTML 信任，存在 DOM/XSS 注入面。

最小修改：普通字段全部用 textContent 创建 `<td>`；badge 也用 DOM 节点生成，而不是字符串拼 HTML。

### P0 — 增加最薄的一层响应结构校验

现在只判断 `all(files.values())`，无法判断 index.json 是不是对象、capabilities.json/instances.json 是不是数组；一旦 JSON 合法但结构错了，可能在 `_aggregate()` 或前端 `.map()` 才炸。

至少校验 index: dict、caps/insts: list、关键字段类型；同时把 `all(files.values())` 改成 `all(v is not None for v in files.values())`，否则合法的空数组也会被误判为拉取失败。

### P0 — "全有或全无"还不等于"同一个 build"，需要补一致性保护

现在 3 个远程文件并发 GET，只保证"三个都拿到了"，并不能保证 GitHub Pages 正好发布切换时三者属于同一个 build；代码注释声称这样可以避免混搭 build_id，实际上目前没有完成这个保证。

本轮不改 ai-resource-hub 的前提下，最小方案是 **读 index A → 并发读 capabilities/instances → 再读 index B**，要求 A/B build_id 相同，否则重试一次或回退本地。

### P1 — 修正 freshness：不要把 fresh 结果缓存死

fresh 是 `_aggregate()` 时算出来后一起放入 300 秒缓存的，所以数据可能已经跨过 stale 阈值，缓存里的 fresh=True 仍继续显示最多约 5 分钟。

缓存原始 generated_at/stale_after_hours，每次响应时重新计算 fresh；同时 generated_at 要求带时区，对未来时间/异常时间返回 unknown，避免机器时钟错误产生错误的"新鲜"。

### P1 — 前端不要硬编码 >48h

后端实际上读取 index.freshness.stale_after_hours，但前端陈旧状态固定显示"数据已陈旧 (>48h)"；一旦桥侧把规则改成 24h/72h，Dashboard 会给出错误解释。

直接显示 `> ${meta.stale_after_hours}h`，并让后端返回实际采用的 effective threshold，包括默认值。

### P1 — 本地回退也应有短缓存，并防止缓存击穿

目前只有成功的 remote 会进入 300s 缓存；remote 挂掉时，每次 auto 请求都会重新进行一次远端尝试，然后才读 local，这恰好违背了"反复切 Tab/刷新不要打爆 GitHub Pages"的初衷。

建议 remote 成功缓存 300s，local fallback 缓存例如 30–60s，再加一个简单 asyncio.Lock/single-flight；source=remote/local 继续绕过自动缓存，人工验证能力不受影响。

### P1 — 把 build_id 和回退状态真正展示出来

现在 API 已返回 build_id、bridge_version 等元信息，但 Dashboard 的核心展示只有数量、来源、生成时间和新鲜度；对于"验证链路"，build_id 其实比资源数量更有证明价值。

不用再加复杂页面，只需在资源 Tab 顶部增加一行：build_id / fetched_at / bridge_version / remote|local / cache hit，local 建议用黄色"回退"而不是红色"故障"。

### P2 — 收紧 /api/resources 的接口语义

source 目前只是普通 str，输入 `?source=remtoe` 这样的拼写错误会悄悄落进 auto 分支，不利于人工验证；失败结果也仍然是 HTTP 200。

用 FastAPI `Literal["auto","remote","local"]` 即可解决参数问题；失败 HTTP 状态码可以下一步再规范成 502/503，不必为此重构 bridge 模块。

### P2 — 下一阶段再升级 bridge 发布协议，不要现在上复杂架构

真正稳妥的长期方案，是让 bridge 提供一个 manifest，包含 build_id + 每个 JSON 的 hash，或者按 `/builds/{build_id}/...` 发布不可变文件，从协议层解决混搭问题。
这属于下一步最小协议演进，不是当前展示雏形的上线前置条件，也符合"不修改 ai-resource-hub、本轮只读"的红线。

## 3. 风险

| 严重度 | 风险 | 当前表现 / 后果 |
|---|---|---|
| 高 | 前端动态字段未经转义进入 innerHTML | 上游某字段含 HTML 时会被浏览器当标记解析；应优先改成 textContent/DOM 渲染 |
| 中高 | 无法证明三个远端 JSON 来自同一 build | GitHub Pages 发布切换窗口可能产生逻辑混搭；当前"全有或全无"只能防缺文件，不能防跨 build |
| 中高 | 没有 JSON shape/schema 校验 | 合法但错误格式的数据可能让后端 500，或让前端 `.map()` / `.includes()` 报错，直接把展示页打坏 |
| 中 | freshness 被随 300s cache 固化 | 临界时刻页面可以继续显示"新鲜"；且前端固定写 48h 与桥端规则可能漂移 |
| 中 | remote 故障时 local fallback 不缓存 | 每次请求重新等待远端失败，不仅体验慢，也会在故障期持续请求 GitHub Pages |
| 中 | source 拼写错误静默进入 auto | 人工测试容易得到"看似成功、实际测错路径"的假结论 |
| 中低 | `_load_local()` 只捕获文件不存在和 JSON 错误 | 权限、I/O 等 OSError 仍可能直接冒泡成 500；补捕获和日志即可 |
| 低 | fetched_at 没有时区 | 当前用 time.strftime() 产生 naive 时间；人工比对 generated/build 时容易混淆，建议统一 ISO-8601 UTC |
| 低 | 多进程时每个 worker 有独立缓存 | 对现在的本机雏形完全可以接受；不值得因此引 Redis，等以后真正多实例部署再处理 |

## 4. 实施步骤

**第一步：先做不改变架构的 P0 修补。** 后端增加 `_validate_files()`，校验三份 JSON 类型和必要字段；把 `all(files.values())` 改成显式 `is not None`，本地读取补 OSError 处理。前端把所有来源于资源 JSON 的普通文本从字符串拼接改为 textContent。

**第二步：补远端 build 一致性。** 把 `_fetch_remote()` 改成 index A → capabilities+instances → index B；两个 build_id 一致才接受，否则重试一次，仍不一致就走现有 local 原子回退。这样不需要修改数据桥仓库，也不破坏现有三种 source 钩子。

**第三步：修缓存和 freshness。** 缓存计时改用 `time.monotonic()`；remote 成功 TTL 保持 300s，local fallback 给一个短 TTL，并做 single-flight 防并发重复拉取。fresh 在每次返回前根据 generated_at + effective stale_after_hours 重新计算，fetched_at 改为带 UTC 时区的 ISO 时间。

**第四步：增强"验证链路"的可见性。** Dashboard 增加 build_id、bridge_version、实际来源、fetched_at，最好再增加 cache_hit/fallback_reason 两个简单字段。把 local 状态表达为"本地回退/手动本地"，不要统一染成故障红色。

**第五步：把 API 参数收紧。** source 改成 Literal/Enum；先保持现有 JSON 返回结构以避免扩大改动面，等页面稳定后再决定是否把失败状态规范为 HTTP 502/503。

**第六步：上线前只跑一组针对性测试，不做大测试体系。** 至少覆盖：remote 全正常、remote 单文件失败+local 正常、remote 非法 JSON、local 缺文件、两边都失败、空数组、stale 数据、发布过程中 build_id 改变，以及字段中放入 `<img ...>` 之类文本确认页面只按文本显示。

通过这组测试后，GPT 认为已达到**"可以稳定给人看，并且能可信地验证链路"**的标准。

## 5. 需确认

1. **陈旧数据是否仍算"可用"**：例如 local fallback 已超过 stale_after_hours，产品策略是"继续展示但黄色警告"，还是"认为资源不可用"？这是业务语义，不应由代码自行决定。
2. **local fallback 的身份是什么**：它是正式容灾副本，还是仅用于开发/人工验证？如果是正式容灾，应给短缓存和清晰的 degraded 标记；如果纯测试，则可以更强调"非当前线上数据"。
3. **freshness 的规则谁是唯一权威**：建议明确由 index.json.freshness.stale_after_hours 决定，门户不另设业务常量；字段缺失时是否默认 48h，需要 owner 明确。
4. **展示页对数据的信任边界**：即使飞书表只有内部人员能编辑，也建议按"不可信文本"渲染；如果 owner 明确未来需要某字段支持富文本，则必须另外定义允许的标签/格式，而不能继续任意 innerHTML。
5. **下一阶段是否允许修改 bridge 发布协议**：如果允许，优先做 manifest + hash 或不可变 build_id 路径；如果暂时不允许，就长期保留"双读 index"作为门户侧一致性保护。
6. **失败时是"宁可旧，不可空"还是"宁可报错，不展示旧数据"**：尤其决定未来是否需要"last known good"缓存。当前场景偏资源目录，GPT 倾向于旧数据可展示，但必须明确标记 source、build_id、生成时间和陈旧状态，不要悄悄伪装成最新数据。

---

*（以上为 GPT-5.6 Extended 对问诊包的完整回复，保留原文；仅去除浏览引用卡片噪音。）*
