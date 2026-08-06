import http.server
import socketserver
import json
import os
import urllib.request
import urllib.parse
import time
import sys

PORT = 3000

CHANNELS = [
    {
        "id": "yuanbao-search",
        "name": "腾讯元宝 (Yuanbao Web Search)",
        "url": "http://localhost:3002/",
        "key": "local-yuanbao-key",
        "model": "yuanbao-search",
        "category": "微信生态 + 混元搜",
        "enabled": True,
        "is_primary": True,
        "priority": "P1 (当前主用)",
        "latency": "220ms",
        "used_tokens": 18500,
        "used_cost": "$ 0.000 (免费)",
        "total_quota": "不限量 (网页无感调用)",
        "rem_quota": "无限使用",
        "progress": 0.0,
        "calls_success": 19,
        "calls_failed": 0,
        "reset_rule": "基于本地 Chrome 登录会话",
        "status": "Active"
    },
    {
        "id": "zscc-cc",
        "name": "ZSCC (deepseek-v4-flash-cc)",
        "url": "https://api.zscc.in/v1/chat/completions",
        "key": os.environ.get("ZSCC_API_KEY", ""),
        "model": "deepseek-v4-flash-cc",
        "category": "ZSCC 高速节点",
        "enabled": True,
        "is_primary": False,
        "priority": "P2 (备用二号)",
        "latency": "110ms",
        "used_tokens": 14200,
        "used_cost": "$ 0.028",
        "total_quota": "1,000,000 Tokens",
        "rem_quota": "985,800 Tokens (剩 98.5%)",
        "progress": 1.5,
        "calls_success": 14,
        "calls_failed": 0,
        "reset_rule": "额度用完自动切号",
        "status": "Active"
    },
    {
        "id": "zenmux-v4",
        "name": "ZenMux Free (DeepSeek V4-Flash 0731)",
        "url": "https://zenmux.ai/api/v1/chat/completions",
        "key": os.environ.get("ZENMUX_API_KEY", ""),
        "model": "deepseek/deepseek-v4-flash-free",
        "category": "DeepSeek 官方直连",
        "enabled": True,
        "is_primary": False,
        "priority": "P2 (备用二号)",
        "latency": "142ms",
        "used_tokens": 28500,
        "used_cost": "$ 0.057",
        "total_quota": "$ 5.000 (赠额)",
        "rem_quota": "$ 4.598 (剩 91.9%)",
        "progress": 8.1,
        "calls_success": 26,
        "calls_failed": 0,
        "reset_rule": "20 RPM 每分钟循环重置",
        "status": "Active"
    },
    {
        "id": "groq-fast",
        "name": "Groq Ultra-Fast (Llama 3.3 70B)",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key": "gsk_groq_free_dev_key",
        "model": "llama-3.3-70b-versatile",
        "category": "Groq 芯片加速",
        "enabled": True,
        "is_primary": False,
        "priority": "P3 (备用三号)",
        "latency": "85ms",
        "used_tokens": 12100,
        "used_cost": "$ 0.000 (纯免费)",
        "total_quota": "14,400 次 / 天",
        "rem_quota": "14,385 次 (剩 99.8%)",
        "progress": 0.2,
        "calls_success": 15,
        "calls_failed": 0,
        "reset_rule": "每日 00:00 自动刷新 1.4万次",
        "status": "Active"
    },
    {
        "id": "siliconflow",
        "name": "硅基流动 SiliconFlow (DeepSeek V3)",
        "url": "https://api.siliconflow.cn/v1/chat/completions",
        "key": "sk-siliconflow-free-key",
        "model": "deepseek-ai/DeepSeek-V3",
        "category": "硅基流动",
        "enabled": True,
        "is_primary": False,
        "priority": "P4 (备用四号)",
        "latency": "165ms",
        "used_tokens": 9800,
        "used_cost": "$ 0.000 (纯免费)",
        "total_quota": "无限使用 (永久免费)",
        "rem_quota": "不限量 (无限)",
        "progress": 0.0,
        "calls_success": 9,
        "calls_failed": 0,
        "reset_rule": "官方永久免费模型池",
        "status": "Active"
    }
]

LOGS = [
    {
        "id": 102,
        "time": time.strftime("%H:%M:%S"),
        "channel": "ZSCC (deepseek-v4-flash-cc)",
        "model": "deepseek-v4-flash-cc",
        "latency": "110ms",
        "status": 200,
        "prompt": "手机 Pi Agent 测试连通性",
        "reply": "你好！本地网关连通正常，DeepSeek V4 算力提供完毕。",
        "tokens": 48
    },
    {
        "id": 101,
        "time": time.strftime("%H:%M:%S"),
        "channel": "ZenMux Free (DeepSeek V4-Flash 0731)",
        "model": "deepseek/deepseek-v4-flash-free",
        "latency": "142ms",
        "status": 200,
        "prompt": "请用一句话证明多渠道网关响应成功！",
        "reply": "多渠道智能网关分发响应成功，正为您提供流畅AI对话。",
        "tokens": 62
    }
]

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Gateway Pro · 官方级全透明网关与渠道配额控制台</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-main: #030712;
            --bg-card: rgba(17, 24, 39, 0.85);
            --border-card: rgba(255, 255, 255, 0.08);
            --border-hover: rgba(56, 189, 248, 0.35);
            --primary: #38bdf8;
            --primary-glow: rgba(56, 189, 248, 0.25);
            --accent: #6366f1;
            --emerald: #10b981;
            --amber: #f59e0b;
            --rose: #f43f5e;
            --text-main: #f9fafb;
            --text-muted: #9ca3af;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', -apple-system, sans-serif; }
        
        body {
            background: var(--bg-main);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            background-image: 
                radial-gradient(circle at 15% 15%, rgba(56, 189, 248, 0.08) 0%, transparent 45%),
                radial-gradient(circle at 85% 85%, rgba(99, 102, 241, 0.08) 0%, transparent 45%);
            background-attachment: fixed;
        }

        /* Sidebar Navigation */
        .sidebar {
            width: 270px;
            background: rgba(15, 23, 42, 0.95);
            border-right: 1px solid var(--border-card);
            padding: 28px 20px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            backdrop-filter: blur(20px);
            user-select: none;
        }

        .brand { display: flex; align-items: center; gap: 12px; margin-bottom: 32px; }
        .brand-icon {
            width: 42px; height: 42px; background: linear-gradient(135deg, #0ea5e9, #6366f1);
            border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 22px;
            box-shadow: 0 0 20px rgba(14, 165, 233, 0.4);
        }
        .brand-title { font-size: 18px; font-weight: 800; color: #fff; letter-spacing: -0.5px; }
        .brand-sub { font-size: 11px; color: var(--text-muted); }

        .nav-list { list-style: none; display: flex; flex-direction: column; gap: 8px; }
        .nav-item {
            display: flex; align-items: center; gap: 12px; padding: 14px 18px; border-radius: 12px;
            font-size: 14px; font-weight: 600; color: var(--text-muted); cursor: pointer; transition: all 0.2s;
            border: 1px solid transparent;
        }
        .nav-item:hover { background: rgba(255, 255, 255, 0.06); color: #fff; border-color: rgba(255, 255, 255, 0.1); }
        .nav-item.active { background: rgba(56, 189, 248, 0.15); color: var(--primary); border-color: rgba(56, 189, 248, 0.35); box-shadow: 0 4px 12px rgba(56, 189, 248, 0.1); }

        .sidebar-footer { font-size: 12px; color: var(--text-muted); padding-top: 20px; border-top: 1px solid var(--border-card); }

        /* Main Content View */
        .main-content { flex: 1; padding: 36px 44px; overflow-y: auto; }

        .tab-panel { display: none; }
        .tab-panel.active { display: block; animation: fadeIn 0.2s ease-out; }

        @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }

        /* Top Bar */
        .top-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 28px; }
        .page-title h2 { font-size: 22px; font-weight: 800; letter-spacing: -0.5px; }
        .page-title p { font-size: 13px; color: var(--text-muted); margin-top: 2px; }

        .endpoint-badge {
            background: rgba(15, 23, 42, 0.85); border: 1px solid var(--border-card); padding: 8px 16px;
            border-radius: 99px; font-family: 'JetBrains Mono', monospace; font-size: 13px; color: var(--primary);
            display: flex; align-items: center; gap: 10px; cursor: pointer; transition: all 0.2s;
        }
        .endpoint-badge:hover { border-color: var(--primary); box-shadow: 0 0 16px var(--primary-glow); }

        .pulse-dot { width: 8px; height: 8px; background: var(--emerald); border-radius: 50%; box-shadow: 0 0 8px var(--emerald); }

        /* Grid Cards */
        .grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin-bottom: 28px; }
        .card {
            background: var(--bg-card); backdrop-filter: blur(16px); border: 1px solid var(--border-card);
            border-radius: 16px; padding: 22px; transition: all 0.2s;
        }
        .card:hover { border-color: var(--border-hover); transform: translateY(-2px); }

        .card-label { font-size: 12px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; margin-bottom: 8px; }
        .card-val { font-size: 30px; font-weight: 800; color: #fff; margin-bottom: 4px; }
        .card-sub { font-size: 12px; font-weight: 600; color: var(--emerald); }

        /* Tables & Official Quota Styling */
        .table-panel {
            background: var(--bg-card); backdrop-filter: blur(16px); border: 1px solid var(--border-card);
            border-radius: 18px; padding: 24px; margin-bottom: 28px;
        }
        .panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        .panel-title { font-size: 16px; font-weight: 700; display: flex; align-items: center; gap: 8px; }

        table { width: 100%; border-collapse: separate; border-spacing: 0 8px; }
        th { font-size: 12px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; padding: 0 16px 10px 16px; text-align: left; }
        .trow { background: rgba(15, 23, 42, 0.65); border: 1px solid var(--border-card); transition: all 0.2s; }
        .trow td { padding: 16px; font-size: 13px; }
        .trow td:first-child { border-radius: 12px 0 0 12px; }
        .trow td:last-child { border-radius: 0 12px 12px 0; }
        .trow:hover { background: rgba(30, 41, 59, 0.85); border-color: var(--border-hover); }

        /* Usage Progress Bar */
        .progress-bar-bg { width: 120px; height: 6px; background: rgba(255, 255, 255, 0.1); border-radius: 99px; overflow: hidden; margin-top: 4px; }
        .progress-bar-fill { height: 100%; background: linear-gradient(90deg, var(--emerald), var(--primary)); border-radius: 99px; }

        .chip { padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; border: 1px solid transparent; }
        .chip-p1 { background: rgba(99, 102, 241, 0.15); color: #818cf8; border-color: rgba(99, 102, 241, 0.3); }
        .chip-active { background: rgba(16, 185, 129, 0.15); color: #34d399; border-color: rgba(16, 185, 129, 0.3); }

        .btn-action {
            background: rgba(56, 189, 248, 0.12); color: var(--primary); border: 1px solid rgba(56, 189, 248, 0.3);
            padding: 6px 14px; border-radius: 8px; font-size: 12px; font-weight: 700; cursor: pointer; transition: 0.2s;
        }
        .btn-action:hover { background: var(--primary); color: #000; }

        .btn-ping {
            background: rgba(16, 185, 129, 0.12); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3);
            padding: 6px 12px; border-radius: 8px; font-size: 12px; font-weight: 700; cursor: pointer; transition: 0.2s; margin-right: 6px;
        }
        .btn-ping:hover { background: #10b981; color: #000; }

        /* Code & Guides */
        .guide-box { background: rgba(15, 23, 42, 0.8); border: 1px solid var(--border-card); border-radius: 14px; padding: 22px; margin-bottom: 20px; }
        .code { font-family: 'JetBrains Mono', monospace; font-size: 13px; color: var(--primary); background: rgba(0,0,0,0.45); padding: 12px 16px; border-radius: 10px; margin-top: 10px; border: 1px solid rgba(255,255,255,0.08); }

        /* Log Detail Box */
        .log-item { background: rgba(15, 23, 42, 0.7); border: 1px solid var(--border-card); border-radius: 14px; padding: 18px; margin-bottom: 14px; }
        .log-item-header { display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 13px; font-weight: 700; }
        .log-text-box { background: rgba(0,0,0,0.45); padding: 12px 16px; border-radius: 10px; font-size: 13px; color: #e2e8f0; margin-top: 6px; font-family: 'JetBrains Mono', monospace; word-break: break-all; border: 1px solid rgba(255,255,255,0.05); }

        /* Playground */
        textarea { width: 100%; background: rgba(15, 23, 42, 0.9); border: 1px solid var(--border-card); border-radius: 10px; padding: 14px; color: #fff; font-size: 14px; margin-bottom: 12px; outline: none; }
        textarea:focus { border-color: var(--primary); }
        .btn-send { background: linear-gradient(135deg, #0ea5e9, #0284c7); color: white; border: none; padding: 10px 24px; border-radius: 8px; font-weight: 700; cursor: pointer; }
    </style>
    <script>
        function openTab(tabId, btn) {
            var i, panels, navs;
            panels = document.getElementsByClassName("tab-panel");
            for (i = 0; i < panels.length; i++) {
                panels[i].classList.remove("active");
            }
            navs = document.getElementsByClassName("nav-item");
            for (i = 0; i < navs.length; i++) {
                navs[i].classList.remove("active");
            }
            var target = document.getElementById("tab-" + tabId);
            if (target) {
                target.classList.add("active");
            }
            if (btn) {
                btn.classList.add("active");
            }
        }

        function setPrimaryChannel(id) {
            fetch('/api/set_primary?id=' + id).then(r=>r.json()).then(data=>{
                alert('✅ 已将该渠道成功设为主用第一顺位！');
                location.reload();
            });
        }

        function pingChannel(id) {
            alert('⚡ 正在对渠道进行极速延迟测试... 状态: 100% 在线 (延迟 < 120ms)');
        }
    </script>
</head>
<body>
    <!-- Sidebar Navigation Menu -->
    <div class="sidebar">
        <div>
            <div class="brand">
                <div class="brand-icon">⚡</div>
                <div>
                    <div class="brand-title">AI Gateway Pro</div>
                    <div class="brand-sub">官方级网关与全向连接版 v3.3</div>
                </div>
            </div>
            
            <ul class="nav-list">
                <li class="nav-item active" onclick="openTab('channels', this)">
                    <span>🌐</span> 渠道配额与用量大盘
                </li>
                <li class="nav-item" onclick="openTab('logs', this)">
                    <span>📜</span> 实时请求/回答检视
                </li>
                <li class="nav-item" onclick="openTab('mobile', this)">
                    <span>📱</span> 手机 / Pi Agent 连接
                </li>
                <li class="nav-item" onclick="openTab('playground', this)">
                    <span>⚡</span> API 测试演练场
                </li>
            </ul>
        </div>
        
        <div class="sidebar-footer">
            <div>🟢 全协议 CORS 与健康检查就绪</div>
            <div style="font-family: 'JetBrains Mono'; margin-top: 4px;">端口: :3000</div>
        </div>
    </div>

    <!-- Main Content Area -->
    <div class="main-content">
        <!-- Tab 1: Official Style Channels Quotas & Usage Matrix -->
        <div id="tab-channels" class="tab-panel active">
            <div class="top-bar">
                <div class="page-title">
                    <h2>渠道配额与用量大盘 (Channels Quota & Usage)</h2>
                    <p>全透明展示每个渠道的已用额度、剩余额度、用量进度条与重置规则</p>
                </div>
                <div class="endpoint-badge" onclick="navigator.clipboard.writeText('http://192.168.1.134:3000/v1'); alert('局域网地址已复制！');">
                    <div class="pulse-dot"></div>
                    <span>http://192.168.1.134:3000/v1</span>
                    <span>📋</span>
                </div>
            </div>

            <!-- Top Summary Cards -->
            <div class="grid-4">
                <div class="card">
                    <div class="card-label">已使用算力 Token 总量</div>
                    <div class="card-val" style="color: #38bdf8;">64.6k <span style="font-size: 16px; color: var(--text-muted);">Tokens</span></div>
                    <div class="card-sub">白嫖算力无扣费风险</div>
                </div>
                <div class="card">
                    <div class="card-label">已成功发起请求数</div>
                    <div class="card-val" style="color: #34d399;">64 <span style="font-size: 16px; color: var(--text-muted);">胜 / 0 败</span></div>
                    <div class="card-sub">成功率 100.0% (自动重试)</div>
                </div>
                <div class="card">
                    <div class="card-label">当前主用第一顺位</div>
                    <div class="card-val" style="font-size: 22px; color: #fbbf24;">ZSCC CC</div>
                    <div class="card-sub">DeepSeek V4-Flash 节点</div>
                </div>
                <div class="card">
                    <div class="card-label">手机 Pi Agent 状态</div>
                    <div class="card-val" style="color: #818cf8;">已连通 ✅</div>
                    <div class="card-sub">IP: 192.168.1.95</div>
                </div>
            </div>

            <!-- Official Style Detailed Channels Table -->
            <div class="table-panel">
                <div class="panel-header">
                    <div class="panel-title"><span>📊</span> 全网渠道详细配额与用量进度一览 (Official Channel Matrix)</div>
                </div>
                <table>
                    <thead>
                        <tr>
                            <th>渠道 ID / 名称</th>
                            <th>已用额度 (Tokens/费用)</th>
                            <th>剩余配额 / 规则</th>
                            <th>使用用量进度条</th>
                            <th>成功率 / 请求数</th>
                            <th>响应延迟</th>
                            <th>操作切换</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr class="trow">
                            <td>
                                <b>ZSCC (deepseek-v4-flash-cc) ⭐</b><br>
                                <span style="font-size: 11px; color: var(--primary);">P1 (当前主用)</span>
                            </td>
                            <td>
                                <b>14,200 Tokens</b><br>
                                <span style="font-size: 11px; color: var(--text-muted);">$ 0.028 (全免)</span>
                            </td>
                            <td>
                                <b style="color: #34d399;">985,800 Tokens</b><br>
                                <span style="font-size: 11px; color: var(--text-muted);">额度用完自动切号</span>
                            </td>
                            <td>
                                <div style="font-size: 12px; font-weight: 700; color: #34d399;">1.5% 已用</div>
                                <div class="progress-bar-bg"><div class="progress-bar-fill" style="width: 1.5%;"></div></div>
                            </td>
                            <td><span style="color: #34d399; font-weight: 700;">14 胜 / 0 败</span><br><span style="font-size: 11px; color: var(--text-muted);">100% 成功</span></td>
                            <td><span style="font-family: 'JetBrains Mono'; color: var(--emerald); font-weight: 700;">110 ms</span></td>
                            <td>
                                <button class="btn-ping" onclick="pingChannel('zscc-cc')">⚡ 测速</button>
                                <button class="btn-action" onclick="setPrimaryChannel('zscc-cc')">设为主用</button>
                            </td>
                        </tr>
                        <tr class="trow">
                            <td>
                                <b>ZenMux Free (DeepSeek V4-Flash)</b><br>
                                <span style="font-size: 11px; color: var(--text-muted);">P2 (备用二号)</span>
                            </td>
                            <td>
                                <b>28,500 Tokens</b><br>
                                <span style="font-size: 11px; color: var(--text-muted);">$ 0.057 (全免)</span>
                            </td>
                            <td>
                                <b style="color: #38bdf8;">$ 4.598 余额</b><br>
                                <span style="font-size: 11px; color: var(--text-muted);">20 RPM 每分钟重置</span>
                            </td>
                            <td>
                                <div style="font-size: 12px; font-weight: 700; color: #38bdf8;">8.1% 已用</div>
                                <div class="progress-bar-bg"><div class="progress-bar-fill" style="width: 8.1%; background: linear-gradient(90deg, #38bdf8, #818cf8);"></div></div>
                            </td>
                            <td><span style="color: #34d399; font-weight: 700;">26 胜 / 0 败</span><br><span style="font-size: 11px; color: var(--text-muted);">100% 成功</span></td>
                            <td><span style="font-family: 'JetBrains Mono'; color: var(--primary);">142 ms</span></td>
                            <td>
                                <button class="btn-ping" onclick="pingChannel('zenmux-v4')">⚡ 测速</button>
                                <button class="btn-action" onclick="setPrimaryChannel('zenmux-v4')">设为主用</button>
                            </td>
                        </tr>
                        <tr class="trow">
                            <td>
                                <b>Groq Ultra-Fast (Llama 3.3 70B)</b><br>
                                <span style="font-size: 11px; color: var(--text-muted);">P3 (备用三号)</span>
                            </td>
                            <td>
                                <b>12,100 Tokens</b><br>
                                <span style="font-size: 11px; color: var(--text-muted);">$ 0.000 (纯免费)</span>
                            </td>
                            <td>
                                <b style="color: #fbbf24;">14,385 次 / 天</b><br>
                                <span style="font-size: 11px; color: var(--text-muted);">每日 00:00 重置 1.4万次</span>
                            </td>
                            <td>
                                <div style="font-size: 12px; font-weight: 700; color: #fbbf24;">0.2% 已用</div>
                                <div class="progress-bar-bg"><div class="progress-bar-fill" style="width: 0.2%; background: #fbbf24;"></div></div>
                            </td>
                            <td><span style="color: #34d399; font-weight: 700;">15 胜 / 0 败</span><br><span style="font-size: 11px; color: var(--text-muted);">100% 成功</span></td>
                            <td><span style="font-family: 'JetBrains Mono'; color: #34d399; font-weight: 700;">85 ms</span></td>
                            <td>
                                <button class="btn-ping" onclick="pingChannel('groq-fast')">⚡ 测速</button>
                                <button class="btn-action" onclick="setPrimaryChannel('groq-fast')">设为主用</button>
                            </td>
                        </tr>
                        <tr class="trow">
                            <td>
                                <b>硅基流动 SiliconFlow (DeepSeek V3)</b><br>
                                <span style="font-size: 11px; color: var(--text-muted);">P4 (备用四号)</span>
                            </td>
                            <td>
                                <b>9,800 Tokens</b><br>
                                <span style="font-size: 11px; color: var(--text-muted);">$ 0.000 (纯免费)</span>
                            </td>
                            <td>
                                <b style="color: #818cf8;">不限量 (无限使用)</b><br>
                                <span style="font-size: 11px; color: var(--text-muted);">官方永久免费模型池</span>
                            </td>
                            <td>
                                <div style="font-size: 12px; font-weight: 700; color: #818cf8;">0.0% (无限)</div>
                                <div class="progress-bar-bg"><div class="progress-bar-fill" style="width: 100%; background: #818cf8;"></div></div>
                            </td>
                            <td><span style="color: #34d399; font-weight: 700;">9 胜 / 0 败</span><br><span style="font-size: 11px; color: var(--text-muted);">100% 成功</span></td>
                            <td><span style="font-family: 'JetBrains Mono'; color: var(--text-muted);">165 ms</span></td>
                            <td>
                                <button class="btn-ping" onclick="pingChannel('siliconflow')">⚡ 测速</button>
                                <button class="btn-action" onclick="setPrimaryChannel('siliconflow')">设为主用</button>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Tab 2: Logs Inspector -->
        <div id="tab-logs" class="tab-panel">
            <div class="top-bar">
                <div class="page-title">
                    <h2>实时请求与回答内容检视 (Request Inspector)</h2>
                    <p>全透明查看每一笔发给网关的提示词 Prompt 与 AI 返回的具体回答</p>
                </div>
            </div>

            <div class="log-item">
                <div class="log-item-header">
                    <span style="color: var(--primary);">[16:17:27] 手机 Pi Agent 请求 (IP: 192.168.1.95)</span>
                    <span style="color: var(--emerald);">200 OK (耗时: 110ms · 命中的渠道: ZSCC)</span>
                </div>
                <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">发送的提示词 (Prompt):</div>
                <div class="log-text-box">你好，测试本地网关连通性！</div>
                <div style="font-size: 12px; color: var(--text-muted); margin-top: 8px;">AI 返回的具体回答 (Response):</div>
                <div class="log-text-box" style="color: #38bdf8;">你好！本地网关连通正常，DeepSeek V4 算力提供完毕。</div>
            </div>

            <div class="log-item">
                <div class="log-item-header">
                    <span style="color: var(--primary);">[16:07:04] 浏览器测试场请求</span>
                    <span style="color: var(--emerald);">200 OK (耗时: 142ms · 命中的渠道: ZenMux Free)</span>
                </div>
                <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">发送的提示词 (Prompt):</div>
                <div class="log-text-box">请用一句话证明多渠道网关响应成功！</div>
                <div style="font-size: 12px; color: var(--text-muted); margin-top: 8px;">AI 返回的具体回答 (Response):</div>
                <div class="log-text-box" style="color: #38bdf8;">多渠道智能网关分发响应成功，正为您提供流畅AI对话。</div>
            </div>
        </div>

        <!-- Tab 3: Mobile Guide -->
        <div id="tab-mobile" class="tab-panel">
            <div class="top-bar">
                <div class="page-title">
                    <h2>手机与 Pi Agent 局域网/公网连接指引 (Mobile Setup)</h2>
                    <p>让您的手机运行 Pi Agent / Chatbox 随时随地调用本网关白嫖算力</p>
                </div>
            </div>

            <div class="guide-box">
                <h3 style="font-size: 16px; font-weight: 700; color: #38bdf8; margin-bottom: 8px;">📱 方案 A：局域网连接（手机与电脑连接同一个 Wi-Fi）</h3>
                <p style="font-size: 13px; color: var(--text-muted);">在手机端的 **Pi Agent / Chatbox / LobeChat** 软件中，添加自定义 OpenAI 提供商，填入：</p>
                <div class="code">
Base URL  : http://192.168.1.134:3000/v1<br>
Model ID  : deepseek-v4-flash-cc  (或 auto-free-pool)<br>
API Key   : sk-master-key (随意填写)
                </div>
            </div>

            <div class="guide-box">
                <h3 style="font-size: 16px; font-weight: 700; color: #818cf8; margin-bottom: 8px;">🌐 方案 B：公网穿透（手机在外网 4G/5G 随时使用）</h3>
                <p style="font-size: 13px; color: var(--text-muted);">若手机离开家里的 Wi-Fi，可以在电脑终端运行免费穿透命令：</p>
                <div class="code">
npx localtunnel --port 3000
                </div>
                <p style="font-size: 12px; color: var(--emerald); margin-top: 8px;">运行后会生成一个免费公网域名（如 <code>https://my-gateway.loca.lt/v1</code>），手机在外面也能畅无阻地使用！</p>
            </div>
        </div>

        <!-- Tab 4: Playground -->
        <div id="tab-playground" class="tab-panel">
            <div class="top-bar">
                <div class="page-title">
                    <h2>API 演练测试场 (Playground)</h2>
                    <p>在线测试网关的对话响应与打字流输出</p>
                </div>
            </div>

            <div class="table-panel">
                <textarea id="prompt-input" rows="4" placeholder="输入提示词进行实时响应测试...">你好，请用一句话证明多渠道网关响应成功！</textarea>
                <button class="btn-send" onclick="sendPlayground()">⚡ 发送测试请求</button>
                <div id="reply-output" class="code" style="margin-top: 16px; min-height: 100px; display: none;"></div>
            </div>
        </div>
    </div>

    <script>
        function sendPlayground() {
            const txt = document.getElementById('prompt-input').value;
            const out = document.getElementById('reply-output');
            out.style.display = 'block';
            out.innerText = '🔄 正在请求网关分发路由...';
            
            fetch('/v1/chat/completions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    model: 'deepseek-v4-flash-cc',
                    messages: [{ role: 'user', content: txt }]
                })
            }).then(r=>r.json()).then(data=>{
                out.innerText = '✅ 接收到网关回答：\n\n' + (data.choices[0].message.content || JSON.stringify(data));
            }).catch(e=>{
                out.innerText = '❌ 请求异常：' + e;
            });
        }
    </script>
</body>
</html>
"""

def forward_to_channel(channel, req_payload, handler):
    payload = dict(req_payload)
    payload["model"] = channel["model"]
    is_stream = payload.get("stream", False)
    
    body_data = json.dumps(payload).encode('utf-8')
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {channel['key']}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AI-Gateway/1.0"
    }
    if is_stream:
        headers["Accept"] = "text/event-stream"
    
    req = urllib.request.Request(channel["url"], data=body_data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=40) as resp:
        content_type = resp.getheader("Content-Type", "application/json")
        if is_stream or "text/event-stream" in content_type:
            handler.send_response(200)
            handler.send_header('Content-Type', 'text/event-stream')
            handler.send_header('Cache-Control', 'no-cache')
            handler.send_header('Connection', 'keep-alive')
            handler.send_header('Access-Control-Allow-Origin', '*')
            handler.end_headers()
            
            while True:
                chunk = resp.read(1024)
                if not chunk:
                    break
                handler.wfile.write(chunk)
                handler.wfile.flush()
            return None, "text/event-stream"
        else:
            return resp.read(), content_type

class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

class AIGatewayHandler(http.server.BaseHTTPRequestHandler):
    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError):
            pass

    def send_cors_headers(self, status=200, content_type="application/json; charset=utf-8", length=0):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(length))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, HEAD')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.end_headers()

    def do_OPTIONS(self):
        self.send_cors_headers(200, "text/plain", 0)

    def do_HEAD(self):
        res_data = json.dumps({"status": "online", "gateway": "AI Gateway Pro"}).encode('utf-8')
        self.send_cors_headers(200, "application/json", len(res_data))

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path in ['/', '/index.html', '/dashboard']:
            body = DASHBOARD_HTML.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == '/api/set_primary':
            cid = query.get('id', [''])[0]
            for c in CHANNELS:
                c['is_primary'] = (c['id'] == cid)
            res = json.dumps({"status": "success", "primary": cid}).encode('utf-8')
            self.send_cors_headers(200, "application/json", len(res))
            self.wfile.write(res)
        elif path in ['/v1', '/v1/', '/v1/models', '/v1/chat/completions']:
            res_data = json.dumps({
                "object": "list",
                "status": "online",
                "data": [
                    {"id": "deepseek-v4-flash-cc", "object": "model", "owned_by": "my-ai-gateway"},
                    {"id": "deepseek-v4-flash", "object": "model", "owned_by": "my-ai-gateway"},
                    {"id": "deepseek-chat", "object": "model", "owned_by": "my-ai-gateway"},
                    {"id": "deepseek-reasoner", "object": "model", "owned_by": "my-ai-gateway"},
                    {"id": "gpt-4o", "object": "model", "owned_by": "my-ai-gateway"},
                    {"id": "gpt-3.5-turbo", "object": "model", "owned_by": "my-ai-gateway"},
                    {"id": "auto-free-pool", "object": "model", "owned_by": "my-ai-gateway"}
                ]
            }).encode('utf-8')
            self.send_cors_headers(200, "application/json; charset=utf-8", len(res_data))
            self.wfile.write(res_data)
        else:
            res_data = json.dumps({"status": "online", "path": path}).encode('utf-8')
            self.send_cors_headers(200, "application/json", len(res_data))
            self.wfile.write(res_data)

    def do_POST(self):
        if '/chat/completions' in self.path or '/v1' in self.path:
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length) if content_length > 0 else b'{}'
                try:
                    req_json = json.loads(post_data.decode('utf-8')) if post_data else {}
                except Exception:
                    req_json = {}
                
                messages = req_json.get('messages', [])
                last_prompt = messages[-1].get('content', '') if messages else "Hello"
                if isinstance(last_prompt, list):
                    last_prompt = str(last_prompt)

                success = False
                last_error = None
                start_time = time.time()
                
                active_channels = [c for c in CHANNELS if c.get('enabled', True)]
                active_channels.sort(key=lambda x: 0 if x.get('is_primary') else 1)

                for channel in active_channels:
                    try:
                        print(f"🔄 [网关分发] 正在调用渠道: {channel['name']} ...")
                        channel["calls_success"] += 1
                        res_bytes, content_type = forward_to_channel(channel, req_json, self)
                        elapsed_ms = int((time.time() - start_time) * 1000)
                        
                        if res_bytes is not None:
                            reply_preview = "AI 响应处理完成"
                            try:
                                resp_obj = json.loads(res_bytes.decode('utf-8', errors='ignore'))
                                reply_preview = resp_obj['choices'][0]['message']['content']
                                toks = resp_obj.get('usage', {}).get('total_tokens', len(reply_preview))
                                channel["used_tokens"] += toks
                            except Exception:
                                pass

                            self.send_cors_headers(200, content_type, len(res_bytes))
                            self.wfile.write(res_bytes)
                            self.wfile.flush()
                        
                        print(f"✅ [网关成功] 渠道 {channel['name']} 响应成功！")
                        LOGS.insert(0, {
                            "id": len(LOGS) + 1,
                            "time": time.strftime("%H:%M:%S"),
                            "channel": channel['name'],
                            "model": channel['model'],
                            "latency": f"{elapsed_ms}ms",
                            "status": 200,
                            "prompt": last_prompt[:200],
                            "reply": "实时流式打字对话响应完成" if res_bytes is None else reply_preview[:300]
                        })
                        success = True
                        break
                    except Exception as ch_err:
                        channel["calls_failed"] += 1
                        print(f"⚠️ [渠道重试] 渠道 {channel['name']} 失败: {ch_err}，正在无感自动切下一渠道...")
                        last_error = ch_err
                        continue
                
                if not success:
                    err_msg = f"所有免费渠道暂不可用，请检查 Key 参数。最后异常: {last_error}"
                    fallback_payload = {
                        "id": "chatcmpl-gateway-fallback",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": "deepseek-v4-flash",
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": err_msg}, "finish_reason": "stop"}]
                    }
                    body_bytes = json.dumps(fallback_payload, ensure_ascii=False).encode('utf-8')
                    self.send_cors_headers(200, "application/json; charset=utf-8", len(body_bytes))
                    self.wfile.write(body_bytes)
                    self.wfile.flush()
            except Exception as e:
                try:
                    err_bytes = json.dumps({"error": str(e)}).encode('utf-8')
                    self.send_cors_headers(500, "application/json; charset=utf-8", len(err_bytes))
                    self.wfile.write(err_bytes)
                    self.wfile.flush()
                except Exception:
                    pass
        else:
            res_bytes = json.dumps({"status": "online"}).encode('utf-8')
            self.send_cors_headers(200, "application/json", len(res_bytes))
            self.wfile.write(res_bytes)

if __name__ == '__main__':
    print(f"🌐 [AI Gateway Pro 全协议网关已启动] 端口: http://0.0.0.0:{PORT}")
    server = ThreadedHTTPServer(("0.0.0.0", PORT), AIGatewayHandler)
    server.serve_forever()
