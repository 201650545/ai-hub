import json
import urllib.request

url = "https://openrouter.ai/api/v1/models"
try:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))["data"]
        ds_models = [m for m in data if "deepseek" in m["id"].lower()]
        print(f"✅ Found {len(ds_models)} DeepSeek models on OpenRouter API:\n")
        for m in ds_models:
            pricing = m.get("pricing", {})
            prompt_cost = float(pricing.get("prompt", 0)) * 1_000_000
            completion_cost = float(pricing.get("completion", 0)) * 1_000_000
            print(f"Model ID: {m['id']}")
            print(f"  Name: {m.get('name')}")
            print(f"  Prompt Price: ${prompt_cost:.4f} / 1M tokens")
            print(f"  Completion Price: ${completion_cost:.4f} / 1M tokens")
            print("-" * 50)
except Exception as e:
    print("❌ Error fetching OpenRouter models API:", e)
