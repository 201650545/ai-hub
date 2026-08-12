## 任务转交说明：用 Open CLI 绑定 AI 搜索引擎会话

**项目路径**：`D:\游戏\ds_v4_cli`（Universal AI Hub 统一 AI 聚合网关）

### 目标
用 Open CLI 驱动用户已打开的 Chrome 浏览器，建立 5 大 AI 搜索引擎的真实登录会话，让网页端 `http://localhost:3000` 的 5 个引擎卡片从「未连接」变为「已连接」。

### 关键操作
```bat
cd /d D:\游戏\ds_v4_cli
python setup_engines.py
```
该脚本会通过 `opencli browser <session> open <url>` 逐个打开元宝/豆包/Kimi/通义千问/MetaAI 标签页，用户在弹出的标签页完成登录后重跑一次，即可全部绑定。

### 重要前提（务必先确认）
1. **必须在真实环境执行**，不要用任何沙箱/虚拟终端。确认 `node` 指向 `D:\Program Files\nodejs\node.exe`（v24），且 PATH 包含 `C:\Users\郭永涛\AppData\Roaming\npm`。
2. **opencli 已安装且可用**（v1.8.6，位于 npm 全局），依赖完整。若报 `node_modules` 缺失，说明被沙箱污染，需在真实环境用 `npm install -g @jackwener/opencli` 重装。
3. 若某个引擎显示「未连接」，重新运行 `setup_engines.py` 刷新；Kimi 首问需点「稍后再说」关掉促销弹窗。

### 当前网关状态
- 网关 `python unified_gateway.py` 已在 3000 端口运行，页面正常。
- LLM 渠道 DeepSeek/Gemini/OpenRouter 已接通；Groq/硅基/通义/智谱待填 key（网页渠道管理页可填）。
- 已修复启动阻塞（引擎/渠道健康检查改为并发）和「渠道管理」页空白（补全 `renderChannelTable`/`fillKey` 函数）。

### 交接注意
- 引擎会话绑定成功后，直接访问 `http://localhost:3000` 即可在自由画布拖拽 5 引擎做并发检索。
- 若遇浏览器掉线，重跑 `setup_engines.py` 即可。