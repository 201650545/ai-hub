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
