# 高级 AI 问诊包：ai-resource-hub 资源清单雏形（子项目①）

> 生成时间：2026-08-11 ｜ 问诊对象：ChatGPT / Claude Sonnet
> 用途：请高级 AI 审阅这个雏形的架构与实现，指出优化空间与风险。

---

## 一、目标与背景

我们正在做一个 **ai-resource-hub 资源体系** 的"基本雏形"，第一个子项目是「资源表 + GitHub 打通」。数据链路：

```
飞书多维表格 → 数据桥构建 → GitHub Pages 公开产物 → 门户 /api/resources → Dashboard 展示
```

- **数据桥**（已上线，不动）：`https://201650545.github.io/ai-resource-hub/`，公开 JSON 产物：
  - `index.json` —— 元信息（build_id、generated_at、freshness 规则）
  - `capabilities.json` —— 21 条能力规格（字段：`capability_id`、`资源名称`、`类别`、`逻辑模型`、`质量等级`、`调用方式`、`adapter_id`、`协议版本`、`模型族`）
  - `instances.json` —— 21 条实例清单（字段：`instance_id`、`平台`、`实际模型名`、`重置规则`、`所属能力`、`额度状态`）
- **门户**：本机 FastAPI 中央平台（`:8000`），Dashboard 里新增了一个「资源清单」Tab 展示上述数据。
- 数据桥 GitHub 仓库：`https://github.com/201650545/ai-resource-hub`（只读参考，本次不修改它）。

## 二、本次改动清单（请审阅的核心）

| 文件 | 改动 |
|---|---|
| `resources_bridge.py`（新增） | 后端代理模块：线上优先 + 本地 `public/` 原子回退 + 300s 进程内缓存 |
| `server.py` | 加 `import resources_bridge` + `GET /api/resources?source=auto/remote/local` |
| `dashboard/index.html` | 侧栏加「资源清单」按钮 + `#tab-resources` section（4 统计卡 + 2 张表） |
| `dashboard/app.js` | 加 `fetchResources/renderResources/renderResourcesError` + 2 个语义色映射 |
| `dashboard/styles.css` | 加 `.badge.warning/.danger/.info` 三个语义色 |

## 三、完整代码（供审阅）

### 3.1 `resources_bridge.py`（后端代理模块，全文）

```python
# -*- coding: utf-8 -*-
"""
ai-resource-hub 公开数据桥代理（子项目①雏形）
================================================
链路: 飞书表 → 数据桥构建 → GitHub Pages → 门户 /api/resources

数据源优先级:
  1. 线上 GitHub Pages（https://201650545.github.io/ai-resource-hub）
  2. 本地 public/ 产物原子回退（本地 D:/项目/ai-resource-hub/public）

回退策略: 全有或全无——3 个文件（index/capabilities/instances）任一拉取失败，
即整体回退本地，避免混搭不同 build_id 的 index 与 capabilities。

缓存: 进程内模块级 TTL 缓存（300s），dashbboard 反复切 Tab/点刷新不打爆 GitHub Pages。
雏形只做「读」，不做任何写；数据桥公开产物无凭证。

依赖: pip install httpx
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

REMOTE_BASE = "https://201650545.github.io/ai-resource-hub"
FILES = ["index.json", "capabilities.json", "instances.json"]
LOCAL_DIR = Path(__file__).parent.parent / "ai-resource-hub" / "public"  # D:\项目\ai-resource-hub\public
CACHE_TTL = 300  # 秒

_CACHE = {"ts": 0.0, "data": None}


def _load_local():
    """读取本地 public/ 产物，缺失或解析失败返回 None（全有或全无由调用方判断）。"""
    out = {}
    for name in FILES:
        try:
            with open(LOCAL_DIR / name, "r", encoding="utf-8") as f:
                out[name] = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            out[name] = None
    return out


async def _fetch_remote():
    """并发拉取线上 3 个 JSON，失败项置 None。"""
    async with httpx.AsyncClient(timeout=httpx.Timeout(8.0), follow_redirects=True) as client:
        async def _get(name):
            try:
                r = await client.get(f"{REMOTE_BASE}/{name}")
                return (name, r.json()) if r.status_code == 200 else (name, None)
            except Exception:  # noqa: BLE001 —— 网络/解析失败统一按缺失处理
                return (name, None)
        return dict(await asyncio.gather(*(_get(name) for name in FILES)))


def _is_fresh(index):
    """由 generated_at 对照 stale_after_hours 判断新鲜度；解析失败返回 None（前端显示未知）。"""
    try:
        gen = datetime.fromisoformat(index.get("generated_at", ""))
        hours = float(index.get("freshness", {}).get("stale_after_hours", 48))
        age = (datetime.now(timezone.utc) - gen.astimezone(timezone.utc)).total_seconds()
        return age <= hours * 3600  # True=新鲜 False=已陈旧 None=未知
    except Exception:  # noqa: BLE001
        return None


def _aggregate(index, caps, insts, source):
    return {
        "ok": True,
        "source": source,  # "remote" | "local"
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "meta": {
            "site": index.get("site", ""),
            "repo": index.get("repo", ""),
            "bridge_version": index.get("bridge_version"),
            "build_id": index.get("build_id"),
            "generated_at": index.get("generated_at", ""),
            "stale_after_hours": index.get("freshness", {}).get("stale_after_hours"),
            "fresh": _is_fresh(index),  # True=新鲜 False=已陈旧 None=未知
            "note": index.get("note", ""),
        },
        "counts": {"capabilities": len(caps or []), "instances": len(insts or [])},
        "capabilities": caps or [],
        "instances": insts or [],
    }


async def get_resources(source="auto"):
    """返回聚合后的资源清单。

    source:
      - auto   （默认）线上优先 + 300s 缓存，线上不可用回退本地
      - remote （强制线上，不走缓存；验证/切换钩子）
      - local  （强制本地；验证回退路径）
    """
    if source == "remote":
        files = await _fetch_remote()
        if all(files.values()):
            return _aggregate(files["index.json"], files["capabilities.json"], files["instances.json"], "remote")
        return {"ok": False, "error": "远程数据桥不可用", "source": "remote"}

    if source == "local":
        files = _load_local()
        if all(files.values()):
            return _aggregate(files["index.json"], files["capabilities.json"], files["instances.json"], "local")
        return {"ok": False, "error": "本地 public 产物缺失", "source": "local"}

    # auto
    if _CACHE["data"] and time.time() - _CACHE["ts"] < CACHE_TTL:
        return _CACHE["data"]

    files = await _fetch_remote()
    if all(files.values()):
        data = _aggregate(files["index.json"], files["capabilities.json"], files["instances.json"], "remote")
        _CACHE["ts"], _CACHE["data"] = time.time(), data
        return data

    # 原子回退本地
    files = _load_local()
    if all(files.values()):
        return _aggregate(files["index.json"], files["capabilities.json"], files["instances.json"], "local")
    return {"ok": False, "error": "远程与本地数据桥均不可用", "source": "auto"}
```

### 3.2 `server.py`（新增端点）

```python
# ---------------------------------------------------------------- 资源清单（ai-resource-hub 数据桥）

import resources_bridge

@app.get("/api/resources")
async def api_resources(source: str = "auto"):
    """ai-resource-hub 公开数据桥代理：能力清单 + 实例清单（线上优先，本地回退）。"""
    return await resources_bridge.get_resources(source)
```

### 3.3 `dashboard/app.js`（资源清单相关函数）

```javascript
// ---------------------------------------------------- 资源清单（ai-resource-hub 数据桥）
function quotaBadge(status) {
    const s = status || '未知';
    if (s.includes('耗尽')) return '<span class="badge danger">' + s + '</span>';
    if (s.includes('接近') || s.includes('偏低')) return '<span class="badge warning">' + s + '</span>';
    if (s.includes('中等')) return '<span class="badge info">' + s + '</span>';
    if (s.includes('充足')) return '<span class="badge online">' + s + '</span>';
    return '<span class="badge offline">' + s + '</span>';
}
function qualityBadge(lv) {
    const m = { T1: 'online', T2: 'warning', T3: 'offline' };
    return '<span class="badge ' + (m[lv] || 'offline') + '">' + (lv || '-') + '</span>';
}
async function fetchResources() {
    try {
        const res = await fetch('/api/resources');
        const data = await res.json();
        if (data.ok) { state.resources = data; renderResources(); }
        else { renderResourcesError(data.error || '数据桥不可用'); }
    } catch (err) { renderResourcesError('无法获取资源清单'); }
}
function renderResources() {
    const d = state.resources;
    if (!d) return;
    const meta = d.meta || {};
    const counts = d.counts || {};
    document.getElementById('res-cap-count').innerText = counts.capabilities ?? '—';
    document.getElementById('res-inst-count').innerText = counts.instances ?? '—';
    const srcEl = document.getElementById('res-source');
    const isRemote = d.source === 'remote';
    srcEl.innerText = isRemote ? '线上 GitHub Pages' : '本地 public 产物';
    srcEl.classList.toggle('text-emerald', isRemote);
    srcEl.classList.toggle('text-rose', !isRemote);
    document.getElementById('res-generated').innerText = (meta.generated_at || '').slice(0, 16) || '—';
    const freshEl = document.getElementById('res-fresh');
    if (meta.fresh === false) freshEl.innerHTML = '<span class="badge warning">数据已陈旧 (>48h)</span>';
    else if (meta.fresh === true) freshEl.innerHTML = '<span class="badge online">数据新鲜</span>';
    else freshEl.innerHTML = '<span class="badge offline">新鲜度未知</span>';
    const capBody = document.getElementById('res-capabilities-body');
    const caps = d.capabilities || [];
    capBody.innerHTML = caps.length
        ? caps.map(c => '<tr>'
            + '<td><code>' + (c.capability_id || '') + '</code></td>'
            + '<td><strong>' + (c['资源名称'] || '') + '</strong></td>'
            + '<td>' + (c['类别'] || '') + '</td>'
            + '<td>' + (c['逻辑模型'] || '') + '</td>'
            + '<td>' + qualityBadge(c['质量等级']) + '</td>'
            + '<td>' + (c['调用方式'] || '') + '</td>'
            + '<td>' + (c['模型族'] || '') + '</td>'
            + '</tr>').join('')
        : '<tr><td colspan="7" style="text-align:center; color:#888;">暂无能力数据</td></tr>';
    const instBody = document.getElementById('res-instances-body');
    const insts = d.instances || [];
    instBody.innerHTML = insts.length
        ? insts.map(i => '<tr>'
            + '<td><code>' + (i.instance_id || '') + '</code></td>'
            + '<td><strong>' + (i['平台'] || '') + '</strong></td>'
            + '<td>' + (i['实际模型名'] || '') + '</td>'
            + '<td><code>' + (i['所属能力'] || '') + '</code></td>'
            + '<td>' + (i['额度单位'] || '') + '</td>'
            + '<td>' + (i['重置规则'] || '') + '</td>'
            + '<td>' + quotaBadge(i['额度状态']) + '</td>'
            + '</tr>').join('')
        : '<tr><td colspan="7" style="text-align:center; color:#888;">暂无实例数据</td></tr>';
}
function renderResourcesError(msg) {
    const row = '<tr><td colspan="7" style="text-align:center; color:var(--rose);">⚠️ ' + msg + '</td></tr>';
    const capBody = document.getElementById('res-capabilities-body');
    const instBody = document.getElementById('res-instances-body');
    if (capBody) capBody.innerHTML = row;
    if (instBody) instBody.innerHTML = row;
    document.getElementById('res-source').innerText = '—';
    document.getElementById('res-generated').innerText = '—';
    document.getElementById('res-fresh').innerHTML = '';
}
```

### 3.4 `dashboard/index.html`（资源 Tab 骨架）

```html
<button class="nav-item" data-tab="resources"><span class="icon">🗂️</span> 资源清单</button>

<section class="tab-page" id="tab-resources">
    <!-- 4 个 stat-card：能力数/实例数/数据源/生成时间 -->
    <div class="table-card">  <!-- 能力表 #res-capabilities-body，7 列 -->
    <div class="table-card">  <!-- 实例表 #res-instances-body，7 列 -->
</section>
```

## 四、设计约束（红线，请在不破坏它们的前提下给建议）

1. **雏形从简**：不要上复杂架构（不需要 ORM/队列/事件流/实时推送）。这是验证链路的基本雏形，下一步再看要不要演进。
2. **只读**：本轮只读数据桥公开产物，不写入、不调飞书 API、不改 ai-resource-hub 仓库。
3. **不写凭证**：数据桥产物本身无凭证；任何环节不存/不传 key、token、密码。
4. **后台代理**：不走浏览器 CORS 直连，统一走 `/api/resources` 同源代理。
5. **能人工验证**：`source=remote/local/auto` 三个钩子保留，便于手动验证回退与缓存。

## 五、期望产出（请按此结构回复）

请用如下固定结构给建议：

1. **结论**（1-2 句总评：雏形够不够好，能不能上线给人看）
2. **建议方案**（按优先级排序，每条 ≤ 3 句，说明"为什么"）
3. **风险**（当前实现最该担心的问题，含严重度）
4. **实施步骤**（若要落地，先做什么后做什么）
5. **需确认**（哪些是业务决策，需要项目 owner 拍板）

重点请回答：这个雏形对"给人看、验证链路"的目标而言，有没有架构缺陷？缓存/回退/新鲜度判断有没有坑？前端渲染有没有明显问题？下一步最小演进应该是什么？
