# -*- coding: utf-8 -*-
"""
引擎适配层 (engine adapters) —— 通过本地 opencli 浏览器会话无感操控已登录的 AI 搜索引擎网页端。
Engine adapter layer: controls logged-in AI search engine web sessions via opencli.
Supports single-turn and multi-turn conversations.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid

GATEWAY_ID = os.environ.get("GATEWAY_ID", "ds_v4_cli")
try:
    _SHARED = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            "..", "..", "03_共享组件"))
    if _SHARED not in sys.path:
        sys.path.insert(0, _SHARED)
    from history import save_turn as _history_save_turn
except Exception:  # noqa: BLE001 共享组件缺失时不影响主流程
    _history_save_turn = None

OPENCLI = "opencli"
_NODE = "D:/Program Files/nodejs/node.exe"
_OPENCLI_SCRIPT = "C:/Users/郭永涛/AppData/Roaming/npm/node_modules/@jackwener/opencli/dist/src/main.js"

EXTRACT_POLL_INTERVAL = 2.0
EXTRACT_POLL_MAX = 45
SUBMIT_SETTLE_DELAY = 1.2

def _cli_prefix():
    return [_NODE, _OPENCLI_SCRIPT]


# 全局多轮对话上下文存储
# conversation_id -> {"engine_id": str, "history": [{"role": "user"|"assistant", "content": str, "thinking": str}], "created_at": str}
CONVERSATIONS = {}

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
  var candidates = Array.from(document.querySelectorAll('.markdown-body, [class*=markdown], [class*=response], [class*=answer], [class*=prose], article'));
  var best = '';
  for (var i=0;i<candidates.length;i++){
    var t = textOf(candidates[i]);
    if (t.length > 40 && t.length > best.length) best = t;
  }
  return JSON.stringify({found: best.length > 0, answer: best, refs: 0});
})()"""

QIANWEN_EXTRACT_JS = """(function(){
  function textOf(e){ return e ? (e.innerText||'').trim() : ''; }
  function htmlOf(e){ return e ? (e.innerHTML||'').trim() : ''; }
  var answers = Array.from(document.querySelectorAll('[class*=message-select-wrapper-answer], .markdown-body'));
  var bestText = ''; var bestHTML = '';
  for(var i=0; i<answers.length; i++){
    var t = textOf(answers[i]); var h = htmlOf(answers[i]);
    if(t.length > 0) { bestText = t; bestHTML = h; }
  }
  if(!bestText){
    var lastRound = document.querySelector('[class*=last-message-item]');
    if(lastRound){
      var as = lastRound.querySelectorAll('[class*=message-select-wrapper-answer]');
      if(as.length) { bestText = textOf(as[as.length-1]); bestHTML = htmlOf(as[as.length-1]); }
    }
  }
  return JSON.stringify({found: bestText.length > 0, answer: bestText, answer_html: bestHTML, refs: 0});
})()"""

DOUBAO_EXTRACT_JS = """(function(){
  function textOf(e){ return e ? (e.innerText||'').trim() : ''; }
  function htmlOf(e){ return e ? (e.innerHTML||'').trim() : ''; }

  var bestText = ''; var bestHTML = '';

  var mdEls = Array.from(document.querySelectorAll('[class*=markdown-body], [class*=markdown], [class*=message_content], [class*=v_list_row], [class*=answer], [class*=ai-message]'));
  if (mdEls.length > 0) {
    for (var i = mdEls.length - 1; i >= 0; i--) {
      var t = textOf(mdEls[i]); var h = htmlOf(mdEls[i]);
      if (t.length > 15 && t.indexOf('flow-chat') === -1) {
        bestText = t; bestHTML = h;
        break;
      }
    }
  }

  if (!bestText) {
    var li = document.querySelector('[class*=list_items]') || document.querySelector('[class*=message-list]');
    if (li) {
      var rows = Array.from(li.querySelectorAll(':scope > [class*=v_list_row], [class*=v_list_row]'));
      for (var i = rows.length - 1; i >= 0; i--) {
        var t = textOf(rows[i]); var h = htmlOf(rows[i]);
        if (t.length >= 15) {
          bestText = t; bestHTML = h;
          break;
        }
      }
    }
  }

  if (!bestText) {
    var divs = Array.from(document.querySelectorAll('main [class*=content]'));
    for (var i = 0; i < divs.length; i++) {
      var t = textOf(divs[i]); var h = htmlOf(divs[i]);
      if (t.length > 40 && t.length > bestText.length && t.indexOf('flow-chat') === -1) {
        bestText = t; bestHTML = h;
      }
    }
  }

  if (!bestText) return JSON.stringify({found: false});
  return JSON.stringify({found: true, answer: bestText, answer_html: bestHTML, refs: 0});
})()"""

KIMI_EXTRACT_JS = """(function(){
  function textOf(e){ return e ? (e.innerText||'').trim() : ''; }
  function htmlOf(e){ return e ? (e.innerHTML||'').trim() : ''; }
  var mds = Array.from(document.querySelectorAll('.segment-content .markdown, .markdown-body'));
  if(mds.length > 0){
    var target = mds[mds.length - 1];
    var t = textOf(target); var h = htmlOf(target);
    if(t.length > 10) return JSON.stringify({found:true, answer:t, answer_html:h, refs:0});
  }
  var segs = Array.from(document.querySelectorAll('.segment-content'));
  if(segs.length > 0){
    for(var i=segs.length-1; i>=0; i--){
      var t = textOf(segs[i]); var h = htmlOf(segs[i]);
      if(t.length > 20) return JSON.stringify({found:true, answer:t, answer_html:h, refs:0});
    }
  }
  return JSON.stringify({found:false, answer:'', refs:0});
})()"""

PERPLEXITY_EXTRACT_JS = """(function(){
  function textOf(e){ return e ? (e.innerText||'').trim() : ''; }
  function htmlOf(e){ return e ? (e.innerHTML||'').trim() : ''; }
  var els = Array.from(document.querySelectorAll('[class*=prose], .markdown-body, [class*=answer]'));
  var bestText = ''; var bestHTML = '';
  for(var i=0; i<els.length; i++){
    var t = textOf(els[i]); var h = htmlOf(els[i]);
    if(t.length > 20 && t.length > bestText.length) { bestText = t; bestHTML = h; }
  }
  return JSON.stringify({found: bestText.length > 0, answer: bestText, answer_html: bestHTML, refs: 0});
})()"""

GROK_EXTRACT_JS = """(function(){
  function textOf(e){ return e ? (e.innerText||'').trim() : ''; }
  function htmlOf(e){ return e ? (e.innerHTML||'').trim() : ''; }
  var els = Array.from(document.querySelectorAll('.markdown-body, [class*=message-content], [class*=prose]'));
  var bestText = ''; var bestHTML = '';
  for(var i=0; i<els.length; i++){
    var t = textOf(els[i]); var h = htmlOf(els[i]);
    if(t.length > 20 && t.length > bestText.length) { bestText = t; bestHTML = h; }
  }
  return JSON.stringify({found: bestText.length > 0, answer: bestText, answer_html: bestHTML, refs: 0});
})()"""


# ---------------------------------------------------------------- Engine registry

ENGINES = {
    "yuanbao": {
        "name": "腾讯元宝",
        "icon": "🐧",
        "badge": "微信公众号生态 + 全网检索",
        "session": "yuanbao",
        "site_url": "https://yuanbao.tencent.com/chat",
        "site_host": "yuanbao.tencent.com",
        "fill_selector": "[contenteditable=true]",
        "submit": {"js_click": "document.querySelector('#yuanbao-send-btn') && document.querySelector('#yuanbao-send-btn').click()"},
        "probe_js": "!!document.querySelector('[contenteditable=true]')",
        "extract_js": YUANBAO_EXTRACT_JS,
        "new_chat_js": "(function(){ var btn = document.querySelector('[class*=new-chat], [class*=new_chat]'); if(btn) btn.click(); })()",
    },
    "doubao": {
        "name": "字节豆包",
        "icon": "🧩",
        "badge": "字节抖音全网实时检索",
        "session": "doubao",
        "site_url": "https://www.doubao.com/chat",
        "site_host": "doubao.com",
        "fill_selector": "textarea",
        "fill_nth": 0,
        "input_method": "react_input",
        "submit": {
            "js_click": "document.getElementById('flow-end-msg-send') && document.getElementById('flow-end-msg-send').click()",
            "keys": "Enter",
        },
        "probe_js": "!!document.querySelector('textarea')",
        "extract_js": DOUBAO_EXTRACT_JS,
        "new_chat_js": "(function(){ var btn = document.querySelector('[class*=new-chat-button], [data-testid*=new_chat]'); if(btn) btn.click(); })()",
    },
    "kimi": {
        "name": "月之暗面 Kimi",
        "icon": "🌙",
        "badge": "200万字长上下文 + 深度联网",
        "session": "kimi",
        "site_url": "https://www.kimi.com/",
        "site_host": "kimi",
        "fill_selector": "[contenteditable=true]",
        "submit": {"js_click": "(function(){ var s=document.querySelector('svg[name=Send]'); var btn=s?s.closest('button,div[role=button]'):null; if(btn)btn.click(); })()"},
        "probe_js": "!!document.querySelector('[contenteditable=true]')",
        "extract_js": KIMI_EXTRACT_JS,
        "dismiss_popup_js": "(function(){ var btns=Array.from(document.querySelectorAll('button, div[role=button]')); for(var i=0;i<btns.length;i++){ if((btns[i].innerText||'').indexOf('稍后再说')>-1){ btns[i].click(); return true; } } return false; })()",
        "new_chat_js": "(function(){ var btn = document.querySelector('svg[name=NewChat]') ? document.querySelector('svg[name=NewChat]').closest('button, div[role=button]') : null; if(btn) btn.click(); })()",
    },
    "qianwen": {
        "name": "通义千问",
        "icon": "🎈",
        "badge": "阿里通义全网智搜",
        "session": "qianwen",
        "site_url": "https://tongyi.aliyun.com/qianwen/",
        "site_host": "qianwen",
        "fill_selector": "[contenteditable=true]",
        "input_method": "clipboard",
        "submit": {"enter": True},
        "probe_js": "!!document.querySelector('[contenteditable=true]')",
        "extract_js": QIANWEN_EXTRACT_JS,
        "new_chat_js": "(function(){ var btn = document.querySelector('[class*=new-chat]'); if(btn) btn.click(); })()",
    },
    "grok": {
        "name": "Grok",
        "icon": "🤖",
        "badge": "xAI Grok real-time search",
        "session": "grok",
        "site_url": "https://grok.com/",
        "site_host": "grok.com",
        "fill_selector": "textarea, [contenteditable=true]",
        "input_method": "type",
        "submit": {
            "keys": "Enter",
            "js_click": "(function(){ var el=document.querySelector('button[type=submit], button[aria-label*=send i], [data-testid*=Send]'); if(el) el.click(); })()"
        },
        "probe_js": "!!document.querySelector('textarea, [contenteditable=true]')",
        "extract_js": GROK_EXTRACT_JS,
        "new_chat_js": "(function(){ var btn = document.querySelector('a[href=\"/\"], button[aria-label*=\"New\"]'); if(btn) btn.click(); })()",
    },
    "perplexity": {
        "name": "Perplexity",
        "icon": "🔍",
        "badge": "Perplexity real-time search",
        "session": "perplexity",
        "site_url": "https://www.perplexity.ai/",
        "site_host": "perplexity.ai",
        "fill_selector": "textarea, [contenteditable=true]",
        "input_method": "type",
        "submit": {
            "js_click": "(function(){ var el=document.querySelector('button[type=submit], button[aria-label*=Submit], button[aria-label*=send]'); if(el) el.click(); })()",
            "keys": "Enter"
        },
        "probe_js": "!!document.querySelector('textarea, [contenteditable=true]')",
        "extract_js": PERPLEXITY_EXTRACT_JS,
        "new_chat_js": "(function(){ var btn = document.querySelector('a[href=\"/\"], button[aria-label*=\"New\"]'); if(btn) btn.click(); })()",
    },
}

ENGINE_ORDER = ["yuanbao", "doubao", "kimi", "qianwen", "grok", "perplexity"]


# ---------------------------------------------------------------- 工具函数

def run_cli(args, timeout=90):
    """运行 opencli 命令。args 为参数列表；JS 一律只用单引号，避免 cmd 引号转义。"""
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
    except Exception as e:
        return {"ok": False, "code": -3, "stdout": "", "stderr": str(e)}


def _parse_state_url(stdout):
    """从 state 输出中解析当前 URL。"""
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
    except Exception:
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

    if not connected and auto_recover and eng.get("site_url"):
        run_cli(["browser", sess, "open", eng["site_url"]], timeout=40)
        time.sleep(2.5)
        st = run_cli(["browser", sess, "state"])
        if st["ok"]:
            url = _parse_state_url(st["stdout"])
            connected = eng["site_host"] in url

    input_found = False
    if connected:
        if eng.get("dismiss_popup_js"):
            run_cli(["browser", sess, "eval", eng["dismiss_popup_js"]], timeout=15)
        p = run_cli(["browser", sess, "eval", eng["probe_js"]], timeout=30)
        input_found = p["ok"] and p["stdout"].strip() == "true"
    return {"id": engine_id, "session": sess, "connected": connected, "url": url,
            "input_found": input_found, "error": ""}


def health_all():
    """并发探测所有引擎会话。"""
    results = {}
    def _probe(eid):
        try:
            results[eid] = engine_health(eid)
        except Exception:
            results[eid] = {"id": eid, "session": ENGINES.get(eid, {}).get("session"),
                            "connected": False, "url": "", "input_found": False, "error": "探测异常"}
    threads = [threading.Thread(target=_probe, args=(eid,), daemon=True) for eid in ENGINE_ORDER]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=45)
    return {eid: results.get(eid) for eid in ENGINE_ORDER}


# ---------------------------------------------------------------- 单轮问答

def ask_engine(engine_id, prompt, baseline=None, progress=None):
    """单次问答接口。"""
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

    if eng.get("dismiss_popup_js"):
        run_cli(["browser", sess, "eval", eng["dismiss_popup_js"]], timeout=15)

    baseline_ans = ""
    baseline_think = ""
    if baseline is None:
        cur = extract_answer(sess, eng)
        if cur["found"]:
            baseline_ans = cur.get("answer", "")
            baseline_think = cur.get("thinking", "")
    else:
        baseline_ans = baseline.get("answer", "")
        baseline_think = baseline.get("thinking", "")

    if progress:
        progress(f"连接 {eng['name']}…")

    input_method = eng.get("input_method", "fill")
    if input_method == "clipboard":
        paste_js = ("(function(){"
                    "  var el = document.querySelector('%s');"
                    "  if(!el) return false;"
                    "  el.focus();"
                    "  var dt=new DataTransfer();"
                    "  dt.setData('text/plain', %s);"
                    "  var ev=new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true});"
                    "  el.dispatchEvent(ev);"
                    "  return true;"
                    "})()") % (eng["fill_selector"], json.dumps(prompt))
        pasted = run_cli(["browser", sess, "eval", paste_js], timeout=30)
        if not pasted["ok"] or pasted["stdout"].strip() != "true":
            return {"status": "error", "answer": "", "refs": 0,
                    "error": f"输入失败: {(pasted['stderr'] or pasted['stdout'])[:160]}",
                    "elapsed": time.time() - t0}
    elif input_method == "react_input":
        react_fill_js = ("(function(){"
                         "  var el = document.querySelector('%s');"
                         "  if(!el) return false;"
                         "  el.focus();"
                         "  var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;"
                         "  nativeSetter.call(el, %s);"
                         "  el.dispatchEvent(new Event('input', { bubbles: true }));"
                         "  el.dispatchEvent(new Event('change', { bubbles: true }));"
                         "  return true;"
                         "})()") % (eng["fill_selector"], json.dumps(prompt))
        typed = run_cli(["browser", sess, "eval", react_fill_js], timeout=30)
        if not typed["ok"] or typed["stdout"].strip() != "true":
            type_args = ["browser", sess, "type"]
            if eng.get("fill_nth") is not None:
                type_args += ["--nth", str(eng["fill_nth"])]
            type_args += [eng["fill_selector"], prompt]
            run_cli(type_args, timeout=60)
    elif input_method == "type":
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
    if sub.get("enter"):
        run_cli(["browser", sess, "keys", "Enter"], timeout=30)

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


# ---------------------------------------------------------------- 多轮对话 API (task_007)

def start_conversation(engine_id):
    """开始新对话，返回 conversation_id。"""
    eng = ENGINES.get(engine_id)
    if not eng:
        raise ValueError(f"未知引擎 {engine_id}")
    
    cid = f"conv_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    
    sess = eng["session"]
    if eng.get("new_chat_js"):
        run_cli(["browser", sess, "eval", eng["new_chat_js"]], timeout=15)
        time.sleep(1.0)
    
    CONVERSATIONS[cid] = {
        "engine_id": engine_id,
        "history": [],
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    return cid


def ask_conversation(engine_id, conversation_id, prompt):
    """在已有对话中追问。"""
    conv = CONVERSATIONS.get(conversation_id)
    if not conv:
        conversation_id = start_conversation(engine_id)
        conv = CONVERSATIONS[conversation_id]
    
    eng = ENGINES.get(engine_id)
    if not eng:
        return {"status": "error", "answer": "", "error": f"未知引擎 {engine_id}"}
    
    sess = eng["session"]
    baseline = extract_answer(sess, eng)
    
    res = ask_engine(engine_id, prompt, baseline=baseline)
    
    conv["history"].append({"role": "user", "content": prompt, "time": time.strftime("%H:%M:%S")})
    if res["status"] == "ok":
        conv["history"].append({
            "role": "assistant",
            "content": res.get("answer", ""),
            "thinking": res.get("thinking", ""),
            "refs": res.get("refs", 0),
            "time": time.strftime("%H:%M:%S")
        })
    res["conversation_id"] = conversation_id

    # task_010：持久化到本地 history.json（共享组件），失败不影响返回
    if _history_save_turn is not None:
        try:
            _history_save_turn(GATEWAY_ID, engine_id, conversation_id, "user", prompt)
            if res["status"] == "ok" and res.get("answer"):
                _history_save_turn(GATEWAY_ID, engine_id, conversation_id,
                                   "assistant", res["answer"])
        except Exception:  # noqa: BLE001
            pass
    return res


def get_conversation_history(engine_id, conversation_id):
    """获取对话历史。"""
    conv = CONVERSATIONS.get(conversation_id)
    if not conv:
        return []
    return conv.get("history", [])


def end_conversation(engine_id, conversation_id):
    """结束对话，清理资源。"""
    if conversation_id in CONVERSATIONS:
        del CONVERSATIONS[conversation_id]
        return True
    return False
