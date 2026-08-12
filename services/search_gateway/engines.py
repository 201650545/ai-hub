# -*- coding: utf-8 -*-
"""
引擎适配层 (engine adapters) —— 通过本地 opencli 浏览器会话无感操控已登录的 AI 搜索引擎网页端。
Engine adapter layer: controls logged-in AI search engine web sessions via opencli.

Design:
- One engine = one subprocess controlled by `opencli browser <session>`.
- Use subprocess.list2cmdline + shell=True; JS injection uses single quotes only.
- Unbound sessions return connected=False; no fake response generated.
"""

import json
import re
import subprocess
import threading
import time

OPENCLI = "opencli"
_NODE = "D:/Program Files/nodejs/node.exe"
_OPENCLI_SCRIPT = "C:/Users/郭永涛/AppData/Roaming/npm/node_modules/@jackwener/opencli/dist/src/main.js"

EXTRACT_POLL_INTERVAL = 2.0
EXTRACT_POLL_MAX = 45
SUBMIT_SETTLE_DELAY = 1.2

# ---------------------------------------------------------------- Extract JS

YUANBAO_EXTRACT_JS = """(function(){
  function textOf(e){ return e ? (e.innerText||'').trim() : ''; }
  function htmlOf(e){ return e ? (e.innerHTML||'').trim() : ''; }
  var cc = document.getElementById('chat-content') || document.body;
  var cotEls = Array.from(cc.querySelectorAll('.hyc-component-deepsearch-cot__think__content, [class*=deepsearch-cot__think]'));
  var thinking = '';
  for (var i=0; i<cotEls.length; i++){
    var ct = textOf(cotEls[i]);
    if (ct.length > 5 && thinking.indexOf(ct.slice(0,30)) === -1)
      thinking += (thinking ? '\\n' : '') + ct;
  }
  var els = Array.from(cc.querySelectorAll('.hyc-common-markdown-style'));
  var answersText = []; var answersHTML = [];
  for (var i=0; i<els.length; i++){
    var cls = String(els[i].className);
    if (cls.indexOf('-cot') > -1) continue;
    var t = textOf(els[i]); var h = htmlOf(els[i]);
    if (t.length > 15 && answersText.indexOf(t) === -1) {
      answersText.push(t); answersHTML.push(h);
    }
  }
  if (!answersText.length) {
    var bubbles = Array.from(cc.querySelectorAll('.agent-chat__bubble--ai .agent-chat__bubble__content'));
    if (bubbles.length) {
      var lb = bubbles[bubbles.length - 1];
      var t = textOf(lb); var h = htmlOf(lb);
      if (t.length > 15) { answersText.push(t); answersHTML.push(h); }
    }
  }
  var answer = answersText.length > 0 ? answersText[answersText.length - 1] : '';
  var answer_html = answersHTML.length > 0 ? answersHTML[answersHTML.length - 1] : '';
  if (!answer && !thinking) return JSON.stringify({found: false});
  var m = (cc.innerText||'').match(/Found\\s*(\\d+)\\s*references/i);
  return JSON.stringify({found:true,thinking:thinking,answer:answer,answer_html:answer_html,refs:m?parseInt(m[1],10):0});
})()"""

GENERIC_EXTRACT_JS = """(function(){
  function textOf(e){ return (e.innerText||'').trim(); }
  var candidates = Array.from(document.querySelectorAll('.markdown-body, [class*=markdown], [class*=response], [class*=answer], article'));
  var best = '';
  for (var i=0;i<candidates.length;i++){
    var t = textOf(candidates[i]);
    if (t.length > 40 && t.length > best.length) best = t;
  }
  return JSON.stringify({found: best.length > 0, answer: best, refs: 0});
})()"""

DOUBAO_EXTRACT_JS = """(function(){
  function textOf(e){ return (e.innerText||'').trim(); }
  var allMsgs = Array.from(document.querySelectorAll('[class*=message-content], [class*=bot-reply], [class*=answer-content], [class*=markdown]'));
  var best = '';
  var minLen = 10;
  for(var i=0; i<allMsgs.length; i++){
    var el = allMsgs[i];
    var parent = el.parentElement;
    var isUser = false;
    while(parent && parent !== document.body){
      if(parent.className && (String(parent.className).indexOf('human') > -1 || String(parent.className).indexOf('user') > -1)) { isUser=true; break; }
      parent = parent.parentElement;
    }
    if(isUser) continue;
    var t = textOf(el);
    if(t.length > minLen && t.length > best.length) best = t;
  }
  if(!best){
    var divs = Array.from(document.querySelectorAll('main [class*=content]'));
    for(var i=0; i<divs.length; i++){
      var t = textOf(divs[i]);
      if(t.length > 40 && t.length > best.length && t.indexOf('flow-chat') === -1) best = t;
    }
  }
  return JSON.stringify({found: best.length > 0, answer: best, refs: 0});
})()"""

KIMI_EXTRACT_JS = """(function(){
  function textOf(e){ return (e.innerText||'').trim(); }
  var mds = Array.from(document.querySelectorAll('.segment-content .markdown, .markdown-body'));
  if(mds.length > 0){
    var t = textOf(mds[mds.length - 1]);
    if(t.length > 10) return JSON.stringify({found:true, answer:t, refs:0});
  }
  var segs = Array.from(document.querySelectorAll('.segment-content'));
  if(segs.length > 0){
    for(var i=segs.length-1; i>=0; i--){
      var t = textOf(segs[i]);
      if(t.length > 20) return JSON.stringify({found:true, answer:t, refs:0});
    }
  }
  return JSON.stringify({found:false, answer:'', refs:0});
})()"""

# ---------------------------------------------------------------- Engine registry

ENGINES = {
    "yuanbao": {
        "name": "\u817e\u8baf\u5143\u5b9d",
        "icon": "\U0001f427",
        "badge": "\u5fae\u4fe1\u516c\u4f17\u53f7\u751f\u6001 + \u5168\u7f51\u68c0\u7d22",
        "session": "yuanbao",
        "site_url": "https://yuanbao.tencent.com/chat",
        "site_host": "yuanbao.tencent.com",
        "fill_selector": "[contenteditable=true]",
        "submit": {"js_click": "document.querySelector('#yuanbao-send-btn') && document.querySelector('#yuanbao-send-btn').click()"},
        "probe_js": "!!document.querySelector('[contenteditable=true]')",
        "extract_js": YUANBAO_EXTRACT_JS,
    },
    "doubao": {
        "name": "\u5b57\u8282\u8c46\u5305",
        "icon": "\U0001f9e9",
        "badge": "\u5b57\u8282\u6296\u97f3\u5168\u7f51\u5b9e\u65f6\u68c0\u7d22",
        "session": "doubao",
        "site_url": "https://www.doubao.com/chat",
        "site_host": "doubao.com",
        "fill_selector": "textarea",
        "fill_nth": 0,
        "input_method": "type",
        "submit": {
            "js_click": "document.getElementById('flow-end-msg-send') && document.getElementById('flow-end-msg-send').click()",
            "keys": "Enter",
        },
        "probe_js": "!!document.querySelector('textarea')",
        "extract_js": DOUBAO_EXTRACT_JS,
    },
    "kimi": {
        "name": "\u6708\u4e4b\u6697\u9762 Kimi",
        "icon": "\U0001f319",
        "badge": "200\u4e07\u5b57\u957f\u4e0a\u4e0b\u6587 + \u6df1\u5ea6\u8054\u7f51",
        "session": "kimi",
        "site_url": "https://www.kimi.com/",
        "site_host": "kimi",
        "fill_selector": "[contenteditable=true]",
        "submit": {"js_click": "(function(){ var s=document.querySelector('svg[name=Send]'); var btn=s?s.closest('button,div[role=button]'):null; if(btn)btn.click(); })()"},
        "probe_js": "!!document.querySelector('[contenteditable=true]')",
        "extract_js": KIMI_EXTRACT_JS,
    },
    "qianwen": {
        "name": "\u901a\u4e49\u5343\u95ee",
        "icon": "\U0001f388",
        "badge": "\u963f\u91cc\u901a\u4e49\u5168\u7f51\u667a\u641c",
        "session": "qianwen",
        "site_url": "https://tongyi.aliyun.com/qianwen/",
        "site_host": "qianwen",
        "fill_selector": "textarea, [contenteditable=true]",
        "submit": {"enter": True},
        "probe_js": "!!document.querySelector('textarea, [contenteditable=true]')",
        "extract_js": GENERIC_EXTRACT_JS,
    },
    "metaai": {
        "name": "Meta AI",
        "icon": "\U0001fa69",
        "badge": "Llama 3 real-time search",
        "session": "metaai",
        "site_url": "https://www.meta.ai/",
        "site_host": "meta.ai",
        "fill_selector": "textarea, [contenteditable=true]",
        "submit": {"enter": True},
        "probe_js": "!!document.querySelector('textarea, [contenteditable=true]')",
        "extract_js": GENERIC_EXTRACT_JS,
    },
}

ENGINE_ORDER = ["yuanbao", "doubao", "kimi", "qianwen", "metaai"]

# ---------------------------------------------------------------- 工具函数


def run_cli(args, timeout=90):
    """运行 opencli 命令。args 为参数列表；JS 一律只用单引号，避免 cmd 引号转义。

    注意：cmd.exe 会把参数内的换行截断（实测导致 JS 'Unexpected end of input'），
    所以对每个参数统一把换行替换为空格（JS 换行只是空白，不影响语义）。
    """
    safe_args = [a.replace("\r", " ").replace("\n", " ") if isinstance(a, str) else a for a in args]
    cmdline = subprocess.list2cmdline([_NODE, _OPENCLI_SCRIPT] + safe_args)
    try:
        proc = subprocess.run(
            cmdline, shell=True, capture_output=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
        return {"ok": proc.returncode == 0, "code": proc.returncode,
                "stdout": proc.stdout.strip(), "stderr": (proc.stderr or "").strip()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": -1, "stdout": "", "stderr": "opencli 超时"}
    except FileNotFoundError:
        return {"ok": False, "code": -2, "stdout": "", "stderr": "opencli 未找到"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "code": -3, "stdout": "", "stderr": str(e)}


def _parse_state_url(stdout):
    """从 `state` 输出中解析当前 URL（兼容大写 URL: / 小写 url:）。"""
    for line in stdout.splitlines():
        if line.lower().startswith("url:"):
            return line.split(":", 1)[1].strip()
    return ""


def extract_answer(sess, eng):
    """调用引擎页面的 extract_js，返回 {found, thinking, answer, answer_html, refs}。"""
    r = run_cli(["browser", sess, "eval", eng["extract_js"]], timeout=60)
    if not r["ok"]:
        return {"found": False, "thinking": "", "answer": "", "answer_html": "", "refs": 0}
    try:
        data = json.loads(r["stdout"])
        if isinstance(data, dict) and data.get("found"):
            return {
                "found": True,
                "thinking": data.get("thinking", ""),
                "answer": data.get("answer", ""),
                "answer_html": data.get("answer_html", ""),
                "refs": int(data.get("refs") or 0)
            }
    except Exception:  # noqa: BLE001
        pass
    return {"found": False, "thinking": "", "answer": "", "answer_html": "", "refs": 0}


def engine_health(engine_id, auto_recover=True):
    """检测单个引擎会话：连通性 + 页面 URL 命中站点 + 输入框存在。若掉线自动尝试打开网页自愈重连。"""
    eng = ENGINES.get(engine_id)
    if not eng:
        return {"id": engine_id, "session": "", "connected": False, "url": "",
                "input_found": False, "error": f"未知引擎 {engine_id}"}
    sess = eng["session"]
    st = run_cli(["browser", sess, "state"])
    if not st["ok"]:
        return {"id": engine_id, "session": sess, "connected": False, "url": "",
                "input_found": False, "error": (st["stderr"] or st["stdout"] or "无连接")[:160]}
    url = _parse_state_url(st["stdout"])
    connected = eng["site_host"] in url

    # 若检测到掉线或停留在 about:blank，自动进行打开网页自愈重连
    if not connected and auto_recover and eng.get("site_url"):
        run_cli(["browser", sess, "open", eng["site_url"]], timeout=40)
        time.sleep(2.5)
        st = run_cli(["browser", sess, "state"])
        if st["ok"]:
            url = _parse_state_url(st["stdout"])
            connected = eng["site_host"] in url

    input_found = False
    if connected:
        p = run_cli(["browser", sess, "eval", eng["probe_js"]], timeout=30)
        input_found = p["ok"] and p["stdout"].strip() == "true"
    return {"id": engine_id, "session": sess, "connected": connected, "url": url,
            "input_found": input_found, "error": ""}


def health_all():
    """并发探测所有引擎会话，避免串行 opencli 调用阻塞启动。"""
    results = {}
    def _probe(eid):
        try:
            results[eid] = engine_health(eid)
        except Exception:  # noqa: BLE001
            results[eid] = {"id": eid, "session": ENGINES.get(eid, {}).get("session"),
                            "connected": False, "url": "", "input_found": False, "error": "探测异常"}
    threads = [threading.Thread(target=_probe, args=(eid,), daemon=True) for eid in ENGINE_ORDER]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=45)
    return {eid: results.get(eid) for eid in ENGINE_ORDER}


def ask_engine(engine_id, prompt, baseline=None, progress=None):
    """向指定 AI 搜索引擎发送 prompt，等待文本稳定后提取思考过程与正文回答。"""
    t0 = time.time()
    eng = ENGINES.get(engine_id)
    if not eng:
        return {"status": "error", "answer": "", "refs": 0, "error": f"未知引擎 {engine_id}", "elapsed": 0}

    sess = eng["session"]
    h = engine_health(engine_id)
    if not h["connected"]:
        return {"status": "unconnected", "answer": "", "refs": 0,
                "error": f"{eng['name']} 会话未绑定，请运行 setup_engines.py 打开页面完成登录",
                "elapsed": time.time() - t0}

    baseline_ans = ""
    baseline_think = ""
    if baseline is None:
        cur = extract_answer(sess, eng)
        if cur["found"]:
            baseline_ans = cur.get("answer", "")
            baseline_think = cur.get("thinking", "")

    if progress:
        progress(f"连接 {eng['name']}…")

    input_method = eng.get("input_method", "fill")
    if input_method == "type":
        focus_js = ("(function(){var el=document.querySelector('%s');"
                    "if(el){el.focus();document.execCommand('selectAll',false,null);"
                    "document.execCommand('insertText',false,'');}return true;})()"
                    % eng["fill_selector"])
        run_cli(["browser", sess, "eval", focus_js], timeout=30)
        type_args = ["browser", sess, "type"]
        if eng.get("fill_nth") is not None:
            type_args += ["--nth", str(eng["fill_nth"])]
        type_args += [eng["fill_selector"], prompt]
        typed = run_cli(type_args, timeout=60)
        if not typed["ok"]:
            return {"status": "error", "answer": "", "refs": 0,
                    "error": f"输入失败: {(typed['stderr'] or typed['stdout'])[:160]}",
                    "elapsed": time.time() - t0}
    else:
        clear_js = ("(function(){var el=document.querySelector('%s');"
                    "if(el){el.focus();document.execCommand('selectAll',false,null);"
                    "document.execCommand('insertText',false,'');}return true;})()"
                    % eng["fill_selector"])
        run_cli(["browser", sess, "eval", clear_js], timeout=30)
        fill_args = ["browser", sess, "fill"]
        if eng.get("fill_nth") is not None:
            fill_args += ["--nth", str(eng["fill_nth"])]
        fill_args += [eng["fill_selector"], prompt]
        fill = run_cli(fill_args, timeout=60)
        if not fill["ok"]:
            return {"status": "error", "answer": "", "refs": 0,
                    "error": f"输入失败: {(fill['stderr'] or fill['stdout'])[:160]}",
                    "elapsed": time.time() - t0}


    # Search tool toggle: removed (contained Chinese chars causing Windows cmd truncation)

    time.sleep(SUBMIT_SETTLE_DELAY)
    sub = eng["submit"]
    if progress:
        progress("已提交，正在检索与思考...")
    if sub.get("js_click"):
        run_cli(["browser", sess, "eval", sub["js_click"]], timeout=30)
    if sub.get("click"):
        run_cli(["browser", sess, "click", sub["click"]], timeout=30)
    if sub.get("keys"):
        run_cli(["browser", sess, "keys", sub["keys"]], timeout=30)

    last = {"found": False, "thinking": "", "answer": "", "answer_html": "", "refs": 0}
    prev_len = 0
    stable_count = 0

    for _ in range(EXTRACT_POLL_MAX):
        time.sleep(EXTRACT_POLL_INTERVAL)
        current = extract_answer(sess, eng)
        if current["found"] and (current["answer"] or current["thinking"]):
            if current.get("answer") == baseline_ans and current.get("thinking") == baseline_think:
                continue
            curr_len = len(current.get("answer", "")) + len(current.get("thinking", ""))
            if curr_len > prev_len:
                last = current
                prev_len = curr_len
                stable_count = 0
                if progress:
                    progress(f"正在思考与生成回答({curr_len}字)…")
            else:
                stable_count += 1
                # 连续 2 次轮询（4秒）文本长度无增长，说明回答已打印完成
                if stable_count >= 2:
                    return {
                        "status": "ok",
                        "thinking": last.get("thinking", ""),
                        "answer": last["answer"],
                        "answer_html": last.get("answer_html", ""),
                        "refs": last["refs"],
                        "error": "",
                        "elapsed": time.time() - t0
                    }

    # 超时：返回最后一次能提取到的最完整内容
    if last["found"] and (last["answer"] or last["thinking"]):
        return {
            "status": "ok",
            "thinking": last.get("thinking", ""),
            "answer": last["answer"],
            "answer_html": last.get("answer_html", ""),
            "refs": last["refs"],
            "error": "",
            "elapsed": time.time() - t0
        }
    return {"status": "timeout", "answer": "", "answer_html": "", "refs": 0,
            "error": "等待回答超时（约 90s），可能是页面会话已失效或该站点未登录",
            "elapsed": time.time() - t0}
