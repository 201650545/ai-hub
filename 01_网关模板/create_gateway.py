# -*- coding: utf-8 -*-
"""
网关生成器 (Gateway Generator)
============================================================
按模板在 02_网关实例/ 下创建新的 AI Gateway 节点，并自动注册到中央平台。

用法:
    python create_gateway.py <gateway_name> [--port 3001] [--desc "描述信息"]
"""

import argparse
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = BASE_DIR.parent
TEMPLATE_DIR = BASE_DIR / "template"
INSTANCES_DIR = PROJECT_DIR / "02_网关实例"

CENTRAL_PLATFORM_URL = "http://localhost:8000/api/gateways"


def create_gateway(name, port, description=""):
    """创建新网关实例并注册。"""
    target_dir = INSTANCES_DIR / name
    if target_dir.exists():
        print(f"❌ 错误: 网关目录 {target_dir} 已存在！")
        return False

    print(f"🚀 开始创建网关实例: {name} (端口: {port})...")

    # 1. 复制模板文件
    if not TEMPLATE_DIR.exists():
        print(f"❌ 错误: 模板目录 {TEMPLATE_DIR} 不存在！")
        return False

    target_dir.mkdir(parents=True, exist_ok=True)
    for item in TEMPLATE_DIR.iterdir():
        if item.is_file():
            shutil.copy2(item, target_dir / item.name)

    # 2. 替换 unified_gateway.py 模板占位符
    gw_file = target_dir / "unified_gateway.py"
    if gw_file.exists():
        content = gw_file.read_text(encoding="utf-8")
        content = content.replace("{{PORT}}", str(port))
        content = content.replace("{{GATEWAY_NAME}}", name)
        content = content.replace("{{DESCRIPTION}}", description)
        gw_file.write_text(content, encoding="utf-8")

    # 3. 生成 config.json
    config_data = {
        "id": name,
        "name": name,
        "port": port,
        "description": description,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")
    }
    with open(target_dir / "config.json", "w", encoding="utf-8") as f:
        json.dump(config_data, f, ensure_ascii=False, indent=2)

    print(f"✅ 实例文件成功写入: {target_dir}")

    # 4. 调用中央平台 API 注册网关
    print("📡 正在注册到中央平台 (:8000)...")
    try:
        req_data = json.dumps({
            "id": name,
            "name": name,
            "port": port,
            "description": description,
            "url": f"http://localhost:{port}"
        }).encode("utf-8")

        req = urllib.request.Request(
            CENTRAL_PLATFORM_URL,
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=5) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            print(f"🎉 注册成功! 中央平台节点 ID: {res_json.get('id')}")
    except Exception as e:
        print(f"⚠️ 中央平台未就绪或无法连接 ({e})，网关将在启动时重新注册。")

    print("\n" + "=" * 60)
    print(f"✨ 网关 [{name}] 创建完成！")
    print(f"👉 启动命令:")
    print(f"   cd 02_网关实例\\{name}")
    print(f"   python unified_gateway.py")
    print("=" * 60)
    return True


def main():
    parser = argparse.ArgumentParser(description="AI Hub 网关模板生成器")
    parser.add_argument("name", help="网关名称 (如 my_search_hub)")
    parser.add_argument("--port", type=int, default=3001, help="网关服务端口号 (默认: 3001)")
    parser.add_argument("--desc", default="", help="网关节点描述信息")

    args = parser.parse_args()
    create_gateway(args.name, args.port, args.desc)


if __name__ == "__main__":
    main()
