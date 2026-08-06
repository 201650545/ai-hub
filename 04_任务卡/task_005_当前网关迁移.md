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
