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
  var cc = document.getElementById('chat-content') || document.querySelector('.agent-dialogue') || document.body;

  var items = Array.from(cc.querySelectorAll('.agent-chat__list__item--ai, [class*="agent-chat__list__item"][class*="--ai"]'));
  var answersText = []; var answersHTML = [];
  for (var i = items.length - 1; i >= 0; i--) {
    var t = textOf(items[i]); var h = htmlOf(items[i]);
    if (t.length > 10) {
      answersText.push(t);
      var clone = items[i].cloneNode(true);
      var icons = Array.from(clone.querySelectorAll('svg, img, [class*="icon"], [class*="ref"], a'));
      icons.forEach(function(ic){
        var url = ic.getAttribute('href') || ic.getAttribute('data-url') || ic.getAttribute('data-href');
        var parentA = ic.closest('a');
        if (!url && parentA) url = parentA.getAttribute('href');
        if (url && url.startsWith('http')) {
          var a = document.createElement('a');
          a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer';
          a.className = 'ref-link';
          a.style.cssText = 'font-size:12px;color:#0052cc;background:rgba(0,82,204,0.08);padding:2px 8px;border-radius:6px;text-decoration:none;margin:0 4px;display:inline-flex;align-items:center;gap:4px;vertical-align:middle;';
          a.innerHTML = '🔗 查看原网页 ↗';
          ic.replaceWith(a);
        } else if (ic.tagName.toLowerCase() === 'svg' || ic.tagName.toLowerCase() === 'img') {
          ic.remove();
        }
      });
      answersHTML.push(clone.innerHTML.trim());
      break;
    }
  }

  if (!answersText.length) {
    var cotEls = Array.from(cc.querySelectorAll('.hyc-component-deepsearch-cot__think__content, [class*=deepsearch-cot__think]'));
    var thinking = '';
    for (var k=0; k<cotEls.length; k++){
      var ct = textOf(cotEls[k]);
      if (ct.length > 5 && thinking.indexOf(ct.slice(0,30)) === -1)
        thinking += (thinking ? '\\n' : '') + ct;
    }
    var mdEls = Array.from(cc.querySelectorAll('.hyc-common-markdown-style'));
    for (var m=0; m<mdEls.length; m++){
      var cls = String(mdEls[m].className);
      if (cls.indexOf('-cot') > -1) continue;
      var tm = textOf(mdEls[m]);
      if (tm.length > 15) { answersText.push(tm); answersHTML.push(htmlOf(mdEls[m])); break; }
    }
    if (answersText.length) {
      var answer = answersText[answersText.length - 1];
      var answer_html = answersHTML[answersHTML.length - 1];
      var m2 = (cc.innerText||'').match(/Found\\s*(\\d+)\\s*references/i);
      return JSON.stringify({found:true, thinking:thinking, answer:answer, answer_html:answer_html, refs:m2?parseInt(m2[1],10):0});
    }
    return JSON.stringify({found: false});
  }

  var thinkTxt = '';
  var cot2 = Array.from(cc.querySelectorAll('[class*=deepsearch-cot__think]'));
  for (var c=0; c<cot2.length; c++){
    var ct2 = textOf(cot2[c]);
    if (ct2.length > 5 && thinkTxt.indexOf(ct2.slice(0,30)) === -1)
      thinkTxt += (thinkTxt ? '\\n' : '') + ct2;
  }
  return JSON.stringify({found:true, thinking: thinkTxt, answer: answersText[0], answer_html: answersHTML[0], refs: 0});
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
  var main = document.querySelector('#qianwen-main-area') || document.querySelector('main') || document.body;

  var roots = Array.from(main.querySelectorAll('[class*="pageContentWrap"], [class*="mainContent"], [class*="guideComp"]'));
  if (roots.length > 0) {
    for (var k = roots.length - 1; k >= 0; k--) {
      var md = roots[k].querySelectorAll('.markdown-body, [class*="markdown"], [class*="answer-common-card"], [class*="chat-answers-card"]');
      for (var m = md.length - 1; m >= 0; m--) {
        var t = textOf(md[m]);
        if (t.length > 20 && t.indexOf('你好，我是千问') === -1) {
          return JSON.stringify({found: true, answer: t, answer_html: htmlOf(md[m]), refs: 0});
        }
      }
    }
  }

  var mdEls = Array.from(main.querySelectorAll('.markdown-body'));
  for (var i = mdEls.length - 1; i >= 0; i--) {
    var t2 = textOf(mdEls[i]);
    if (t2.length > 20 && t2.indexOf('你好，我是千问') === -1) {
      return JSON.stringify({found: true, answer: t2, answer_html: htmlOf(mdEls[i]), refs: 0});
    }
  }
  return JSON.stringify({found: false, answer: '', answer_html: '', refs: 0});
})()"""

DOUBAO_EXTRACT_JS = """(function(){
  function textOf(e){ return e ? (e.innerText||'').trim() : ''; }
  function htmlOf(e){ return e ? (e.innerHTML||'').trim() : ''; }
  var main = document.querySelector('main') || document.body;

  var rows = Array.from(main.querySelectorAll('[class*="list_items"] [class*="inner-item"], [class*="list_items"] [class*="v_list_row"], [class*="message-list"] [class*="inner-item"]'));
  var bestText = ''; var bestHTML = '';
  for (var i = rows.length - 1; i >= 0; i--) {
    var t = textOf(rows[i]); var h = htmlOf(rows[i]);
    var cls = String(rows[i].className || '');
    if (cls.indexOf('bg-g-send-msg-bubble-bg') > -1) continue;
    if (t.length <= 20) continue;
    if (t.indexOf('发送消息') > -1 || t.indexOf('历史对话') > -1 || t.indexOf('新对话') > -1 || t.indexOf('深入研究') > -1 || t.indexOf('图像生成') > -1) continue;
    if (t.length > bestText.length) { bestText = t; bestHTML = h; }
  }

  if (!bestText) {
    var lastRow = Array.from(main.querySelectorAll('[class*="list_items"] [class*="v_list_row"]'));
    for (var j = lastRow.length - 1; j >= 0; j--) {
      var t2 = textOf(lastRow[j]);
      if (t2.length > 40) { bestText = t2; bestHTML = htmlOf(lastRow[j]); break; }
    }
  }
  return JSON.stringify({found: bestText.length > 0, answer: bestText, answer_html: bestHTML, refs: 0});
})()"""

KIMI_EXTRACT_JS = """(function(){
  function textOf(e){ return e ? (e.innerText||'').trim() : ''; }
  function htmlOf(e){ return e ? (e.innerHTML||'').trim() : ''; }
  var items = Array.from(document.querySelectorAll('.chat-content-item.chat-content-item-assistant, [class*="chat-content-item"][class*="assistant"]'));
  var bestText = ''; var bestHTML = '';
  for (var i = items.length - 1; i >= 0; i--) {
    var t = textOf(items[i]); var h = htmlOf(items[i]);
    if (t.length > 20 && t.indexOf('稍后再说') === -1 && t.indexOf('新建会话') === -1 && t.indexOf('查看全部') === -1) {
      bestText = t; bestHTML = h;
      break;
    }
  }
  if (!bestText) {
    var blocks = Array.from(document.querySelectorAll('.chat-content-list [class*="chat-content-item"], .chat-content-list > div'));
    for (var j = blocks.length - 1; j >= 0; j--) {
      var cls2 = String(blocks[j].className || '');
      var t2 = textOf(blocks[j]);
      if (cls2.indexOf('user') > -1) continue;
      if (t2.length > 30) { bestText = t2; bestHTML = htmlOf(blocks[j]); break; }
    }
  }
  return JSON.stringify({found: bestText.length > 0, answer: bestText, answer_html: bestHTML, refs: 0});
})()"""

PERPLEXITY_EXTRACT_JS = """(function(){
  function textOf(e){ return e ? (e.innerText||'').trim() : ''; }
  function htmlOf(e){ return e ? (e.innerHTML||'').trim() : ''; }
  var els = Array.from(document.querySelectorAll('[class*=prose], .markdown-body, [class*=answer]'));
  if (els.length > 0) {
    var last = els[els.length - 1];
    var t = textOf(last); var h = htmlOf(last);
    if (t.length > 10) return JSON.stringify({found: true, answer: t, answer_html: h, refs: 0});
  }
  return JSON.stringify({found: false, answer: '', answer_html: '', refs: 0});
})()"""

ZAI_EXTRACT_JS = """(function(){
  function textOf(e){ return e ? (e.innerText||'').trim() : ''; }
  function htmlOf(e){ return e ? (e.innerHTML||'').trim() : ''; }
  var els = Array.from(document.querySelectorAll('.markdown-body, [class*="prose"], [class*="message"], article'));
  var bestText = ''; var bestHTML = '';
  for (var i = els.length - 1; i >= 0; i--) {
    var t = textOf(els[i]); var h = htmlOf(els[i]);
    if (t.length > 15 && t.indexOf('发送消息') === -1) {
      bestText = t; bestHTML = h;
      break;
    }
  }
  return JSON.stringify({found: bestText.length > 0, answer: bestText, answer_html: bestHTML, refs: 0});
})()"""

GROK_EXTRACT_JS = """(function(){
  function textOf(e){ return e ? (e.innerText||'').trim() : ''; }
  function htmlOf(e){ return e ? (e.innerHTML||'').trim() : ''; }

  function isGarbage(t){
    var low = t.toLowerCase();
    if (low.indexOf('limit is gone') > -1) return true;
    if (low.indexOf('upgrade to supergrok') > -1) return true;
    if (low.indexOf('upgrade now') > -1) return true;
    if (low.indexOf('ask grok') > -1) return true;
    if (low.indexOf('toggle sidebar') > -1) return true;
    if (low.indexOf('before limit') > -1) return true;
    return false;
  }

  var items = Array.from(document.querySelectorAll('[class*="items-start"]'));
  var bestText = ''; var bestHTML = '';
  for (var i = items.length - 1; i >= 0; i--) {
    var cls = String(items[i].className || '');
    var el = items[i].querySelector('.message-bubble') || items[i].querySelector('[class*="prose"]') || items[i];
    var t = textOf(el); var h = htmlOf(el);
    if (t.length > 20 && !isGarbage(t)) {
      bestText = t; bestHTML = h;
      break;
    }
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
        "submit": {
            "click": "#yuanbao-send-btn",
            "enter": True
        },
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
        "fill_selector": ".semi-input-textarea",
        "fill_nth": 0,
        "input_method": "type",
        "gentle_submit": True,
        "submit": {
            "js_click": "(function(){ var b = document.querySelector('button[class*=\"send-msg-btn\"]') || document.querySelector('#flow-end-msg-send'); if(b) b.click(); })()",
            "click": "button[class*=\"send-msg-btn\"]",
            "enter": True
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
        "submit": {
            "click": "button[class*=\"send\" i], div.send-button-container",
            "enter": True
        },
        "probe_js": "!!document.querySelector('[contenteditable=true]')",
        "extract_js": KIMI_EXTRACT_JS,
        "dismiss_popup_js": "(function(){ var btns=Array.from(document.querySelectorAll('button, div[role=button]')); for(var i=0;i<btns.length;i++){ if((btns[i].innerText||'').indexOf('稍后再说')>-1){ btns[i].click(); return true; } } return false; })()",
        "new_chat_js": "(function(){ var btn = document.querySelector('svg[name=NewChat]') ? document.querySelector('svg[name=NewChat]').closest('button, div[role=button], div') : null; if(btn) btn.click(); })()",
    },
    "qianwen": {
        "name": "通义千问智搜",
        "icon": "🎈",
        "badge": "阿里通义全网智搜",
        "session": "qianwen",
        "site_url": "https://www.qianwen.com/",
        "site_host": "qianwen",
        "fill_selector": "[role=textbox][contenteditable=true], [contenteditable=true]",
        "fill_nth": 0,
        "input_method": "type",
        "submit": {
            "js_click": "(function(){ var closeBtn=document.querySelector('button[aria-label=关闭]'); if(closeBtn) closeBtn.click(); var btn=document.querySelector('button[aria-label=\"发送消息\"]') || document.querySelector('[aria-label=\"发送消息\"]') || document.querySelector('button[aria-label*=\"发送\"]'); if(btn) btn.click(); })()",
            "click": "button[aria-label=\"发送消息\"]",
            "enter": True
        },
        "probe_js": "!!(document.querySelector('[role=textbox][contenteditable=true]') || document.querySelector('[contenteditable=true]'))",
        "extract_js": QIANWEN_EXTRACT_JS,
        "dismiss_popup_js": "(function(){ var b=document.querySelector('button[aria-label=关闭]') || document.querySelector('[data-testid=home-guide-carousel] button'); if(b) b.click(); })()",
        "new_chat_js": "(function(){ var btn = document.querySelector('button[aria-label*=\"新建对话\"]'); if(btn) btn.click(); })()",
    },
    "grok": {
        "name": "Grok",
        "icon": "🤖",
        "badge": "Grok 实时全网智搜",
        "session": "grok",
        "site_url": "https://grok.com/",
        "site_host": "grok.com",
        "fill_selector": ".tiptap.ProseMirror, [contenteditable=true]",
        "fill_nth": 0,
        "submit": {
            "click": "button[data-testid=\"chat-submit\"]",
            "enter": True
        },
        "probe_js": "!!document.querySelector('[contenteditable=true]')",
        "extract_js": GROK_EXTRACT_JS,
        "dismiss_popup_js": "(function(){ var b=document.querySelector('#accept-recommended-btn-handler, #onetrust-accept-btn-handler'); if(b){ b.click(); return true; } return false; })()",
        "new_chat_js": "(function(){ var a = document.querySelector('a[href=\"/\"]'); if(a) a.click(); })()",
    },
    "perplexity": {
        "name": "Perplexity 搜",
        "icon": "🔍",
        "badge": "Perplexity 深度检索",
        "session": "perplexity",
        "site_url": "https://www.perplexity.ai/",
        "site_host": "perplexity.ai",
        "fill_selector": "textarea",
        "fill_nth": 0,
        "submit": {
            "click": "button[aria-label*=\"Submit\" i], button[aria-label*=\"Send\" i]",
            "enter": True
        },
        "probe_js": "!!document.querySelector('textarea')",
        "extract_js": PERPLEXITY_EXTRACT_JS,
        "new_chat_js": "(function(){ var btn = document.querySelector('[aria-label*=\"New thread\"]'); if(btn) btn.click(); })()",
    },
    "zai": {
        "name": "Z.ai 智搜",
        "icon": "⚡",
        "badge": "Z.ai 智能全网检索",
        "session": "zai",
        "site_url": "https://z.ai/",
        "site_host": "z.ai",
        "fill_selector": "textarea, [contenteditable=\"true\"]",
        "fill_nth": 0,
        "submit": {
            "click": "button[type=\"submit\"], button[aria-label*=\"Send\" i]",
            "enter": True
        },
        "probe_js": "!!document.querySelector('textarea, [contenteditable=\"true\"]')",
        "extract_js": ZAI_EXTRACT_JS,
        "new_chat_js": "(function(){ var a = document.querySelector('a[href=\"/\"]'); if(a) a.click(); })()",
    },
}

ENGINE_ORDER = ["yuanbao", "doubao", "kimi", "qianwen", "grok", "perplexity", "zai"]


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

    # 检查当前 Session 页面 URL。若已在聊天页面中，禁止重置跳转！
    st = run_cli(["browser", sess, "state"], timeout=10)
    current_url = st.get("stdout", "")
    if ("about:blank" in current_url or not current_url.strip()) or (eng["site_host"] not in current_url):
        run_cli(["browser", sess, "open", eng["site_url"]], timeout=25)
        time.sleep(2.0)
    else:
        if eng.get("new_chat_js"):
            run_cli(["browser", sess, "eval", eng["new_chat_js"]], timeout=10)
            time.sleep(0.5)

    # 动态等待输入框 DOM 元素真正挂载就绪，解决 React/Vue 渲染延迟
    fill_sel = eng["fill_selector"]
    for _ in range(6):
        chk = run_cli(["browser", sess, "eval", f"!!document.querySelector('{fill_sel}')"], timeout=10)
        if chk["ok"] and chk["stdout"].strip() == "true":
            break
        time.sleep(0.8)

    if eng.get("dismiss_popup_js"):
        run_cli(["browser", sess, "eval", eng["dismiss_popup_js"]], timeout=10)

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

    injected = {"ok": False, "stdout": ""}
    if eng.get("input_method") == "type":
        # 原生键入注入：对 JS 注入感知不友好的 React 富文本编辑器，用 CDP 原生 type
        focus_try = run_cli(["browser", sess, "eval", "(function(){ var el=document.querySelector(%s); if(el) el.focus(); return !!el; })()" % json.dumps(eng["fill_selector"].split(",")[0].strip())], timeout=10)
        time.sleep(0.2)
        t_res = run_cli(["browser", sess, "type", eng["fill_selector"].split(",")[0].strip(), prompt], timeout=30)
        if t_res["ok"]:
            injected = {"ok": True, "stdout": "true"}
    if not injected["ok"] or injected.get("stdout", "").strip() != "true":
        universal_input_js = ("(function(){"
                              "  var el = document.querySelector(%s);"
                              "  if(!el) return false;"
                              "  el.focus();"
                              "  if(el.tagName === 'TEXTAREA' || el.tagName === 'INPUT'){"
                              "    var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value') ? "
                              "      Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set : null;"
                              "    if(nativeSetter){ nativeSetter.call(el, %s); } else { el.value = %s; }"
                              "    el.dispatchEvent(new Event('input', { bubbles: true }));"
                              "    el.dispatchEvent(new Event('change', { bubbles: true }));"
                              "  } else {"
                              "    el.innerHTML = '<p>' + %s + '</p>';"
                              "    document.execCommand('selectAll', false, null);"
                              "    document.execCommand('insertText', false, %s);"
                              "    el.dispatchEvent(new Event('input', { bubbles: true }));"
                              "    el.dispatchEvent(new Event('change', { bubbles: true }));"
                              "  }"
                              "  return true;"
                              "})()") % (json.dumps(eng["fill_selector"]), json.dumps(prompt), json.dumps(prompt), json.dumps(prompt), json.dumps(prompt))

        injected = run_cli(["browser", sess, "eval", universal_input_js], timeout=30)
        if not injected["ok"] or injected.get("stdout", "").strip() != "true":
            paste_js = ("(function(){"
                        "  var el = document.querySelector(%s);"
                        "  if(!el) return false;"
                        "  el.focus();"
                        "  var dt=new DataTransfer();"
                        "  dt.setData('text/plain', %s);"
                        "  var ev=new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true});"
                        "  el.dispatchEvent(ev);"
                        "  return true;"
                        "})()") % (json.dumps(eng["fill_selector"]), json.dumps(prompt))
            run_cli(["browser", sess, "eval", paste_js], timeout=30)

    # 1. 强制聚焦输入框
    focus_js = "(function(){ var el = document.querySelector('" + eng["fill_selector"] + "'); if(el){ el.focus(); return true; } return false; })()"
    run_cli(["browser", sess, "eval", focus_js], timeout=10)
    time.sleep(0.3)

    sub = eng["submit"]
    if eng.get("gentle_submit"):
        # 温和单次提交：对风控敏感的站点(豆包)只用一次原生 Enter + 按住按钮点击，
        # 避免频谱轰炸式交互触发风控。点击后等待 settle。
        if progress:
            progress(f"提交至 {eng['name']}…")
        run_cli(["browser", sess, "keys", "Enter"], timeout=10)
        time.sleep(SUBMIT_SETTLE_DELAY)
        if sub.get("click"):
            run_cli(["browser", sess, "click", sub["click"]], timeout=8)
        time.sleep(SUBMIT_SETTLE_DELAY)
    else:
        # 2. 优先通过 CDP 发送绝对真实的原生 Enter 回车按键 (isTrusted=true)
        res_keys = run_cli(["browser", sess, "keys", "Enter"], timeout=10)

        # 3. 补发按钮点击作为二重保障
        time.sleep(0.6)
        if sub.get("js_click"):
            run_cli(["browser", sess, "eval", sub["js_click"]], timeout=10)
        if sub.get("click"):
            run_cli(["browser", sess, "click", sub["click"]], timeout=8)

        # 多引擎协同提交双重校验触发与强制补偿补发回车
        time.sleep(1.0)
        focus_and_enter_js = "(function(){ var el = document.querySelector('" + eng["fill_selector"] + "'); if(el){ el.focus(); var ev=new KeyboardEvent('keydown',{key:'Enter',code:'Enter',keyCode:13,bubbles:true}); el.dispatchEvent(ev); } })()"
        run_cli(["browser", sess, "eval", focus_and_enter_js], timeout=15)
        run_cli(["browser", sess, "keys", "Enter"], timeout=15)

    last = {"found": False, "thinking": "", "answer": "", "answer_html": "", "refs": 0}
    prev_len = 0
    stable_count = 0

    for i in range(EXTRACT_POLL_MAX):
        time.sleep(EXTRACT_POLL_INTERVAL)
        current = extract_answer(sess, eng)
        if current["found"] and (current["answer"] or current["thinking"]):
            # 关键校验：若抓取到的回答与提问前的旧回答完全相同，说明页面尚未更新新回答，必须跳过！
            if baseline_ans and current.get("answer") == baseline_ans and current.get("thinking") == baseline_think:
                continue

            curr_len = len(current.get("answer", "")) + len(current.get("thinking", ""))
            if curr_len > prev_len:
                last = current
                prev_len = curr_len
                stable_count = 0
                if progress:
                    progress(f"正在生成回答({curr_len}字)…")
            else:
                stable_count += 1
                if stable_count >= 3 and curr_len > 10:
                    last = current
                    break

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
