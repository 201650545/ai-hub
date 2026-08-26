# Fast 渠道 95% 提前切换策略（v2 · 已实施）

> 状态：**已实施（2026-08-26）**。v1 草案经 ChatGPT Extended 评审后推翻核心实现方式，
> 按 v2「原子准入闸门」落地。关联代码：`rate_limit.py`（admission gate）、
> `api_gateway.py`（路由捕获 RateLimitSkip）、`channels.py`（每次 HTTP attempt 预占）。

## 1. 背景

`:3100` 按用户排定的渠道顺序逐个尝试转发。部分渠道 Fast/免费模型有 rpm/rpd 上限，
打满吃 429。task_044 先上了纯记录台账；本任务把它升级为准入控制器。

## 2. GPT Extended 评审结论（2026-08-26，六问压缩）

| 问题 | 结论 |
|---|---|
| Q1 抖动 | 用滞后区间不用固定冷却；且用整数门槛 trip=ceil(95%)、resume=floor(85%)（20→19/17，70% 对低 RPM 渠道闲置太多） |
| Q2 口径 | 不搞死板 channel×model 两级；policy 声明 scope+match。OpenRouter free 是**账号级共享池**（20/min + 50/day total），不按模型各自算 |
| Q3 unknown 自适应 | **429 只学 cooldown 不学永久 RPM**（偶发拥堵会被学成错误上限）；Retry-After 优先，否则指数退避 15/30/60/120/300s，成功清零 = 轻量熔断器 |
| Q4 并发 | 「先查再打点」会穿透（10 线程同读 94% 全打入）；必须原子 try_acquire（锁内 prune→判断→预占），deque+Lock 够，不需要 token bucket；锁内绝无 IO/HTTP |
| Q5 与 key 池关系 | 分层：共享配额 gate 在 key 轮换之外；**每个真实 HTTP attempt 都要预占一次**（轮一圈 key = N 次上游请求）；同 quota 池内换 key 无意义、free 层失败请求也烧日额度 |
| Q6 rpd | 必须纳入——50/day 比 20/min 更需要保护；rolling 24h 起步（比猜错的 calendar reset 安全）；**day 计数要跨重启持久化**，1m/1h 纯内存即可 |

另纠正：OpenRouter 日限额语义是「曾购 $10 credits 则 1000/day」一次性门槛，非余额恒 ≥$10。

## 3. 最终实现（rate_limit.py v2）

- **try_acquire(cid, model, key)**：路由关键路径唯一决策入口。一把 `threading.Lock`
  内完成 清窗口→判断→预占，30 线程并发实测精确放行 trip_at=19 个（v1 会穿透到 28）。
- **滞后状态机**：`trip_at=ceil(limit*0.95)` 触发 THROTTLED；全部规则窗口回落到
  `floor(limit*0.85)` 才回 OPEN；`blocked_until`（429 熔断）优先于一切。
- **record_result()**：429 → Retry-After 优先、否则指数退避设 blocked_until；
  2xx → 连续 429 计数清零（不清封禁，到点自然解除）。unknown 渠道无静态阈值但同享熔断。
- **scope**：xiaohongshu=channel 整渠道一桶；openrouter=credential 每 key 一桶
  （池内三把 key 是三个独立账号，free 额度各算各的，不乘也不共享）。
  free 池与非 free 请求再分桶（`|free` 后缀），付费模型不被 free 阈值误伤。
- **记账粒度**：channels.chat_completion 的 key 循环内**每次真实 HTTP attempt 前
  try_acquire**；某把 key 被拒只跳该 key，全部被拒才抛 `RateLimitSkip` →
  route_completion 记一条错误、走下一渠道（用户顺序永不重排）。
- **持久化**：24h 日额度时间戳落盘 `data/search_gateway/rate_limit_day.json`
  （tmp+rename 原子替换，锁内 ~1KB 写无感知延迟）；1m/1h 重启即失，可接受。
- **事件日志**：只在 OPEN⇄THROTTLED / 熔断触发时记一条（deque maxlen=50），
  skip 走累计计数防刷屏；`GET /api/rate-limits` 返回 `{channels, events}`。

## 4. 边界与约束（沿用）

- 不改变用户排定的渠道顺序——提前切换只是临时跳过。
- zscc 渠道禁主动压测；台账数字只能被动观测。
- 本地/网络异常不回滚预占（无法确认请求是否发出，保守多占一个窗口位）。
- 时间轴用墙钟而非 monotonic：日窗口要跨重启落盘，NTP 微调影响可忽略。
- 单进程 threading.Lock 够用；若未来换 gunicorn 多 worker 需改 Redis（现在不上）。

## 5. 验证记录（2026-08-26）

仿真 6 场景全过：①30 并发放行恰 19+throttled+skipped 11；②滑空自动恢复；
③Retry-After 熔断生效；④free 双 key 各自 19、paid 同 key 全放行（分桶正确）；
⑤unknown 渠道一次 429 即熔断；⑥事件只记翻转 + day 落盘重建。
