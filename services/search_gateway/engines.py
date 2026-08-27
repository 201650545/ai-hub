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
VERIFY_SUBMIT_DELAY = 5.0  # 提交后等待会话开始的秒数（verify_js 兜底判定用）

# ---------------------------------------------------------------- Extract JS

YUANBAO_EXTRACT_JS = """(function(){
  function textOf(e){ return e ? (e.innerText||'').trim() : ''; }
  function htmlOf(e){ return e ? (e.innerHTML||'').trim() : ''; }
  var cc = document.getElementById('chat-content') || document.body;

  /* 气泡选择器：查找所有气泡，取最后一个AI气泡（勿用行注释——run_cli 折叠换行后会被吞） */
  var bubbles = Array.from(cc.querySelectorAll('.agent-chat__bubble'));
  var lastBubble = null;
  for(var i=bubbles.length-1; i>=0; i--){
    var cls = String(bubbles[i].className);
    if(cls.indexOf('bubble--ai') > -1 || cls.indexOf('hunyuan') > -1){
      lastBubble = bubbles[i];
      break;
    }
  }

  var answer = '';
  var answer_html = '';
  if(lastBubble){
    var rawText = textOf(lastBubble);
    answer = rawText.replace(/Deep thinking completed[^\n]*/g, '').trim();
    answer_html = lastBubble.innerHTML;
  }

  var thinking = '';
  if(lastBubble){
    var t = lastBubble.innerText || '';
    var thinkMatch = t.match(/Deep thinking completed[^\\n]*/);
    if(thinkMatch) thinking = thinkMatch[0];
  }

  /* 兜底：从末尾取最新 markdown 块（首个块是旧消息，恒等于 baseline 会致轮询超时） */
  if(!answer){
    var els = Array.from(cc.querySelectorAll('.hyc-common-markdown-style, .agent-chat__conv--ai__speech_show'));
    for(var i=els.length-1; i>=0; i--){
      var t = textOf(els[i]);
      if(t.length > 15 && answer.indexOf(t) === -1){
        answer = t;
        answer_html = htmlOf(els[i]);
        break;
      }
    }
  }

  if(!answer && !thinking) return JSON.stringify({found: false});
  var m = (cc.innerText||'').match(/Found\\s*(\\d+)\\s*references/i);
  return JSON.stringify({found:true,thinking:thinking,answer:answer,answer_html:answer_html,refs:m?parseInt(m[1],10):0});
})()"""

GENERIC_EXTRACT_JS = """(function(){
  function textOf(e){ return (e.innerText||'').trim(); }
  var ans = '';
  var answers = Array.from(document.querySelectorAll('[class*=message-select-wrapper-answer]'));
  for(var i=0; i<answers.length; i++){ var t = textOf(answers[i]); if(t.length > ans.length) ans = t; }
  if(!ans){
    var mds = Array.from(document.querySelectorAll('.qk-markdown'));
    for(var j=0; j<mds.length; j++){ var t = textOf(mds[j]); if(t.length > ans.length) ans = t; }
  }
  if(!ans){
    var cards = Array.from(document.querySelectorAll('.answer-common-card'));
    for(var k=0; k<cards.length; k++){ var t = textOf(cards[k]); if(t.length > ans.length) ans = t; }
  }
  if(ans) return JSON.stringify({found:true, answer:ans, refs:0});
  return JSON.stringify({found:false, answer:'', refs:0});
})()"""

DOUBAO_EXTRACT_JS = """(function(){
  function textOf(e){ return (e.innerText||'').trim(); }
  var thinking = '';
  var answers = [];
  /* 收集所有带 thinking box 的行(排除用户消息/侧栏) */
  var rows = Array.from(document.querySelectorAll('.v_list_row, [data-thinking-box], [class*=thinking]'));
  var seen = {};
  for(var i=0; i<rows.length; i++){
    var r = rows[i];
    var th = r.querySelector('[data-thinking-box]') || r.querySelector('[data-thinking-box="content"]');
    if(th){
      var tt = textOf(th);
      if(tt.length > 2 && tt.indexOf('已思考') === -1 && !seen[tt.slice(0,20)]) { seen[tt.slice(0,20)] = 1; thinking += (thinking ? '\n' : '') + tt; }
    }
    var mds = Array.from(r.querySelectorAll('.md-box-root, [class*=md-box], [class*=markdown]'));
    for(var j=0; j<mds.length; j++){
      var t = textOf(mds[j]);
      if(t.length > 2 && t !== '已思考' && answers.indexOf(t) === -1) answers.push(t);
    }
  }
  if(!answers.length){
    var allMds = Array.from(document.querySelectorAll('.md-box-root, [class*=md-box], [class*=markdown]'));
    for(var k=0; k<allMds.length; k++){
      var t2 = textOf(allMds[k]);
      if(t2.length > 2 && t2 !== '已思考' && answers.indexOf(t2) === -1) answers.push(t2);
    }
  }
  /* 取最后一条,过滤常见噪声前缀 */
  var answer = '';
  for(var m=answers.length-1; m>=0; m--){
    var a = answers[m];
    var isNoise = /^(已思考|正在|好的|用户|让我|首先|识别|Reference|参考|来源|搜索)/.test(a);
    if(!isNoise && a.length > 1) { answer = a; break; }
  }
  if(!answer) return JSON.stringify({found:false});
  return JSON.stringify({found:true, thinking:thinking, answer:answer, refs:0});
})()"""
KIMI_EXTRACT_JS = """(function(){
  function textOf(e){ return (e.innerText||'').trim(); }
  var items = Array.from(document.querySelectorAll('.chat-content-item-assistant'));
  if(!items.length) return JSON.stringify({found:false});
  var ai = items[items.length - 1];
  var thinking = '';
  var tells = Array.from(ai.querySelectorAll('.toolcall-content-text .markdown, [class*=thinking-container] .markdown'));
  for(var i=0; i<tells.length; i++){ var t = textOf(tells[i]); if(t.length > 5 && thinking.indexOf(t.slice(0,30)) === -1) thinking += (thinking ? '\n' : '') + t; }
  var ans = '';
  var mds = Array.from(ai.querySelectorAll('.markdown-container'));
  for(var j=0; j<mds.length; j++){
    var md = mds[j];
    if(md.className && String(md.className).indexOf('toolcall') > -1) continue;
    var t = textOf(md);
    if(t.length > ans.length) ans = t;
  }
  if(!ans){
    var box = ai.querySelector('.segment-content-box');
    if(box){ var full = textOf(box).replace(thinking, '').trim(); if(full.length > 2) ans = full; }
  }
  if(!ans && !thinking) return JSON.stringify({found:false});
  return JSON.stringify({found:true, thinking:thinking, answer:ans, refs:0});
})()"""


def _modern_extract_js(candidates, exclude_host, noise_patterns=None, refs_regex=None,
                       fail_texts=None):
    """新版站点(metaso/grok/perplexity/zai)的通用提取脚本模板。

    这些站点前端改版频繁、类名混淆，无法像元宝那样依赖稳定类名，所以策略是：
    1. 按候选选择器【顺序】找第一个能取到 ≥15 字文本的（精确选择器在前，兜底在后）；
    2. 没命中且页面出现 fail_texts 标记（如 grok 的 "High Demand" 容量墙）
       → 返回 {found:false, fatal:标记}，上层立即报错不空等；
    3. 都没命中则把 main 里所有段落拼起来兜底；
    4. 按行过滤噪声（grok 的 "Worked for 6s"/"10 sources" 等状态行）；
    5. 收集正文外链作为引用来源(ref_links)，refs=外链数（兼容原语义：引用数量）；
       refs_regex 可额外从页面文本抓来源计数（如 grok 的 "N sources"），取两者较大值。
    选择器以「登录后现场 DOM 探查」结果为准持续校准（2026-08-26 首轮校准完成）。
    """
    cand_js = json.dumps(candidates)
    noise_js = json.dumps(noise_patterns or [])
    refs_js = json.dumps(refs_regex) if refs_regex else "null"
    fail_js = json.dumps(fail_texts or [])
    return """(function(){
  function textOf(e){ return e ? (e.innerText||'').trim() : ''; }
  function collectLinks(root){
    var out=[],seen={};
    if(!root) return out;
    try{
      var as=root.querySelectorAll('a[href]');
      for(var i=0;i<as.length;i++){
        var u=as[i].getAttribute('href')||'';
        if(u.indexOf('http')!==0 || u.indexOf('__HOST__')>-1) continue;
        if(seen[u]) continue; seen[u]=1;
        var t=textOf(as[i]).replace(/\\s+/g,' ').trim();
        if(!t) t=u.replace(/^https?:\\/\\/([^\\/]+).*$/,'$1');
        if(t.length>70) t=t.slice(0,67)+'…';
        out.push({title:t,url:u});
        if(out.length>=20) break;
      }
    }catch(e){}
    return out;
  }
  var sels=__CANDS__;
  var best='';
  for(var i=0;i<sels.length;i++){
    var els=document.querySelectorAll(sels[i]);
    for(var j=els.length-1;j>=0;j--){
      var t=textOf(els[j]);
      if(t.length>best.length) best=t;
    }
    if(best.length>=15) break;
  }
  if(best.length<15){
    var fts=__FAILTEXTS__;
    if(fts.length){
      var bt=document.body.innerText||'';
      for(var F=0;F<fts.length;F++){
        if(bt.indexOf(fts[F])>-1) return JSON.stringify({found:false,fatal:fts[F]});
      }
    }
  }
  if(best.length<15){
    var nodes=document.querySelectorAll('main p,main li,main h1,main h2,main h3');
    var buf=[];
    for(var k=0;k<nodes.length;k++){var t2=textOf(nodes[k]);if(t2.length>1)buf.push(t2);}
    best=buf.join('\\n');
  }
  if(!best) return JSON.stringify({found:false});
  var noises=__NOISE__;
  if(noises.length){
    var lines=best.split('\\n');var keep=[];
    for(var L=0;L<lines.length;L++){
      var bad=false;
      for(var N=0;N<noises.length;N++){try{if(new RegExp(noises[N]).test(lines[L].trim())){bad=true;break;}}catch(e){}}
      if(!bad) keep.push(lines[L]);
    }
    best=keep.join('\\n').replace(/\\n{3,}/g,'\\n\\n').trim();
  }
  if(!best) return JSON.stringify({found:false});
  var links=collectLinks(document.body);
  var refs=links.length;
  var refsRe=__REFSRE__;
  if(refsRe){
    try{
      var m=document.body.innerText.match(new RegExp(refsRe));
      if(m&&parseInt(m[1],10)>refs) refs=parseInt(m[1],10);
    }catch(e){}
  }
  return JSON.stringify({found:true,thinking:'',answer:best,refs:refs,ref_links:links});
})()""".replace("__CANDS__", cand_js).replace("__HOST__", exclude_host) \
        .replace("__NOISE__", noise_js).replace("__REFSRE__", refs_js) \
        .replace("__FAILTEXTS__", fail_js)


METASO_EXTRACT_JS = _modern_extract_js(
    [".markdown-body", "[class*=answer] [class*=markdown]", "[class*=summary]"],
    "metaso.cn",
    noise_patterns=["^\\d{1,2}:\\d{2}$"])  # 视频时间戳行

GROK_EXTRACT_JS = _modern_extract_js(
    ['[class*=response-content-markdown]', ".message-bubble", "[class*=assistant]"],
    "grok.com",
    noise_patterns=[
        "^Worked for\\s", "^Working for\\s", "^Ran \\d+ ", "^Thinking$",
        "^Thought for\\s", "^\\d+ sources?$", "^Searched ", "^Read ",
        "^View ", "^Show ", "^Skip to content$", "^Press .* to skip$",
        "^Get SuperGrok$", "^High Demand$",
        "^Grok is under heavy usage[\\s\\S]{0,120}$",
    ],
    refs_regex="(\\d+)\\s*sources?",
    fail_texts=["under heavy usage"])

PERPLEXITY_EXTRACT_JS = _modern_extract_js(
    ['[data-testid="ai-markdown-result"]', ".prose", "[id*=answer]",
     "[class*=answer] [class*=markdown]"],
    "perplexity.ai")

ZAI_EXTRACT_JS = _modern_extract_js(
    [".chat-assistant", "[class*=markdown-prose]", "[class*=assistant]"],
    "z.ai",
    noise_patterns=["^\\+\\d+$", "^思考过程$", "^正在思考[\\s\\S]{0,10}$"])

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
        "fill_selector": "[contenteditable=true]",
        "fill_nth": 0,
        "input_method": "type",
        "submit": {
            "js_click": "(function(){ var b=document.querySelector('.send-btn-wrapper button'); if(b){b.click();return true;} return false; })()"
        },
        "probe_js": "!!document.querySelector('[contenteditable=true]')",
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
        "submit": {"js_click": "(function(){ var b=document.querySelector('.send-button-container'); if(b){b.click();return true;} return false; })()"},
        "probe_js": "!!document.querySelector('[contenteditable=true]')",
        "extract_js": KIMI_EXTRACT_JS,
    },
    "qianwen": {
        "name": "\u901a\u4e49\u5343\u95ee",
        "icon": "\U0001f388",
        "badge": "\u963f\u91cc\u901a\u4e49\u5168\u7f51\u667a\u641c",
        "session": "qianwen",
        "site_url": "https://www.qianwen.com/",
        "site_host": "qianwen",
        "fill_selector": "[contenteditable=true]",
        "input_method": "type",
        "fill_nth": 0,
        "submit": {"js_click": "(function(){ var b=document.querySelector('button.size-8.border-0'); if(b){b.click();return true;} return false; })()"},
        "probe_js": "!!document.querySelector('[contenteditable=true]')",
        "extract_js": GENERIC_EXTRACT_JS,
    },
    # ---- \u4ee5\u4e0b 4 \u4e2a\u4e3a 2026-08 \u65b0\u589e\uff08\u9009\u62e9\u5668\u5f85\u767b\u5f55\u540e\u73b0\u573a DOM \u63a2\u67e5\u6821\u51c6\uff09----
    "metaso": {
        "name": "\u79d8\u5854AI\u641c\u7d22",
        "icon": "\U0001f52d",
        "badge": "\u65e0\u5e7f\u544a\u76f4\u8fbe\u7ed3\u679c \u00b7 \u5168\u7f51/\u5b66\u672f",
        "session": "metaso",
        "site_url": "https://metaso.cn/",
        "site_host": "metaso.cn",
        "fill_selector": "textarea",
        "fill_nth": 0,
        "input_method": "type",
        # \u53d1\u9001\u7b56\u7565\uff1a\u5148\u8bd5\u5e38\u89c1\u53d1\u9001\u6309\u94ae\uff0c\u627e\u4e0d\u5230\u518d\u56de\u8f66\uff08js_click \u8fd4\u56de false \u4e0d\u5f71\u54cd keys \u515c\u5e95\uff09
        "submit": {
            "js_click": "(function(){ var b=document.querySelector('button[class*=send i],button[aria-label*=send i],button[type=submit]'); if(b&&!b.disabled){b.click();return 'clicked';} return false; })()",
            "keys": "Enter",
        },
        "probe_js": "(function(){return !!(document.querySelector('textarea')||document.querySelector('[contenteditable=true]'));})()",
        "extract_js": METASO_EXTRACT_JS,
        "timeout": 60,
    },
    "grok": {
        "name": "Grok",
        "icon": "\U0001f680",
        "badge": "xAI \u5b9e\u65f6 X \u60c5\u62a5",
        "session": "grok",
        "site_url": "https://grok.com/",
        "site_host": "grok.com",
        # 2026-08-26 \u5b9e\u6d4b\uff1acomposer \u662f tiptap ProseMirror \u7684 contenteditable div
        # \uff08\u9875\u9762\u4e0a\u53e6\u6709\u4e00\u4e2a\u9690\u85cf textarea\uff0c\u4e0d\u80fd\u7528\u4f5c\u8f93\u5165\u76ee\u6807\uff09\uff1b
        # \u539f\u751f keys Enter \u95f4\u6b47\u88ab\u541e\uff08\u95ee\u9898\u7559\u5728\u6846\u91cc\u6ca1\u53d1\u51fa\u53bb\uff09\uff0c\u6539 KeyboardEvent \u6d3e\u53d1 + Submit \u6309\u94ae\u515c\u5e95\uff1b
        # verify \u7528\u300c\u8f93\u5165\u6846\u5df2\u6e05\u7a7a\u300d\u5224\u5b9a\u662f\u5426\u771f\u7684\u53d1\u51fa\uff08\u5931\u8d25\u65f6\u6587\u5b57\u4f1a\u7559\u5728\u6846\u91cc\uff09
        "fill_selector": "[contenteditable=true]",
        "input_method": "fill",
        "submit": {
            "enter_js": "(function(){var el=document.querySelector('[contenteditable=true]');if(!el)return 'no-input';el.focus();el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true,cancelable:true}));return 'ok';})()",
            "js_click": "(function(){var b=document.querySelector('button[aria-label=Submit]');if(b){b.click();return true;}return false;})()",
            "verify_js": "(function(){var el=document.querySelector('[contenteditable=true]');return !el||(el.innerText||'').trim().length<3;})()",
        },
        "probe_js": "(function(){return !!document.querySelector('[contenteditable=true]');})()",
        "extract_js": GROK_EXTRACT_JS,
        "timeout": 90,
    },
    "perplexity": {
        "name": "Perplexity",
        "icon": "\U0001f9ed",
        "badge": "\u82f1\u6587\u4e16\u754c\u6700\u5f3a AI \u641c\u7d22",
        "session": "perplexity",
        "site_url": "https://www.perplexity.ai/",
        "site_host": "perplexity.ai",
        # 2026-08-26 实测：过 Cloudflare 后 composer 是 contenteditable（页面上没有 textarea）
        "fill_selector": "[contenteditable=true]",
        "input_method": "fill",
        "submit": {"keys": "Enter", "keys_always": True},
        "probe_js": "(function(){return !!(document.querySelector('textarea')||document.querySelector('[contenteditable=true]'));})()",
        "extract_js": PERPLEXITY_EXTRACT_JS,
        "timeout": 90,
    },
    "zai": {
        "name": "\u667a\u8c31 Z.ai",
        "icon": "\u2728",
        "badge": "GLM \u5168\u6808 \u00b7 \u4e2d\u82f1\u53cc\u641c",
        "session": "zai",
        "site_url": "https://chat.z.ai/",
        "site_host": "z.ai",
        # 2026-08-26 实测：输入框 id=chat-input（textarea）
        "fill_selector": "#chat-input",
        "fill_nth": 0,
        "input_method": "type",
        # 2026-08-26 实测：opencli 原生 keys Enter 会被 zai 前端吞掉（间歇），
        # 改为 eval 派发 KeyboardEvent keydown，实测可靠；sendMessageButton 仅作兜底
        "submit": {
            "enter_js": "(function(){var el=document.querySelector('#chat-input');if(!el)return 'no-input';el.focus();el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true,cancelable:true}));return 'ok';})()",
            "js_click": "(function(){var b=document.querySelector('.sendMessageButton');if(b){b.click();return true;}return false;})()",
            # 会话是否真的开始：离开首页 hero（URL 变 /c/<id> 或 hero 文案消失）
            "verify_js": "(function(){return location.href.indexOf('/c/')>-1||document.body.innerText.indexOf('我能为你创造什么')<0;})()",
        },
        # 发送前检查：深度思考若在高档位会拖到分钟级超时——检测到就点开下拉关掉；
        # 两段式：先点开下拉，间隔后再点 role=switch 关闭（菜单渲染需要时间）
        "pre_send": [
            "(function(){var els=document.querySelectorAll('button,div[role=button],span');for(var i=0;i<els.length;i++){var t=(els[i].innerText||'').trim();if(/深度思考\\s*(最高|高)/.test(t)){els[i].click();return 'dropdown-opened';}}return 'dt-off';})()",
            "(function(){var sw=document.querySelectorAll('[role=switch]');var n=0;for(var i=0;i<sw.length;i++){if(sw[i].getBoundingClientRect().width>0){sw[i].click();n++;}}if(n){document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));return 'switch-off:'+n;}return 'no-switch';})()",
        ],
        "probe_js": "(function(){return !!(document.querySelector('#chat-input')||document.querySelector('textarea'));})()",
        "extract_js": ZAI_EXTRACT_JS,
        "timeout": 150,
    },
}

ENGINE_ORDER = ["yuanbao", "doubao", "kimi", "qianwen", "metaso", "grok", "perplexity", "zai"]

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
    """调用引擎页面的 extract_js，返回 {found, thinking, answer, answer_html, refs, ref_links}。"""
    r = run_cli(["browser", sess, "eval", eng["extract_js"]], timeout=60)
    if not r["ok"]:
        return {"found": False, "thinking": "", "answer": "", "answer_html": "", "refs": 0, "ref_links": []}
    try:
        data = json.loads(r["stdout"])
        if isinstance(data, dict) and data.get("found"):
            links = data.get("ref_links")
            if not isinstance(links, list):
                links = []
            return {
                "found": True,
                "thinking": data.get("thinking", ""),
                "answer": data.get("answer", ""),
                "answer_html": data.get("answer_html", ""),
                "refs": int(data.get("refs") or 0),
                "ref_links": links,
            }
    except Exception:  # noqa: BLE001
        pass
    return {"found": False, "thinking": "", "answer": "", "answer_html": "", "refs": 0, "ref_links": []}


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


def _is_prompt_echo(answer, prompt):
    """「答案」只是把问题原样回显 → 判为未出答案。
    场景：提交实际没发出去时，页面停留在首页/会话列表，提取器兜底抓到
    输入框文字、侧栏历史标题等家具文本（如 grok 首页 composer 里的原话）。
    规则：完整包含问题原文、且总长不超过 max(120, 问题长度×4)。"""
    p = (prompt or "").strip()
    a = (answer or "").strip()
    if not p or len(p) < 10 or not a:
        return False
    return p in a and len(a) < max(120, 4 * len(p))


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
        if cur["found"] and not _is_prompt_echo(cur.get("answer", ""), prompt):
            baseline_ans = cur.get("answer", "")
            baseline_think = cur.get("thinking", "")

    if progress:
        progress(f"连接 {eng['name']}…")

    # 发送前预处理（如 zai 关深度思考：点开下拉 → 间隔 → 点 switch，两段式执行）
    for pre_js in eng.get("pre_send", []) or []:
        run_cli(["browser", sess, "eval", pre_js], timeout=30)
        time.sleep(1.0)

    input_method = eng.get("input_method", "fill")
    if input_method == "type":
        focus_js = ("(function(){var el=document.querySelector('%s');"
                    "if(el){el.focus();}return true;})()"
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

    def _click_send():
        if sub.get("js_click"):
            run_cli(["browser", sess, "eval", sub["js_click"]], timeout=30)
        elif sub.get("click"):
            run_cli(["browser", sess, "click", sub["click"]], timeout=30)

    submitted = False
    if sub.get("enter_js"):
        # 某些前端（如 zai）对原生 keys Enter 响应不可靠，改 eval 派发 KeyboardEvent；
        # 提交后用 verify_js 确认会话真的开始了，没开始再点发送按钮兜底
        r = run_cli(["browser", sess, "eval", sub["enter_js"]], timeout=30)
        out = r.get("stdout") or ""
        if "no-input" not in out and r.get("ok"):
            if sub.get("verify_js"):
                time.sleep(VERIFY_SUBMIT_DELAY)
                v = run_cli(["browser", sess, "eval", sub["verify_js"]], timeout=30)
                submitted = "true" in (v.get("stdout") or "")
            else:
                submitted = True
        if not submitted:
            _click_send()
    else:
        clicked = False
        if sub.get("js_click"):
            rr = run_cli(["browser", sess, "eval", sub["js_click"]], timeout=30)
            clicked = "false" not in (rr.get("stdout") or "")
        if sub.get("click"):
            run_cli(["browser", sess, "click", sub["click"]], timeout=30)
            clicked = True
        if sub.get("keys") and (not clicked or sub.get("keys_always")):
            run_cli(["browser", sess, "keys", sub["keys"]], timeout=30)

    last = {"found": False, "thinking": "", "answer": "", "answer_html": "", "refs": 0, "ref_links": []}
    prev_len = 0
    stable_count = 0

    # 轮询上限按引擎配置的 timeout 换算（未配置回落到全局默认次数）
    try:
        tmo = int(eng.get("timeout") or 0)
    except (TypeError, ValueError):
        tmo = 0
    poll_max = max(6, tmo // int(EXTRACT_POLL_INTERVAL)) if tmo else EXTRACT_POLL_MAX

    for _ in range(poll_max):
        time.sleep(EXTRACT_POLL_INTERVAL)
        current = extract_answer(sess, eng)
        if current.get("fatal"):
            return {
                "status": "error",
                "answer": current.get("answer", ""),
                "refs": current.get("refs", 0),
                "ref_links": current.get("ref_links", []),
                "error": f"{eng['name']} 上游容量限制（{current['fatal']}）",
                "elapsed": time.time() - t0
            }
        if current["found"] and (current["answer"] or current["thinking"]):
            if _is_prompt_echo(current.get("answer", ""), prompt):
                continue  # 还是问题回显/页面家具，新回答尚未生成
            if current.get("answer") == baseline_ans and current.get("thinking") == baseline_think:
                continue
            # 只要正文 answer 仍是旧回答(baseline 非空)，说明新回答尚未开始生成，
            # 即便 thinking 已变化也不再稳定判定，继续等待新正文出现
            if baseline_ans and current.get("answer") == baseline_ans:
                continue
            curr_len = len(current.get("answer", "")) + len(current.get("thinking", ""))
            if curr_len > prev_len:
                last = current
                prev_len = curr_len
                stable_count = 0
                if progress:
                    progress(f"正在思考与生成回答({curr_len}字)…")
            elif current["answer"]:
                stable_count += 1
                # 仅当正文答案已出现后，连续 2 次轮询（4秒）文本长度无增长，才判定回答完成
                # （避免深度思考类引擎 thinking 与正文之间的间隙导致过早返回）
                if stable_count >= 2:
                    return {
                        "status": "ok",
                        "thinking": last.get("thinking", ""),
                        "answer": last["answer"],
                        "answer_html": last.get("answer_html", ""),
                        "refs": last["refs"],
                        "ref_links": last.get("ref_links", []),
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
            "ref_links": last.get("ref_links", []),
            "error": "",
            "elapsed": time.time() - t0
        }
    return {"status": "timeout", "answer": "", "answer_html": "", "refs": 0, "ref_links": [],
            "error": "等待回答超时（约 90s），可能是页面会话已失效或该站点未登录",
            "elapsed": time.time() - t0}
