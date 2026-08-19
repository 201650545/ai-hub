# -*- coding: utf-8 -*-
"""content_pool.py - 多 AI 搜索内容聚合交付"""
import json, threading, datetime
import urllib.request
from pathlib import Path
import engines

BASE_DIR = Path(__file__).resolve().parent
RUNS_DIR = BASE_DIR / "runs"

def _run_id():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

def _esc(s):
    if not s: return ""
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace(chr(34),"&quot;")

def _md(text):
    if not text: return ""
    out=[]; in_code=False
    for line in str(text).splitlines():
        ls=line.strip()
        if ls.startswith("```"): in_code=not in_code; continue
        if in_code: out.append("<pre>"+_esc(line)+"</pre>")
        elif ls.startswith("## "): out.append("<h3>"+_esc(ls[3:])+"</h3>")
        elif ls.startswith("### "): out.append("<h4>"+_esc(ls[4:])+"</h4>")
        elif ls.startswith("- "): out.append("<li>"+_esc(ls[2:])+"</li>")
        elif ls=="": out.append("")
        else: out.append("<p>"+_esc(line)+"</p>")
    return "\n".join(out)
CSS = "".join([
    "body{font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display','PingFang SC','Microsoft YaHei',sans-serif;background:#f5f5f7;color:#1d1d1f;line-height:1.7;margin:0;padding:32px 16px}",
    ".wrap{max-width:860px;margin:0 auto}",
    "header{background:#fff;border:1px solid #d2d2d7;border-radius:18px;padding:28px 32px;margin-bottom:20px;box-shadow:0 1px 2px rgba(0,0,0,.04)}",
    "h1{font-size:28px;font-weight:700;letter-spacing:-.02em;margin:0 0 8px}",
    ".q{color:#6e6e73;font-size:16px}",
    ".meta-sm{color:#86868b;font-size:12px;margin-top:6px}",
    ".card{background:#fff;border:1px solid #d2d2d7;border-radius:18px;padding:24px 28px;margin-bottom:16px;box-shadow:0 1px 2px rgba(0,0,0,.04)}",
    ".card h2{font-size:18px;font-weight:600;margin:0 0 12px;padding-bottom:10px;border-bottom:1px solid #e8e8ed;color:#1d1d1f}",
    ".meta{font-size:12px;color:#86868b;font-weight:normal;margin-left:8px}",
    ".answer p{margin:8px 0;font-size:15px}.answer h3{margin:14px 0 6px;font-size:16px}.answer pre{background:#f5f5f7;border:1px solid #e8e8ed;border-radius:10px;padding:12px;overflow-x:auto;font-size:13px}.answer li{margin-left:20px;font-size:15px}",
    "details.think{margin:10px 0;padding:12px 16px;background:#f5f5f7;border-radius:12px}",
    "details.think summary{cursor:pointer;color:#6e6e73;font-size:13px;font-weight:500}",
    ".toolbar{position:fixed;right:20px;bottom:20px;display:flex;gap:8px}",
    ".toolbar button{background:#0071e3;color:#fff;border:none;border-radius:999px;padding:9px 18px;cursor:pointer;font-size:13px;font-weight:500;transition:opacity .15s}",
    ".toolbar button:hover{opacity:.85}",
    "footer{color:#86868b;font-size:12px;text-align:center;margin:28px 0;border-top:1px solid #e8e8ed;padding-top:20px}",
])

def _llm_summarize(question, merged):
    """调网关 LLM 转发 API，把各引擎内容整理成一段综合结论（2026-08-15）。
    用本机 :3000 的 /v1/chat/completions（DeepSeek 等渠道）；失败返回空串（不阻塞报告）。"""
    ok = [r for r in merged if r.get("status") == "ok" and (r.get("answer") or r.get("thinking"))]
    if not ok:
        return ""
    parts = []
    for r in ok:
        txt = (r.get("answer") or r.get("thinking") or "")[:1500]
        parts.append("【" + (r.get("name") or r.get("provider") or "") + "】\n" + txt)
    contents = "\n\n".join(parts)
    prompt = ("以下是多个 AI 搜索引擎对同一个问题的回答。请综合它们，输出一段有条理的中文总结"
              "（先给结论，再列各来源要点，标注共识与差异；300 字以内）：\n\n问题：" + question + "\n\n" + contents)
    payload = {
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 800,
    }
    req = urllib.request.Request(
        "http://127.0.0.1:3100/v1/chat/completions",  # 走 API 转发网关(OpenAI 兼容)。:3000 是搜索网关只认 yuanbao-search，会拒 deepseek-v4-flash
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8", "ignore"))
        return (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    except Exception as e:
        print("[content_pool] LLM summarize failed: " + str(e)[:200])
        return ""


def _build_report(run_id, question, merged, summary=None):
    cards=[]
    if summary:
        cards.append("<section class=card style='border-left:3px solid #0071e3'><h2>综合整理</h2><div class=answer>"+_md(summary)+"</div></section>")
    for r in merged:
        if r.get("status")=="ok":
            body=_md(r.get("answer") or r.get("thinking") or "") or "<p style=color:#999>（无有效内容）</p>"
            think=""
            if r.get("thinking"):
                think="<details class=think><summary>思考过程</summary>"+_md(r["thinking"])+"</details>"
            name=_esc(r.get("name") or r.get("provider") or "")
            icon=_esc(r.get("icon") or "")
            el=round(r.get("elapsed") or 0,1)
            rf=r.get("refs") or 0
            cards.append("<section class=card><h2>"+icon+" "+name+" <span class=meta>"+str(el)+"s · 引用 "+str(rf)+"</span></h2>"+think+"<div class=answer>"+body+"</div></section>")
        else:
            name=_esc(r.get("name") or r.get("provider") or "")
            icon=_esc(r.get("icon") or "")
            st=r.get("status") or "error"
            err=_esc(r.get("error") or "")
            cards.append("<section class=card style=opacity:.6><h2>"+icon+" "+name+" <span class=meta>"+st+"</span></h2><div class=answer><p style=color:#b00>未返回内容："+err+"</p></div></section>")
    cards_html="\n".join(cards)
    q=_esc(question); rid=_esc(run_id); n=len(merged)
    return "".join([
        "<!DOCTYPE html><html lang=zh-CN><head><meta charset=utf-8><meta name=viewport content=width=device-width,initial-scale=1>",
        "<title>AI 搜索聚合报告 · "+rid+"</title><style>"+CSS+"</style></head><body><div class=wrap>",
        "<header><h1>AI 搜索聚合报告</h1><div class=q>问题："+q+"</div>",
        "<div class=q style=margin-top:6px;font-size:12px;color:#999>"+rid+" · "+str(n)+" 个引擎返回</div></header>",
        cards_html,
        "<footer>由 content_pool 自动生成</footer></div>",
        "<div class=toolbar><button onclick=window.print()>打印 / PDF</button><button onclick=window.scrollTo(0,0)>返回顶部</button></div>",
        "</body></html>",
    ])
def run_search(question, engine_ids=None):
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_id=_run_id()
    run_dir=RUNS_DIR/run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir/"question.txt").write_text(question, encoding="utf-8")
    engine_ids = engine_ids or ["yuanbao","doubao","kimi","qianwen"]
    results={}
    def _one(eid):
        try: results[eid]=engines.ask_engine(eid, question)
        except Exception as e: results[eid]={"status":"error","answer":"","refs":0,"error":str(e)[:120],"elapsed":0}
    threads=[threading.Thread(target=_one,args=(eid,),daemon=True) for eid in engine_ids]
    for t in threads: t.start()
    for t in threads: t.join(timeout=150)
    records=[]
    for eid in engine_ids:
        r=results.get(eid,{})
        name=engines.ENGINES.get(eid,{}).get("name",eid)
        icon=engines.ENGINES.get(eid,{}).get("icon","")
        records.append({"provider":eid,"name":name,"icon":icon,"status":r.get("status","error"),
            "thinking":r.get("thinking",""),"answer":r.get("answer",""),"answer_html":r.get("answer_html",""),
            "refs":r.get("refs",0),"elapsed":r.get("elapsed",0),"error":r.get("error","")})
    with open(run_dir/"raw.jsonl","a",encoding="utf-8") as f:
        for rec in records: f.write(json.dumps(rec,ensure_ascii=False)+"\n")
    merged={}
    for r in records:
        merged[r["provider"]]=r
    merged_list=list(merged.values())
    (run_dir/"merged.json").write_text(json.dumps(merged_list,ensure_ascii=False,indent=2),encoding="utf-8")
    summary=_llm_summarize(question, merged_list)
    (run_dir/"summary.md").write_text(summary or "（无综合结论）",encoding="utf-8")
    report_path=run_dir/"report.html"
    report_path.write_text(_build_report(run_id, question, merged_list, summary),encoding="utf-8")
    return run_id, str(report_path), records

if __name__=="__main__":
    import sys
    q=" ".join(sys.argv[1:]) or "中国近期的 AI 政策动态"
    rid, rp, recs = run_search(q)
    print("RUN:", rid)
    print("REPORT:", rp)
    for r in recs: print(" ", r["provider"], r["status"], round(r.get("elapsed",0),1))