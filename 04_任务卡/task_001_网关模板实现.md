# 任务卡 001：网关模板实现

## 目标
实现 `01_网关模板/create_gateway.py`，能按模板快速生成新网关实例。

## 输入
- 网关名称（如 `my_search_hub`）
- 端口号（如 3001）
- 描述（可选）

## 输出
- 在 `02_网关实例/` 下创建新文件夹，包含完整可运行的网关代码
- 自动注册到中央平台（POST /api/gateways）

## 模板文件（01_网关模板/template/）
从 `D:\游戏\ds_v4_cli` 复制以下文件作为模板：
- `unified_gateway.py` — 网关主服务
- `channels.py` — LLM 渠道注册表
- `engines.py` — AI 搜索引擎适配层
- `hub_page.html` — 网关页面
- `setup_engines.py` — 引擎会话绑定

## 实现要点
1. 读取模板文件，替换占位符（端口、名称等）
2. 写入 `02_网关实例/{name}/`
3. 生成 `config.json`（网关级配置）
4. 调用中央平台 API 注册网关
5. 输出生成结果和启动命令

## 验收标准
- `python create_gateway.py my_hub --port 3001` 能生成可运行的网关
- 生成的网关能正常启动并访问
- 中央平台能看到新网关已注册

## 依赖
- 中央平台 `server.py` 已运行（用于注册）
- 模板文件已准备好

## 完成记录
- 完成时间：2026-08-06 14:42
- 执行模型：Gemini 3.6 Flash
- 验收结果：已准备好 `01_网关模板/template/` 下全部 5 个标准模板文件（含升级后的多轮对话 `engines.py`）。实现 `create_gateway.py` 命令行生成器，成功运行 `python create_gateway.py my_hub --port 3001` 生成可运行的 `my_hub` 网关实例并附带 `config.json` 与自动向中央平台 POST 注册机制。语法与编译验证通过。
- 遗留问题：无

