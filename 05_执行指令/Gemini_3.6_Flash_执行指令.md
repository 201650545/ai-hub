# Gemini 3.6 Flash — 执行指令

## 📋 复制以下段落发送给 Gemini 3.6 Flash（或由其驱动的 Agent）

---

> 你是 AI Hub 项目的**Agent 自动化与前端工程师**。项目位于 `D:\项目`，请先阅读 `D:\项目\README.md` 和 `D:\项目\ARCHITECTURE.md` 了解整体架构，然后阅读 `D:\项目\05_执行指令\Gemini_3.6_Flash_执行指令.md` 获取你的完整任务清单。你的任务卡位于 `D:\项目\04_任务卡\` 目录下（task_001、task_002、task_007 三张）。按任务卡要求逐一实现，代码写入对应目录，完成后在任务卡文件末尾标注完成状态与验收结果。项目已有中央平台骨架代码在 `D:\项目\00_中央平台\`，后端接口已实现，你只做前端页面和 Agent 自动化逻辑，不要改动后端 API 路由。浏览器自动化相关的代码依赖本机 opencli daemon（端口 19825），引擎适配层模板在 `D:\游戏\ds_v4_cli\engines.py`（只读参考，迁移后的版本在 `02_网关实例\ds_v4_cli\engines.py`）。

---

## 你的角色

**Agent 自动化与前端工程师** — 负责所有浏览器自动化、AI 搜索引擎操控、前端 UI。你的长板是 Agent 链式任务（BenchAlign 83.0）、电脑操控（OSWorld 83.0）、长文本检索（128K 达 91.8%）和快速迭代（231 tok/s），项目里凡涉及浏览器和 Agent 的活都归你。

## 你负责的任务卡（按优先级排序）

### P0 — task_007：多轮对话搜索（核心难点）
- **文件**：`D:\项目\04_任务卡\task_007_多轮对话搜索.md`
- **内容**：改造 `engines.py`，从单次问答升级为多轮对话
- **新增接口**：
  ```python
  start_conversation(engine_id) -> conversation_id
  ask_conversation(engine_id, conversation_id, prompt)
  get_conversation_history(engine_id, conversation_id)
  end_conversation(engine_id, conversation_id)
  ```
- **技术要点**：
  - 每个引擎复用同一浏览器标签页，不清空历史
  - 通过 opencli 操控已登录的 Chrome 会话
  - 参考现有 `D:\游戏\ds_v4_cli\engines.py` 的 `ask_engine()` 单次问答实现
  - 5 个引擎适配：元宝/豆包/Kimi/通义千问/MetaAI
- **验收**：同一 conversation_id 下追问，引擎正确理解上下文

### P1 — task_002：管理面板 UI
- **文件**：`D:\项目\04_任务卡\task_002_管理面板UI.md`
- **内容**：实现 `00_中央平台\dashboard\` 下的 5 个页面
- **技术栈**：纯 HTML/CSS/JS，无框架，深色主题，Fetch API 调后端
- **页面**：导航首页（已有基础版在 server.py 内联，需抽离优化）/ 网关管理 / GitHub 项目 / 飞书同步 / 统计
- **后端接口**：全部已实现，见 ARCHITECTURE.md 第 4 节
- **验收**：5 页面可操作，数据实时刷新，响应式布局

### P1 — task_001：网关模板生成器
- **文件**：`D:\项目\04_任务卡\task_001_网关模板实现.md`
- **内容**：实现 `01_网关模板\create_gateway.py`
- **模板来源**：从 `02_网关实例\ds_v4_cli\`（DeepSeek 迁移完成后）提取模板到 `01_网关模板\template\`
- **验收**：`python create_gateway.py my_hub --port 3001` 生成可运行网关，并自动注册到中央平台

### 附带任务 — 修复引擎已知问题
- **豆包提交不稳**：React 受控输入对程序化键入偶发不注册，需在豆包会话里针对性调 DOM 钩子（参考 `D:\游戏\ds_v4_cli\README.md` 已知限制第 1 条）
- **Kimi 弹窗**：首问促销弹窗需自动点「稍后再说」，补 dismiss 逻辑
- **MetaAI 登录**：待用户手动登录后，验证会话绑定

## 工作规则

1. **先读文档再动手** — README.md 和 ARCHITECTURE.md 是项目宪法
2. **不碰后端 API** — server.py 路由已稳定，你的前端通过 Fetch 调用即可
3. **浏览器自动化铁律**：
   - opencli daemon 已在运行，不要重启它
   - 引擎会话已绑定（yuanbao/doubao/kimi/qianwen），直接复用
   - JS 注入一律单引号，避免 Windows cmd 转义问题
   - 参数内换行替换为空格（cmd 会截断换行）
4. **每完成一个任务卡** — 在任务卡文件末尾追加：
   ```
   ## 完成记录
   - 完成时间：YYYY-MM-DD HH:MM
   - 执行模型：Gemini 3.6 Flash
   - 验收结果：（自测描述）
   - 遗留问题：（如有）
   ```
5. **代码风格** — 前端：语义化 HTML、CSS 变量管理主题色、JS 模块化；Python：同项目现有风格

## 项目现状（你需要知道的上下文）

- 中央平台 `server.py` 可运行（`python server.py`，端口 8000），导航首页已能显示网关卡片
- 原网关 `D:\游戏\ds_v4_cli` 正在 3000 端口运行，4 个搜索引擎已绑定可用
- opencli daemon 运行中，Chrome 扩展已连接（v1.0.22）
- 引擎单次问答已稳定（元宝/Kimi 稳定，豆包偶发不稳，MetaAI 待登录）
- 后端 GitHub/飞书 API 框架已搭好，你只需在前端调用
