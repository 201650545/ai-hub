import os
import sys
import json
import argparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# 预设厂商接入点配置
PROVIDERS = {
    "siliconflow": {
        "name": "硅基流动 (SiliconFlow)",
        "env_key": "SILICONFLOW_API_KEY",
        "base_url": "https://api.siliconflow.cn/v1/chat/completions",
        "default_model": "deepseek-ai/DeepSeek-V3",
        "free_info": "赠送约 200万 tokens (¥14)"
    },
    "dashscope": {
        "name": "阿里云百炼 (DashScope)",
        "env_key": "DASHSCOPE_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "default_model": "deepseek-v3",
        "free_info": "每模型赠送 100 万 tokens (90天)"
    },
    "deepseek": {
        "name": "DeepSeek 官方 API",
        "env_key": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/v1/chat/completions",
        "default_model": "deepseek-chat",
        "free_info": "新用户赠送 500 万 tokens"
    },
    "openrouter": {
        "name": "OpenRouter (极致低价/每日免费)",
        "env_key": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1/chat/completions",
        "default_model": "deepseek/deepseek-v4-flash:free",
        "free_info": "免费版 $0/1M (200~1000次/天)；付费版比官方还便宜！"
    }
}

def call_llm(prompt, provider_name="siliconflow", api_key=None, model=None):
    conf = PROVIDERS.get(provider_name.lower())
    if not conf:
        print(f"❌ 未知厂商: {provider_name}。可选厂商: {list(PROVIDERS.keys())}")
        return

    key = api_key or os.environ.get(conf["env_key"])
    if not key:
        print(f"⚠️ 未检测到 {conf['name']} 的 API Key (环境变量 {conf['env_key']})。")
        print(f"💡 请在终端设置: $env:{conf['env_key']}=\"sk-xxx\" 或通过 --key 参数传入。")
        return

    target_model = model or conf["default_model"]
    print(f"🚀 [正在调用 {conf['name']}] 模型: {target_model}...")

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": target_model,
        "messages": [
            {"role": "system", "content": "你是一个高效专业的 AI 助手。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7
    }

    req = Request(conf["base_url"], data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")

    try:
        with urlopen(req) as resp:
            res_body = resp.read().decode("utf-8")
            data = json.loads(res_body)
            content = data["choices"][0]["message"]["content"]
            print("\n" + "="*50)
            print(content)
            print("="*50 + "\n")
    except HTTPError as e:
        err_msg = e.read().decode("utf-8")
        print(f"❌ 请求失败 [HTTP {e.code}]: {err_msg}")
    except URLError as e:
        print(f"❌ 网络链接错误: {e.reason}")
    except Exception as e:
        print(f"❌ 发生异常: {str(e)}")

def main():
    parser = argparse.ArgumentParser(description="DeepSeek V4-Flash 终端统一调用 CLI")
    parser.add_argument("prompt", type=str, nargs="?", help="发给 AI 的提示词/问题")
    parser.add_argument("-p", "--provider", type=str, default="siliconflow", help="选择厂商服务商 (siliconflow / dashscope / deepseek / openrouter)")
    parser.add_argument("-m", "--model", type=str, default=None, help="指定模型 ID")
    parser.add_argument("-k", "--key", type=str, default=None, help="临时 API Key")

    args = parser.parse_args()

    if not args.prompt:
        print("💡 使用示例:")
        print("   python ds-v4.py \"帮我分析八年级英语时态\"")
        print("   python ds-v4.py -p dashscope \"写一段说明文阅读理解\"")
        sys.exit(0)

    call_llm(args.prompt, args.provider, args.key, args.model)

if __name__ == "__main__":
    main()
