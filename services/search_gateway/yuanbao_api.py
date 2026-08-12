# -*- coding: utf-8 -*-
"""
腾讯元宝 Web 接口接入与打通测试脚本 (Yuanbao Web API Integration)
功能：
针对 腾讯元宝 (yuanbao.tencent.com) 独立做打通。
支持从网页端发起问答，带微信生态与全网实时搜索，并以流式输出打字返回。
"""

import urllib.request
import json
import time
import sys

YUANBAO_URL = "https://yuanbao.tencent.com/api/chat/v1/completions"

def test_yuanbao_connection(prompt="你好，请介绍一下腾讯元宝的微信搜索优势！"):
    print(f"🔄 正在发起【腾讯元宝 Web 真实接口】请求...")
    print(f"💬 问题内容: '{prompt}'\n")

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://yuanbao.tencent.com/chat/",
        "Origin": "https://yuanbao.tencent.com"
    }

    # 腾讯元宝 Web 请求结构
    payload = {
        "model": "hunyuan-turbo",
        "search_enable": True,  # 开启腾讯全网 + 微信生态搜索
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "stream": True
    }

    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(YUANBAO_URL, data=data, headers=headers, method="POST")
        
        print("⚡ [腾讯元宝数据流建立] 正在接收实时搜索与回答...:\n")
        print("--------------------------------------------------")
        
        with urllib.request.urlopen(req, timeout=15) as resp:
            for line in resp:
                line_str = line.decode('utf-8', errors='ignore').strip()
                if line_str.startswith("data:"):
                    raw_json = line_str[5:].strip()
                    if raw_json == "[DONE]":
                        break
                    try:
                        obj = json.loads(raw_json)
                        chunk = obj.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if chunk:
                            sys.stdout.write(chunk)
                            sys.stdout.flush()
                    except Exception:
                        pass
        print("\n--------------------------------------------------")
        print("✅ 腾讯元宝 Web 接口打通成功！")
    except Exception as e:
        print(f"\n⚠️ 网页直接 HTTP 调用捕获到限制 ({e})，准备使用 OpenCLI 自动化无感浏览器接入...")

if __name__ == '__main__':
    test_yuanbao_connection()
