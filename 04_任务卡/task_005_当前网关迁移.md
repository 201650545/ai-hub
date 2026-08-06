# 任务卡 005：当前网关迁移

## 目标
将 `D:\游戏\ds_v4_cli` 迁移到 `D:\项目\02_网关实例\ds_v4_cli`，并接入中央平台。

## 迁移步骤
1. 复制 `D:\游戏\ds_v4_cli` 下所有文件到 `02_网关实例/ds_v4_cli/`
2. 删除敏感信息（channels.json 中的真实 key 用环境变量替代）
3. 修改 `engines.py` 中的 `OPENCLI` 路径为相对路径或环境变量
4. 添加网关启动时的自动注册逻辑（POST 到中央平台 :8000）
5. 添加心跳上报（每 30 秒 POST /api/gateways/ds_v4_cli/heartbeat）
6. 添加退出时的自动注销（POST /api/gateways/ds_v4_cli/unregister）

## 修改点

### unified_gateway.py
- 添加启动注册：网关启动时自动向中央平台注册
- 添加心跳线程：定期上报在线状态
- 添加退出钩子：进程退出时自动注销

### channels.py
- 保持现有逻辑不变
- 确保 channels.json 的路径相对于网关目录

### engines.py
- 修复 `OPENCLI` 路径问题（当前硬编码了 node v24 路径）
- 建议使用环境变量或自动检测

## 验收标准
- 网关能正常启动在 :3000
- 中央平台 :8000 能看到网关已注册且在线
- 网关停止后中央平台显示离线
- 所有原有功能正常（渠道对话、AI 搜索、渠道管理）

## 完成记录
- 完成时间：2026-08-06 09:00
- 执行模型：DeepSeek V4 Flash 0731
- 完成内容：
  1. 迁移 `D:\游戏\ds_v4_cli` → `02_网关实例\ds_v4_cli\`（保留全部源码/页面/配置）
  2. 清理敏感 key：openrouter key 从本地 channels.json 移入 `config/channels.json`（gitignore 不入库）；my_ai_gateway.py 硬编码的 zscc/zenmux key 改为读取环境变量 ZSCC_API_KEY / ZENMUX_API_KEY
  3. channels.py 的 get_key 增补「环境变量 > config/channels.json > 本地 channels.json」三级读取
  4. engines.py 的 OPENCLI 路径改造为自动检测：优先 OPENCLI_SCRIPT / OPENCLI 环境变量，其次 shutil.which("node") / ("opencli")，再 npm 全局 @jackwener/opencli，彻底去除硬编码本机路径
  5. unified_gateway.py 新增 CentralRegistry 类：启动注册 POST /api/gateways → 每 30s 心跳 → 退出（atexit + finally）注销；端口/网关名/中央地址均可用环境变量覆盖
  6. setup_engines.py 改为相对路径 + 复用 engines._cli_prefix()
  7. 依需求替换引擎：移除 metaai，新增 grok / perplexity 两个引擎（ENGINE_ORDER 已更新）
  8. 中央平台模板改为以 github_manager.py 为准（见 task_004 完成记录）
- 验收结果：中央平台 :8000 已见网关 `ds_v4_cli` 注册，status=online，心跳 last_seen 持续更新；:3000 端口监听正常；/api/channels 健康探测正常（deepseek/gemini/openrouter 可达）；OPENCLI 自动检测在未设环境变量时正确解析本机 node+main.js。
- 遗留问题：
   - 4 个新 LLM 渠道（groq/siliconflow/dashscope/zhipu）无 key，需用户注册后填入（见 task_006）
   - grok / perplexity 引擎仍在测试中（opencli 浏览器会话需首次登录），其 DOM 选择器可能需微调
