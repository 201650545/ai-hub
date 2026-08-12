# Universal AI Hub（统一 AI 聚合站）

单一 `:3000` 入口，**我的 API + 网上免费 API + AI 搜索**一站聚合。无数据库，Python `http.server` + 多线程。

**三大模块**：
1. **💬 渠道对话**：多渠道 LLM 聚合，模型自动路由 + 失败自动 fallback
2. **🌐 AI 搜索**：4 大真实 AI 搜索引擎（元宝/Kimi/秘塔/豆包）并发检索对比
3. **📡 渠道管理**：渠道状态大盘 + 免费渠道 key 网页填写（存 channels.json）

## 文件
| 文件 | 作用 |
|---|---|
| `unified_gateway.py` | 网关主服务（:3000，多 Tab 聚合站） |
| `hub_page.html` | 聚合站页面（苹果风简约 UI，独立文件便于改样式） |
| `channels.py` | LLM 渠道注册表 + 健康检查 + OpenAI 兼容转发 |
| `engines.py` | AI 搜索适配层：opencli 浏览器会话操控 4 大引擎 |
| `setup_engines.py` | 一次性建立/核对引擎浏览器会话 |
| `channels.json` | 网页填写的免费渠道 key（明文本机） |
| `README.md` | 本文档 |

## LLM 渠道
| 渠道 | Key 来源 | 状态 |
|---|---|---|
| DeepSeek 官方 | env `DEEPSEEK_API_KEY` | ✅ 已接通 |
| Google Gemini | env `GOOGLE_API_KEY` | ✅ 已接通（gemini-2.5-flash 等） |
| OpenRouter 免费池 | env 或 channels.json | ✅ 已接通（14+ 免费模型） |
| Groq / 硅基流动 / 通义 / 智谱 | 网页「渠道管理」填入 | ⚪ 待填 key |

手机端 Pi Agent / Chatbox：`Base URL http://<局域网IP>:3000/v1`，Model 可填
`deepseek-v4-flash` / `gemini-2.5-flash` / `yuanbao-search` / 任意 openrouter 免费模型名。

## 启动
```bat
python setup_engines.py          :: 建立 4 个引擎标签页会话（首次需在各站点登录）
set DEEPSEEK_API_KEY=你的官方key  :: 手机端通用 LLM 上游
python unified_gateway.py        :: 启动网关
```
> 注意：Shell 里可能有残留的旧 `DEEPSEEK_API_KEY`（如 zscc 中转 key），务必用官方 key 覆盖。
> 网页端：`http://localhost:3000/`；手机端：`http://<局域网IP>:3000/v1`

## 端点
- `GET /` 四引擎对比网页（SSE 打字流）
- `GET /api/unified_stream?prompt=` 网页 SSE 事件流
- `GET /api/health` 各引擎会话 + LLM 上游状态
- `GET /v1/models` 模型列表
- `POST /v1/chat/completions` OpenAI 兼容（JSON / SSE）
  - `model=yuanbao-search` → 腾讯元宝网页端真实检索（`stream:true` 打字流）
  - `model=deepseek-v4-flash` / `deepseek-chat` / `deepseek-reasoner` → DeepSeek 官方 API 代理

## 引擎适配器实测记录（2026-08-04）
| 引擎 | 会话 | 输入 | 提交 | 提取 | 状态 |
|---|---|---|---|---|---|
| 腾讯元宝 | yuanbao | fill `[contenteditable=true]` | click `#yuanbao-send-btn`（Enter 无效） | `hyc-common-markdown-style` 非 `-cot` 块 | ✅ 稳定 |
| Kimi | kimi | fill `[contenteditable=true]` | `keys Enter`（先关掉促销弹窗） | 通用 markdown 选择器 | ✅ 稳定 |
| 秘塔 | metaso | `type` textarea（React 须真实键入） | JS `[data-testid^=SendArrowButton].click()`（CDP click 无效） | 通用 markdown 选择器 | ✅ 稳定（~30-75s） |
| 字节豆包 | doubao | `type` textarea | JS `[class*=send-btn-wrapper] button.click()` | 无 class 的 `div` 最大文本块 | ⚠️ 不稳（React 受控状态偶发不注册，提交空消息；首次曾成功） |

## 已知限制 / 待办
1. **豆包提交不稳**：React 受控输入对程序化键入（即使 CDP 真实按键）偶发不注册，点发送提交空消息。
   建议后续在豆包会话里人工确认一次正常交互后，再针对性调 DOM 钩子。
2. **并发争用**：4 引擎同时打 opencli daemon（单会话串行），耗时约为单个引擎的 2-4 倍；
   未连接/失败引擎不阻塞其他引擎，网页端卡片如实显示状态。
3. **弹窗**：Kimi 会弹会员促销弹窗，首问需先点「稍后再说」；遇新弹窗需补 dismiss 逻辑。
4. **会话漂移**：`tab new`/`open` 会切换会话默认标签页，若某引擎 health 变 `about:blank`，
   重跑 `setup_engines.py` 即可恢复。
5. 网页端元宝卡片的引用数取自正文 `Found N references`，其余引擎 refs=0（暂未解析来源列表）。

## 手机端接入示例（Pi Agent / Chatbox）
```
Base URL: http://192.168.1.134:3000/v1
Model  : yuanbao-search   （元宝微信生态+全网搜索，带引用）
       : deepseek-v4-flash （DeepSeek 官方）
API Key: 任意填写
```
