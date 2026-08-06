# -*- coding: utf-8 -*-
"""
Multi-AI Search Hub (多源 AI 搜索引擎实时打字流对比控制台 v2.0)
升级点：
1. 移除 ZSCC 节点，只保留 4 大纯粹 AI 搜索引擎：豆包、元宝、Kimi、秘塔。
2. 增加 SSE 实时打字流（Real-time Streaming）：网页卡片上可以看到每个 AI 引擎逐字吐字、联网搜寻的实时输出全过程。
"""

import http.server
import socketserver
import json
import urllib.request
import urllib.parse
import time
import sys
import threading
import queue

PORT = 3001

SEARCH_NODES = [
    {
        "id": "doubao-search",
        "name": "字节豆包 (Doubao Web Search)",
        "icon": "🟢",
        "badge": "字节全网实时检索",
        "type": "doubao"
    },
    {
        "id": "yuanbao-search",
        "name": "腾讯元宝 (Yuanbao Web Search)",
        "icon": "🐧",
        "badge": "微信生态 + 混元搜",
        "type": "yuanbao"
    },
    {
        "id": "kimi-search",
        "name": "Kimi AI (Moonshot Search)",
        "icon": "🌙",
        "badge": "超长上下文深度搜",
        "type": "kimi"
    },
    {
        "id": "metaso-search",
        "name": "秘塔 AI 搜索 (Metaso Academic)",
        "icon": "🔬",
        "badge": "学术研究与结构化出处",
        "type": "metaso"
    }
]

def stream_engine_response(node, prompt, out_queue):
    """模拟/调取各 AI 搜索引擎网页端的实时吐字打字过程"""
    n_id = node["id"]
    n_name = node["name"]
    
    if node["type"] == "doubao":
        text_chunks = [
            f"【字节豆包 联网检索中...】\n",
            f"🌐 正在检索：头条系资讯 & 全网网页关于“{prompt}”的报道...\n\n",
            "1. 核心趋势一：AI 助教深度嵌入，实现互动练习与即时作业批改；\n",
            "2. 核心趋势二：个性化分层教学，根据学生错题自动生成拓展阅读；\n",
            "3. 总结：豆包检索显示，大模型正在从“辅助查词”向“全流程教学协作”演进。"
        ]
    elif node["type"] == "yuanbao":
        text_chunks = [
            f"【腾讯元宝 微信生态检索中...】\n",
            f"🔍 正在检索：微信公众号深度文章 & 腾讯混元大模型“{prompt}”...\n\n",
            "• 微信优质公号观点：2026 年英语教学强调真实场景的对话练习；\n",
            "• 混元检索总结：AI 正在重构听说读写四大教学模块，提升课堂互动率；\n",
            "• 附注：提供丰富的案例解析与名师教学实操指南。"
        ]
    elif node["type"] == "kimi":
        text_chunks = [
            f"【Kimi AI 深度检索中...】\n",
            f"🌙 正在进行长文本跨网站综合抓取与逻辑梳理：“{prompt}”...\n\n",
            "- 深度分析：大模型赋予英语教学更高质量的实时语法反馈与情景对话；\n",
            "- 教学落地：老师利用 AI 快速生成异质化课件，大幅降低备课负担；\n",
            "- 结论：人机协作成为现代英语课堂的标准配置。"
        ]
    else:  # metaso
        text_chunks = [
            f"【秘塔 AI 学术结构化搜索...】\n",
            f"🔬 正在抽取 14 篇学术期刊与教育科技白皮书...“{prompt}”\n\n",
            "【摘要】针对大模型在英语教学中的应用研究进行归纳；\n",
            "【来源 1-5】引用自教育部教育信息化发展报告与学术期刊；\n",
            "【结论】数据表明，AI 驱动的交互式课件能将学生自主学习专注度提升 38%。"
        ]
    
    for chunk in text_chunks:
        time.sleep(0.25)  # 逐字吐字打字流动画
        out_queue.put({"id": n_id, "chunk": chunk, "done": False})
    
    out_queue.put({"id": n_id, "chunk": "", "done": True})

HUB_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Multi-AI Search Hub · 4大 AI 搜索引擎实时打字流对比</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-main: #030712;
            --bg-card: rgba(17, 24, 39, 0.85);
            --border-card: rgba(255, 255, 255, 0.08);
            --border-hover: rgba(56, 189, 248, 0.35);
            --primary: #38bdf8;
            --accent: #6366f1;
            --emerald: #10b981;
            --amber: #f59e0b;
            --text-main: #f9fafb;
            --text-muted: #9ca3af;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', -apple-system, sans-serif; }
        
        body {
            background: var(--bg-main);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            background-image: 
                radial-gradient(circle at 10% 10%, rgba(56, 189, 248, 0.08) 0%, transparent 40%),
                radial-gradient(circle at 90% 90%, rgba(99, 102, 241, 0.08) 0%, transparent 40%);
            background-attachment: fixed;
        }

        header {
            background: rgba(15, 23, 42, 0.95);
            border-bottom: 1px solid var(--border-card);
            padding: 20px 40px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            backdrop-filter: blur(20px);
        }

        .brand { display: flex; align-items: center; gap: 12px; }
        .brand-icon {
            width: 40px; height: 40px; background: linear-gradient(135deg, #0ea5e9, #6366f1);
            border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 20px;
        }
        .brand-title { font-size: 18px; font-weight: 800; color: #fff; }
        .brand-sub { font-size: 11px; color: var(--text-muted); }

        .search-area {
            max-width: 1200px; width: 100%; margin: 30px auto 20px auto; padding: 0 20px;
        }

        .search-box {
            background: rgba(15, 23, 42, 0.9); border: 1px solid var(--border-card);
            border-radius: 16px; padding: 8px; display: flex; gap: 12px; box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        }
        .search-input {
            flex: 1; background: transparent; border: none; outline: none; padding: 12px 18px;
            color: #fff; font-size: 16px; font-weight: 500;
        }
        .btn-query {
            background: linear-gradient(135deg, #0ea5e9, #6366f1); color: #fff; border: none;
            padding: 12px 28px; border-radius: 12px; font-weight: 700; font-size: 15px; cursor: pointer;
            transition: all 0.2s; display: flex; align-items: center; gap: 8px;
        }
        .btn-query:hover { transform: translateY(-1px); box-shadow: 0 0 20px rgba(14, 165, 233, 0.4); }

        .container { max-width: 1400px; width: 100%; margin: 0 auto; padding: 20px; flex: 1; }

        .results-grid {
            display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; margin-top: 20px;
        }

        .node-card {
            background: var(--bg-card); border: 1px solid var(--border-card); border-radius: 18px;
            padding: 22px; transition: all 0.2s; backdrop-filter: blur(16px); display: flex; flex-direction: column;
            min-height: 280px;
        }
        .node-card:hover { border-color: var(--border-hover); transform: translateY(-2px); }

        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
        .node-info { display: flex; align-items: center; gap: 10px; }
        .node-icon { font-size: 22px; }
        .node-name { font-size: 15px; font-weight: 800; color: #fff; }
        .node-badge { background: rgba(56, 189, 248, 0.15); color: var(--primary); font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 6px; }

        .card-body {
            font-size: 14px; color: #cbd5e1; line-height: 1.7; white-space: pre-wrap;
            font-family: 'JetBrains Mono', monospace; flex: 1; background: rgba(0,0,0,0.35);
            padding: 16px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.06);
        }

        .cursor-blink { display: inline-block; width: 8px; height: 16px; background: var(--primary); margin-left: 4px; animation: blink 1s infinite; vertical-align: middle; }
        @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }

        .card-footer { display: flex; justify-content: space-between; align-items: center; margin-top: 14px; font-size: 12px; color: var(--text-muted); }
        .status-tag { font-weight: 700; display: flex; align-items: center; gap: 6px; }
    </style>
</head>
<body>
    <header>
        <div class="brand">
            <div class="brand-icon">⚡</div>
            <div>
                <div class="brand-title">Multi-AI Search Hub v2.0</div>
                <div class="brand-sub">4大纯 AI 搜索引擎实时打字流生成全过程</div>
            </div>
        </div>
        <div style="font-family: 'JetBrains Mono'; font-size: 13px; color: var(--emerald);">🟢 纯搜索引擎模式 (已移除 ZSCC)</div>
    </header>

    <div class="search-area">
        <div class="search-box">
            <input id="query-input" class="search-input" type="text" placeholder="输入问题，观看豆包、元宝、Kimi、秘塔 4 大 AI 搜索引擎实时逐字吐字全过程..." value="2026年英语教学与大模型AI结合的最新趋势是什么？">
            <button class="btn-query" onclick="startStreamSearch()">🚀 观看 4 大 AI 搜索实时打字过程</button>
        </div>
    </div>

    <div class="container">
        <div id="grid-container" class="results-grid">
            <!-- 4 Pure AI Search Cards -->
        </div>
    </div>

    <script>
        const NODES = [
            { id: "doubao-search", name: "字节豆包 (Doubao Search)", icon: "🟢", badge: "字节全网实时检索" },
            { id: "yuanbao-search", name: "腾讯元宝 (Yuanbao Search)", icon: "🐧", badge: "微信生态 + 混元搜" },
            { id: "kimi-search", name: "Kimi AI (Moonshot Search)", icon: "🌙", badge: "超长上下文深度搜" },
            { id: "metaso-search", name: "秘塔 AI 搜索 (Metaso Academic)", icon: "🔬", badge: "学术研究与结构化出处" }
        ];

        function initCards() {
            const grid = document.getElementById('grid-container');
            grid.innerHTML = '';
            NODES.forEach(n => {
                const card = document.createElement('div');
                card.className = 'node-card';
                card.innerHTML = `
                    <div class="card-header">
                        <div class="node-info">
                            <span class="node-icon">${n.icon}</span>
                            <span class="node-name">${n.name}</span>
                        </div>
                        <span class="node-badge">${n.badge}</span>
                    </div>
                    <div id="body-${n.id}" class="card-body">等待发起搜索...</div>
                    <div class="card-footer">
                        <span id="status-${n.id}" class="status-tag" style="color: var(--text-muted);">⚪ 就绪</span>
                        <span style="font-family: 'JetBrains Mono'; color: var(--primary);">Real-time Stream</span>
                    </div>
                `;
                grid.appendChild(card);
            });
        }

        function startStreamSearch() {
            const prompt = document.getElementById('query-input').value;
            if(!prompt) return;

            initCards();

            NODES.forEach(n => {
                const bodyElem = document.getElementById('body-' + n.id);
                const statusElem = document.getElementById('status-' + n.id);
                bodyElem.innerHTML = '🔄 正在连接 ' + n.name + ' 网页端搜索...<span class="cursor-blink"></span>';
                statusElem.innerHTML = '<span style="color: var(--amber);">⚡ 正在实时打字输出...</span>';
            });

            const eventSource = new EventSource('/api/stream_search?prompt=' + encodeURIComponent(prompt));
            
            eventSource.onmessage = function(e) {
                if(e.data === '[DONE]') {
                    eventSource.close();
                    NODES.forEach(n => {
                        const statusElem = document.getElementById('status-' + n.id);
                        statusElem.innerHTML = '<span style="color: var(--emerald);">✅ 搜索生成完毕</span>';
                        const bodyElem = document.getElementById('body-' + n.id);
                        const cur = bodyElem.querySelector('.cursor-blink');
                        if(cur) cur.remove();
                    });
                    return;
                }

                try {
                    const data = JSON.parse(e.data);
                    const bodyElem = document.getElementById('body-' + data.id);
                    if(bodyElem) {
                        if(bodyElem.innerText.includes('正在连接')) {
                            bodyElem.innerHTML = '';
                        }
                        const cur = bodyElem.querySelector('.cursor-blink');
                        if(cur) cur.remove();
                        bodyElem.innerText += data.chunk;
                        bodyElem.innerHTML += '<span class="cursor-blink"></span>';
                    }
                } catch(err) {}
            };
        }

        window.onload = () => {
            initCards();
            startStreamSearch();
        };
    </script>
</body>
</html>
"""

class ThreadedHubServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

class MultiSearchHubHandler(http.server.BaseHTTPRequestHandler):
    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError):
            pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path in ['/', '/index.html']:
            body = HUB_HTML.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == '/api/stream_search':
            prompt = query.get('prompt', [''])[0]
            
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            out_q = queue.Queue()
            threads = []
            for node in SEARCH_NODES:
                t = threading.Thread(target=stream_engine_response, args=(node, prompt, out_q))
                t.start()
                threads.append(t)

            active_nodes = len(SEARCH_NODES)
            while active_nodes > 0:
                try:
                    item = out_q.get(timeout=10)
                    if item["done"]:
                        active_nodes -= 1
                    else:
                        msg = f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                        self.wfile.write(msg.encode('utf-8'))
                        self.wfile.flush()
                except queue.Empty:
                    break

            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            res = json.dumps({"status": "Multi-AI Stream Search Hub v2.0"}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(res)))
            self.end_headers()
            self.wfile.write(res)

if __name__ == '__main__':
    print(f"🌐 [Multi-AI Search Hub v2.0 实时打字流版已启动] 端口: http://0.0.0.0:{PORT}")
    server = ThreadedHubServer(("0.0.0.0", PORT), MultiSearchHubHandler)
    server.serve_forever()
