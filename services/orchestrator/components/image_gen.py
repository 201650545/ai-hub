# -*- coding: utf-8 -*-
"""
图片生成组件 (image_gen) —— 组件编排器核心适配器
通过 opencli 自动控制浏览器生图站点、注入提示词、轮询等待、提取下载图片到指定课时文件夹。
遵守规范：
1. opencli 直调 (_NODE + _OPENCLI_SCRIPT)
2. JS 注入只用单引号，替换换行为空格
3. React 受控输入采用 type 方式
4. 会话隔离命名 (*_image)
5. 支持 fallback 重试与备用站点切换
"""

import base64
import glob
import json
import os
import subprocess
import time
import urllib.request
import yaml

_NODE = "D:/Program Files/nodejs/node.exe"
_OPENCLI_SCRIPT = "C:/Users/郭永涛/AppData/Roaming/npm/node_modules/@jackwener/opencli/dist/src/main.js"
# 规则卡目录（monorepo：services/orchestrator/rules/）
RULE_CARD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rules")

def run_cli(args, timeout=90):
    """底层 opencli 执行器"""
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
    except Exception as e:
        return {"ok": False, "code": -2, "stdout": "", "stderr": str(e)}

def _js_quote(s: str) -> str:
    """用 json.dumps 安全生成 JS 字符串字面量（处理单引号/双引号/换行/反斜杠）。"""
    return json.dumps(s, ensure_ascii=True)

def load_card(rule_card_path: str) -> dict:
    """加载 yaml 规则卡"""
    if not os.path.exists(rule_card_path):
        card_name = os.path.basename(rule_card_path)
        rule_card_path = os.path.join(RULE_CARD_DIR, card_name)
    with open(rule_card_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def list_sites() -> list:
    """扫描规则卡目录，返回可用站点列表（供 fallback 排序）"""
    cards = []
    pattern = os.path.join(RULE_CARD_DIR, "image_gen_*.yaml")
    for file_path in glob.glob(pattern):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                c = yaml.safe_load(f)
                if c and c.get("component") == "image_gen":
                    cards.append({
                        "path": file_path,
                        "site": c.get("site", "未知"),
                        "session": c.get("session", "image_session"),
                        "url": c.get("url", "")
                    })
        except Exception:
            pass
    return cards

def inject_and_generate(session: str, url: str, prompt: str, card: dict) -> bool:
    """打开站点 → 注入提示词 → 提交 → 轮询至出现「新图」或超时。

    基线感知：提交前记录结果区 img 数量与末张 src；轮询改为等待
    数量增加或末张 src 变化，避免同一页面多槽位时旧图命中即返回。
    """
    inj = card.get("inject", {})
    wait_cfg = card.get("wait", {})
    ext_cfg = card.get("extract", {})
    fill_selector = inj.get("fill_selector", "textarea")
    input_method = inj.get("input_method", "type")
    submit = inj.get("submit", "keys:Enter")
    pre_actions = inj.get("pre_actions", []) or []
    fill_nth = int(inj.get("fill_nth", 0) or 0)
    timeout_s = wait_cfg.get("timeout_s", 90)
    poll_js = wait_cfg.get("poll_js", "!!document.querySelector('img')")
    selector = ext_cfg.get("selector", "img")

    # 1. 确保打开页面
    if url:
        open_res = run_cli(["browser", session, "open", url], timeout=40)
        time.sleep(2)
        if "chatgpt_mirror" in session or "vip" in url:
            run_cli(["browser", session, "bind"], timeout=20)
            time.sleep(1)

    # 1.5 执行 pre_actions（如 Gemini 点模型选择器 + 选模型）
    for pa in pre_actions:
        pa_act = pa.get("action", "")
        pa_sel = pa.get("selector", "")
        if not pa_sel:
            continue
        if pa_act == "click_model_picker":
            js = ('(function(){'
                  ' var el = document.querySelector(%s);'
                  ' if(el){ el.click(); return "clicked"; }'
                  ' return "not found";'
                  '})()') % _js_quote(pa_sel)
            run_cli(["browser", session, "eval", js], timeout=15)
            time.sleep(1.5)
        elif pa_act == "select_model":
            model_text = pa.get("text", "3.6 Flash")
            js = ('(function(){'
                  ' var items = document.querySelectorAll(%s);'
                  ' for(var i=0;i<items.length;i++){'
                  '   if(items[i].innerText.includes(%s)){ items[i].click(); return "clicked"; }'
                  ' }'
                  ' return "not found";'
                  '})()') % (_js_quote(pa_sel), _js_quote(model_text))
            run_cli(["browser", session, "eval", js], timeout=15)
            time.sleep(1)
        else:
            js = ('(function(){'
                  ' var el = document.querySelector(%s);'
                  ' if(el){ el.click(); return "clicked"; }'
                  ' return "not found";'
                  '})()') % _js_quote(pa_sel)
            run_cli(["browser", session, "eval", js], timeout=15)
            time.sleep(1)

    # 2. 注入提示词
    if input_method == "type":
        focus_js = ("(function(){ var el = document.querySelector(%s);"
                    " if(el){ el.focus(); document.execCommand('selectAll',false,null);"
                    " document.execCommand('insertText',false,''); } return !!el; })()") % _js_quote(fill_selector)
        run_cli(["browser", session, "eval", focus_js], timeout=15)
        type_res = run_cli(["browser", session, "type", fill_selector, prompt], timeout=40)
        if not type_res["ok"]:
            insert_js = ("(function(){ var el = document.querySelector(%s);"
                         " if(!el) return false; el.focus();"
                         " document.execCommand('insertText',false,%s);"
                         " return true; })()") % (_js_quote(fill_selector), _js_quote(prompt))
            run_cli(["browser", session, "eval", insert_js], timeout=15)
    elif input_method == "react_input":
        react_js = ("(function(){ var el = document.querySelector(%s);"
                    " if(!el) return false; el.focus();"
                    " var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;"
                    " nativeSetter.call(el, %s);"
                    " el.dispatchEvent(new Event('input', { bubbles: true }));"
                    " el.dispatchEvent(new Event('change', { bubbles: true }));"
                    " return true; })()") % (_js_quote(fill_selector), _js_quote(prompt))
        run_cli(["browser", session, "eval", react_js], timeout=20)
    elif input_method == "shadow_p_inject":
        # 穿透 Shadow DOM 找到 contenteditable 输入框，execCommand 注入
        # 注意：execCommand('insertText') 不触发 React 合成事件，须补发 input/change
        shadow_js = (
            "(function(){"
            " function deepCE(root){"
            "   var els = Array.from(root.querySelectorAll('[contenteditable=true]'));"
            "   if(els.length) return els[%d];"
            "   for(var i=0;i<root.children.length;i++){"
            "     var c=root.children[i];"
            "     if(c.shadowRoot){ var f=deepCE(c.shadowRoot); if(f) return f; }"
            "   }"
            "   return null;"
            " }"
            " var ta=deepCE(document);"
            " if(!ta) return false;"
            " ta.focus();"
            " document.execCommand('selectAll',false,null);"
            " document.execCommand('insertText',false,%s);"
            " ta.dispatchEvent(new Event('input',{bubbles:true}));"
            " ta.dispatchEvent(new Event('change',{bubbles:true}));"
            " return true;"
            "})()"
        ) % (fill_nth, _js_quote(prompt))
        run_cli(["browser", session, "eval", shadow_js], timeout=20)
    else:
        run_cli(["browser", session, "fill", fill_selector, prompt], timeout=30)

    time.sleep(1)

    # 基线：提交前结果区图片数量与末张 src（穿透 Shadow DOM）
    _DEEP_Q_JS = (
        "function deepQSA(root,sel){"
        " var out=Array.from(root.querySelectorAll(sel));"
        " for(var i=0;i<root.children.length;i++){"
        "   var c=root.children[i];"
        "   if(c.shadowRoot){ Array.prototype.push.apply(out,deepQSA(c.shadowRoot,sel)); }"
        " }"
        " return out;"
        "}"
    )
    safe_sel = _js_quote(selector)
    base_js = ("(function(){%s"
               "var imgs=deepQSA(document,%s);"
               "var last=imgs.length?imgs[imgs.length-1].src||'':'';"
               "return JSON.stringify({n:imgs.length,s:last});})()") % (_DEEP_Q_JS, safe_sel)
    base_res = run_cli(["browser", session, "eval", base_js], timeout=15)
    base_n, base_src = 0, ""
    if base_res["ok"]:
        try:
            snap = json.loads(base_res["stdout"].strip())
            base_n, base_src = int(snap.get("n", 0)), str(snap.get("s", ""))
        except Exception:  # noqa: BLE001
            pass

    # 3. 提交生成
    if submit == "keys:Enter":
        run_cli(["browser", session, "keys", "Enter"], timeout=15)
    elif isinstance(submit, str) and submit.startswith("js_click:"):
        js_click = submit.split("js_click:", 1)[1]
        run_cli(["browser", session, "eval", js_click], timeout=15)
    elif isinstance(submit, str) and submit.startswith("click:"):
        sel = submit.split("click:", 1)[1]
        js_click = ('(function(){ var el=document.querySelector(%s);'
                    ' if(el){ el.click(); return "clicked"; } return "not found"; })()') % _js_quote(sel)
        run_cli(["browser", session, "eval", js_click], timeout=15)
    else:
        run_cli(["browser", session, "keys", "Enter"], timeout=15)

    # 4. 轮询等待「新图」出现（数量增加或末张 src 变化，穿透 Shadow DOM）
    poll_js_deep = ("(function(){%s"
                    "var imgs=deepQSA(document,%s);"
                    "return JSON.stringify({n:imgs.length,s:imgs.length?imgs[imgs.length-1].src||'':''});})()"
                    ) % (_DEEP_Q_JS, safe_sel)
    poll_start = time.time()
    while time.time() - poll_start < timeout_s:
        time.sleep(2.5)
        cur_res = run_cli(["browser", session, "eval", poll_js_deep], timeout=15)
        if not cur_res["ok"]:
            continue
        cur_n, cur_src = 0, ""
        try:
            snap = json.loads(cur_res["stdout"].strip())
            cur_n, cur_src = int(snap.get("n", 0)), str(snap.get("s", ""))
        except Exception:  # noqa: BLE001
            continue
        if cur_n and (cur_n > base_n or (cur_n == base_n and cur_src not in ("", base_src))):
            # 额外等 1 秒让图稳定，避免未渲染完整即提取
            time.sleep(1)
            return True
        # 兜底：规则卡自带 poll_js 命中也算（兼容旧卡）
        legacy = run_cli(["browser", session, "eval", poll_js], timeout=10)
        if legacy["ok"] and legacy["stdout"].strip() == "true":
            return True

    return False

def extract_image(session: str, card: dict, save_path: str) -> bool:
    """提取图片：支持 img_src 直链下载与 blob_canvas 转 dataURL 保存"""
    ext_cfg = card.get("extract", {})
    method = ext_cfg.get("method", "img_src")
    selector = ext_cfg.get("selector", "img")
    prefer_last = ext_cfg.get("prefer_last", True)

    if method == "blob_canvas":
        # 递归穿透 Shadow DOM 找图，canvas 转 dataURL（兼容 Gemini 的 <generated-image> shadow DOM）
        canvas_js = (
            "(function(){"
            " function deepQSA(root, sel){"
            "   var out = Array.from(root.querySelectorAll(sel));"
            "   for(var i=0;i<root.children.length;i++){"
            "     var c=root.children[i];"
            "     if(c.shadowRoot){ Array.prototype.push.apply(out, deepQSA(c.shadowRoot, sel)); }"
            "   }"
            "   return out;"
            " }"
            " var imgs = deepQSA(document, %s);"
            " if (!imgs.length) return '';"
            " var img = %s;"
            " var canvas = document.createElement('canvas');"
            " canvas.width = img.naturalWidth || img.width || 512;"
            " canvas.height = img.naturalHeight || img.height || 512;"
            " var ctx = canvas.getContext('2d');"
            " ctx.drawImage(img, 0, 0);"
            " return canvas.toDataURL('image/png');"
            "})()"
        ) % (_js_quote(selector), "imgs[imgs.length - 1]" if prefer_last else "imgs[0]")
        res = run_cli(["browser", session, "eval", canvas_js], timeout=20)
        data_url = res["stdout"].strip().strip('"')
        if data_url.startswith("data:image"):
            header, encoded = data_url.split(",", 1)
            data = base64.b64decode(encoded)
            with open(save_path, "wb") as f:
                f.write(data)
            return True

    # 默认 img_src 直链提取
    ext_js = ("(function(){"
              " var imgs = Array.from(document.querySelectorAll(%s));"
              " if (!imgs.length) return '';"
              " var img = %s;"
              " return img.src || '';"
              "})()") % (_js_quote(selector), "imgs[imgs.length - 1]" if prefer_last else "imgs[0]")

    res = run_cli(["browser", session, "eval", ext_js], timeout=15)
    img_url = res["stdout"].strip().strip('"').strip("'")

    if img_url:
        if img_url.startswith("data:image"):
            header, encoded = img_url.split(",", 1)
            data = base64.b64decode(encoded)
            with open(save_path, "wb") as f:
                f.write(data)
            return True
        elif img_url.startswith("http"):
            req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp, open(save_path, "wb") as f:
                f.write(resp.read())
            return True

    return False

def run(slot: dict, rule_card_path: str, lesson_dir: str | None = None) -> dict:
    """
    槽位填充入口函数（兼容组件编排器两参数契约）：
    slot: {id, topic, prompt, mode=download, lesson_dir?}
    rule_card_path: 规则卡路径
    lesson_dir: 资产保存的课时目录（可选；编排器会注入 slot["lesson_dir"]）
    """
    slot_id = slot.get("id", f"img_{int(time.time())}")
    base_prompt = slot.get("prompt", slot.get("topic", "picture"))
    lesson_dir = lesson_dir or slot.get("lesson_dir") \
        or os.path.dirname(RULE_CARD_DIR)
    os.makedirs(lesson_dir, exist_ok=True)
    save_path = os.path.join(lesson_dir, f"{slot_id}.png")

    card = load_card(rule_card_path)
    site_name = card.get("site", "AI生图")
    # 会话按槽位隔离：同页多槽位复用会导致 poll 命中旧图、prefer_last 取到同一张
    base_session = card.get("session", f"{slot_id}_image")
    session = f"{base_session}_{slot_id}" if slot_id not in base_session else base_session
    url = card.get("url", "")
    style_lock = card.get("style_lock", "")
    full_prompt = f"{base_prompt}, {style_lock}" if style_lock else base_prompt

    max_retry = card.get("budget", {}).get("max_retry", 2)

    # 1. 尝试主站点生成
    for attempt in range(max_retry + 1):
        clean_prompt = full_prompt if attempt == 0 else f"{base_prompt}, simple cartoon style"
        print(f"[{site_name}] 正在生成槽位 {slot_id} (尝试 {attempt+1}/{max_retry+1})...")
        gen_ok = inject_and_generate(session, url, clean_prompt, card)
        if gen_ok:
            ext_ok = extract_image(session, card, save_path)
            if ext_ok and os.path.exists(save_path) and os.path.getsize(save_path) > 100:
                return {
                    "ok": True,
                    "asset": f"{slot_id}.png",
                    "site": site_name,
                    "path": save_path,
                    "error": None
                }

    # 2. 触发 Fallback 备用站点
    print(f"[{site_name}] 主站点生成失败，尝试 Fallback 备用站点...")
    available_sites = list_sites()
    for fallback_card_info in available_sites:
        if fallback_card_info["site"] == site_name:
            continue
        try:
            fb_card = load_card(fallback_card_info["path"])
            fb_site = fb_card.get("site", "备用生图")
            fb_session = fb_card.get("session", "fallback_image")
            if slot_id not in fb_session:
                fb_session = f"fallback_{slot_id}"
            fb_url = fb_card.get("url", "")
            print(f"[Fallback 切换] -> {fb_site}...")
            fb_gen = inject_and_generate(fb_session, fb_url, full_prompt, fb_card)
            if fb_gen:
                fb_ext = extract_image(fb_session, fb_card, save_path)
                if fb_ext and os.path.exists(save_path) and os.path.getsize(save_path) > 100:
                    return {
                        "ok": True,
                        "asset": f"{slot_id}.png",
                        "site": fb_site,
                        "path": save_path,
                        "error": None
                    }
        except Exception as e:
            print(f"Fallback 站点 {fallback_card_info['site']} 出错: {e}")

    return {
        "ok": False,
        "asset": None,
        "site": site_name,
        "path": None,
        "error": "所有生图站点生成/提取均超时或失败"
    }

if __name__ == "__main__":
    test_slot = {
        "id": "p12_market_test",
        "topic": "超市场景对话",
        "prompt": "A bright supermarket aisle with colorful apples, flat cartoon style",
        "mode": "download"
    }
    card_p = os.path.join(RULE_CARD_DIR, "image_gen_zhipu.yaml")
    target_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_output")
    print("Testing image_gen.py adapter...")
    res = run(test_slot, card_p, target_dir)
    print("Run Result:", json.dumps(res, ensure_ascii=False, indent=2))
