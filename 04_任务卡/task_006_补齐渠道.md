# 任务卡 006：补齐 4 个 LLM 渠道

## 目标
为 Groq / 硅基流动 / 通义 DashScope / 智谱 GLM 4 个渠道填写 key 并验证可用。

## 渠道配置（channels.py 已定义）

| 渠道 | 环境变量 | 免费额度 | 默认模型 |
|------|---------|---------|---------|
| Groq | - | 1000次/天 | gpt-oss-120b |
| 硅基流动 | - | 赠送 ¥14 | deepseek-ai/DeepSeek-V3 |
| 通义 DashScope | - | 新用户赠送 | qwen-plus |
| 智谱 GLM | - | Flash 免费 | glm-4-flash |

## 实现步骤
1. 在各厂商官网注册账号，获取 API key
2. 通过网页「渠道管理」页填入 key（存 channels.json）
3. 或直接在 `config/channels.json` 中填写
4. 验证各渠道能正常调用（发送测试请求）

## 各厂商注册地址
- Groq: https://console.groq.com/
- 硅基流动: https://cloud.siliconflow.cn/
- 通义 DashScope: https://dashscope.aliyun.com/
- 智谱 GLM: https://open.bigmodel.cn/

## 验收标准
- 4 个渠道的 key 已填写
- 每个渠道能成功发送请求并收到回复
- 渠道管理页显示各渠道状态为 active
- fallback 链能正确路由到可用渠道

## 完成记录
- 完成时间：2026-08-06 09:00
- 执行模型：DeepSeek V4 Flash 0731
- 完成内容：
  1. channels.py 为 4 个新渠道补全 env_key：GROQ_API_KEY / SILICONFLOW_API_KEY / DASHSCOPE_API_KEY / ZHIPU_API_KEY（原为空，只能走 channels.json；现环境变量也可直接生效）
  2. config/channels.json（gitignore）预留 4 渠道 key 位，与 get_key 三级读取打通
  3. 新增 `02_网关实例\ds_v4_cli\test_channels.py`：`python test_channels.py`（健康报告）、`--ping groq`（实际请求）、`--fallback`（路由链测试）
  4. fallback 链验证通过：deepseek-v4-flash→deepseek；gemini-*→gemini；gpt-oss-120b→groq；qwen-plus→dashscope；glm-4-flash→zhipu；deepseek-ai/DeepSeek-V3 命中 deepseek 前缀；未知模型走 DEFAULT_CHAIN 并按 key 就绪跳过未配置渠道
- 验收结果：4 渠道模型路由与 fallback 逻辑全部正确；deepseek/gemini/openrouter（env/config 读取）实测 reachable=True；groq/siliconflow/dashscope/zhipu 状态正确显示「待填 key」（因无真实 key，未能发真实请求）。
- 遗留问题：4 渠道 key 需用户在各厂商官网注册后填写（网页「渠道管理」页 或 config/channels.json 或环境变量）；填入后运行 `python test_channels.py --ping groq --ping siliconflow --ping dashscope --ping zhipu` 即可逐个验证。
