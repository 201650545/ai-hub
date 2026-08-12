# -*- coding: utf-8 -*-
"""B站视频嵌入组件 —— 检索 → BV 校验 → iframe 回填
架构依据：06_组件编排器/组件编排器架构设计.md §5
规则卡：06_组件编排器/组件规则卡/video_embed_bilibili.yaml
"""
import random
import re
import html as _html
from pathlib import Path
from urllib.parse import quote

try:
    import httpx
except Exception:  # noqa: BLE001
    httpx = None

try:
    import yaml  # type:ignore
except Exception:  # noqa: BLE001
    yaml = None

# ---------------------------------------------------------------- 常量

BV_RE = re.compile(r"BV[0-9A-Za-z]{10}")

# B站搜索接口（search_type=video 稳定返回 bvid/title/duration）
SEARCH_API = "https://api.bilibili.com/x/web-interface/search/type"
VIDEO_URL_TPL = "https://www.bilibili.com/video/{bv}"

# 儿童课件偏好:时长为 ≤10 分钟、标题含教学关键词
KID_KEYWORDS = ("儿歌", "教学", "动画", "启蒙", "英语", "儿童", "早教",
                "abc", "english", "nursery", "song", "kids", "number", "episode")
MAX_DURATION_S = 600

# 规则卡的搜索结果选择器（保留以备将来页面 HTML 提取使用）
DEFAULT_RESULT_SELECTOR = "a[href*=BV]"

# AI Hub 网关（降级辅助选型；可选，连通失败不影响主流程）
AI_HUB_URL = "http://localhost:3000/v1/chat/completions"
AI_HUB_MODEL = "yuanbao-search"

USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
)

# 页面中出现即判定「不可嵌入 / 已失效」的标记（小写匹配）
UNPLAYABLE_MARKERS = ("视频不见了", "出错了", "该视频已删除", "播放器加载失败",
                      "仅限", "region", "unavailable")


def _ua() -> str:
    return random.choice(USER_AGENTS)


def _clean(s: str) -> str:
    return _html.unescape(s or "").strip()


def _duration_to_s(duration) -> int | None:
    """'MM:SS' 或 'H:MM:SS' → 秒；异常返回 None。"""
    if duration is None:
        return None
    parts = str(duration).split(":")
    try:
        nums = [int(p) for p in parts if p.strip().isdigit()]
        if len(nums) == 2:
            return nums[0] * 60 + nums[1]
        if len(nums) == 3:
            return nums[0] * 3600 + nums[1] * 60 + nums[2]
    except Exception:  # noqa: BLE001
        pass
    return None


def _load_card(rule_card_path: str) -> dict:
    if not rule_card_path or yaml is None:
        return {}
    p = Path(rule_card_path)
    if not p.is_file():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------- 检索

def search_candidates(keyword: str, limit: int = 5, rule_card_path: str = "") -> list:
    """检索 B站视频候选，返回 [{bv, title, duration, duration_s, url}]。

    主路径：规则卡 search_url_tpl 搜索页（公开可访问，返回完整卡片）。
    降级：B站官方搜索 API(需 Cookie，412 风控时自动跳出)。
    结果按儿童内容偏好排序（时长 ≤10 分钟优先、标题含关键词优先）。
    """
    if httpx is None:
        return []
    results = _search_page_html(keyword, limit, rule_card_path)
    if not results:
        results = _search_api(keyword)
    return _sort_kid_preferred(results)[:limit]


def _search_api(keyword: str) -> list:
    """官方 JSON API（风控时可能 412，视为降级通道）。"""
    headers = {"User-Agent": _ua(), "Referer": "https://www.bilibili.com/"}
    try:
        url = f"{SEARCH_API}?search_type=video&keyword={quote(keyword)}"
        r = httpx.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        items = (data.get("data") or {}).get("result") or []
        out = []
        for it in items:
            bv = it.get("bvid") or ""
            if not BV_RE.fullmatch(bv):
                continue
            out.append({
                "bv": bv,
                "title": _clean(it.get("title") or ""),
                "duration": str(it.get("duration") or ""),
                "duration_s": _duration_to_s(it.get("duration")),
                "url": VIDEO_URL_TPL.format(bv=bv),
            })
        return out
    except Exception:  # noqa: BLE001
        return []


def _search_page_html(keyword: str, limit: int, rule_card_path: str) -> list:
    """主路径：规则卡 search_url_tpl 搜索页 HTML，解析视频卡片。
    从卡片提取 BV（稳定）、标题（img alt 属性）、时长（duration span）。
    """
    if httpx is None:
        return []
    card = _load_card(rule_card_path) or {}
    tpl = (card.get("search") or {}).get("search_url_tpl", "")
    if not tpl:
        return []
    try:
        url = tpl.format(keyword=quote(keyword))
        r = httpx.get(url, headers={"User-Agent": _ua(),
                                    "Referer": "https://www.bilibili.com/"},
                      timeout=15)
        text = r.text or ""
        # 候选：收集 (BV, img alt, duration)
        items = []
        # 每张卡通常以 <a href="//www.bilibili.com/video/BV.../ 开始，到 </a> 结束
        card_chunks = re.split(r'(?=<a href="[^"]*?/video/BV[0-9A-Za-z]{10}[/"][^>]*>)', text)
        for chunk in card_chunks:
            bv_m = re.search(r'/video/(BV[0-9A-Za-z]{10})/', chunk)
            if not bv_m:
                continue
            bv = bv_m.group(1)
            # 标题：优先 <img alt="...">
            img_m = re.search(r'<img[^>]*alt="([^"]*)"', chunk)
            title = _clean(img_m.group(1)) if img_m else None
            if not title:
                h_m = re.search(r'info--tit"[^>]*title="([^"]*)"', chunk)
                title = _clean(h_m.group(1)) if h_m else None
            title = title or bv
            dur_m = re.search(r'bili-video-card__stats__duration"[^>]*>([^<]+)<', chunk)
            dur_raw = dur_m.group(1).strip() if dur_m else ""
            items.append({"bv": bv, "title": title, "duration": dur_raw,
                          "duration_s": _duration_to_s(dur_raw) if dur_raw else None,
                          "url": VIDEO_URL_TPL.format(bv=bv)})
            if len(items) >= limit:
                break
        if not items:
            # 兜底：仅 BV
            bvs, seen = set(), []
            for bv in BV_RE.findall(text):
                if bv not in bvs:
                    bvs.add(bv)
                    seen.append({"bv": bv, "title": bv, "duration": "",
                                 "duration_s": None,
                                 "url": VIDEO_URL_TPL.format(bv=bv)})
                if len(seen) >= limit:
                    break
            return seen
        return items
    except Exception:  # noqa: BLE001
        return []


def _sort_kid_preferred(results: list) -> list:
    """儿童内容偏好：标题含关键词优先，其次时长 ≤10min。"""
    def key(r):
        title = (r.get("title") or "").lower()
        kw_hits = sum(1 for k in K_FILTER_KEYS if k in title)
        dur = r.get("duration_s")
        dur_score = 0 if dur is not None and 0 < dur <= MAX_DURATION_S else 1
        return (-kw_hits, dur_score)
    return sorted(results, key=key)


K_FILTER_KEYS = {k.lower() for k in KID_KEYWORDS}

# ---------------------------------------------------------------- 校验与回填


def validate_bv(bv: str) -> bool:
    """校验视频存在且允许嵌入。伪造/404/区域限制/禁止外播 → False。"""
    if not BV_RE.fullmatch(bv or ""):
        return False
    if httpx is None:
        return False
    try:
        r = httpx.get(VIDEO_URL_TPL.format(bv=bv),
                      headers={"User-Agent": _ua(),
                               "Referer": "https://www.bilibili.com/"},
                      timeout=15, follow_redirects=True)
        if r.status_code != 200:
            return False
        text = r.text or ""
        for marker in UNPLAYABLE_MARKERS:
            if marker.lower() in text.lower():
                return False
        return True
    except Exception:  # noqa: BLE001
        return False


def build_iframe(bv: str, rule_card_path: str = "") -> str:
    """按规则卡 embed_tpl 生成响应式 iframe（16:9、autoplay=0、danmaku=0）。"""
    if not BV_RE.fullmatch(bv or ""):
        raise ValueError(f"非法 BV 号: {bv!r}")
    card = _load_card(rule_card_path) or {}
    tpl = card.get("embed_tpl", "")
    if tpl:
        return tpl.format(bv=bv).strip()
    # 架构 §5 兜底模板
    return (
        '<div class="video-slot" style="position:relative;width:100%;'
        'aspect-ratio:16/9;">'
        '<iframe src="//player.bilibili.com/player.html?bvid=' + bv +
        '&page=1&high_quality=1&danmaku=0&autoplay=0" '
        'scrolling="no" border="0" frameborder="no" framespacing="0" '
        'allowfullscreen="true" '
        'style="position:absolute;inset:0;width:100%;height:100%;">'
        '</iframe></div>')


def _ai_search_fallback(keyword: str) -> dict:
    """降级：AI Hub 网关 AI 搜索引擎辅助选型（§5 降级）。"""
    if httpx is None:
        return {"ok": False, "error": "无检索结果 且 httpx 不可用"}
    try:
        r = httpx.post(AI_HUB_URL,
                       json={"model": AI_HUB_MODEL,
                             "messages": [{"role": "user",
                                           "content":
                                               f"请提供 B站上关于『{keyword}』"
                                               f"适合课堂的短教学/儿歌视频的 BV 号"}],
                             "stream": False},
                       timeout=25)
        if r.status_code == 200:
            data = r.json()
            text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            bv = BV_RE.search(text or "")
            if bv:
                return {"ok": True, "bv": bv.group(0),
                        "error": f"AI 辅助选型 {bv.group(0)}"}
            return {"ok": False, "error": "AI 搜索无可用 BV"}
        return {"ok": False, "error": f"AI 搜索网关 HTTP {r.status_code}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"AI 搜索不可用: {e}"}


def run(slot: dict, rule_card_path: str = "") -> dict:
    """按槽位 keyword：检索候选 → 逐个 validate_bv → iframe 回填。

    返回值契约（task_014）：{"ok", "asset"(iframe)|None, "bv", "error"}。
    """
    keyword = (slot.get("keyword") or "").strip()
    if not keyword:
        return {"ok": False, "asset": None, "bv": None, "error": "槽位缺少 keyword"}

    candidates = search_candidates(keyword, limit=5, rule_card_path=rule_card_path)
    if not candidates:
        fallback = _ai_search_fallback(keyword)
        return {"ok": False, "asset": None, "bv": None, "error": fallback["error"]}

    tried = []
    for cand in candidates:
        bv = cand["bv"]
        if bv in tried:
            continue
        tried.append(bv)
        if not validate_bv(bv):
            continue
        iframe = build_iframe(bv, rule_card_path)
        return {"ok": True, "asset": iframe, "bv": bv, "error": ""}

    return {"ok": False, "asset": None, "bv": None,
            "error": f"候选均不可嵌入: {tried[:3]}"}