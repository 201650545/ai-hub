# AI 画布 · 白板动态图解

> 需求来源：小红书调研《笔记② PenEcho 开源智能白板》→ 产品需求文档 §二「项目二：AI 画布」
> 定位：在无限白板上自由画/写，AI 识别你的意图，把抽象概念「画成动态图」给你看。

## 一句话

**绘制 → 框选 → Recognise（视觉识别）→ Reason（生成动态图解）→ 逐笔播放动画**

## 如何运行

1. 启动本地搜索网关（:3000）——已随 ai-hub 三服务一起管理：
   ```
   cd D:\项目
   python -m runtime.cli start --all
   ```
2. 浏览器打开 `apps/ai-canvas/index.html`（直接双击即可，纯前端单文件）
3. 画布上画点东西（或写一句话）→ 点 **Recognise** 识别 → 点 **Reason** 生成动态图解

## 功能

| 能力 | 说明 |
|------|------|
| 无限白板 | 画笔（颜色/粗细）、文字、橡皮、框选、平移、缩放（滚轮）、撤销、清空、导出 PNG |
| **Recognise** | 框选或整图截图 → 调 `gemini-2.5-flash` 视觉模型 → 识别文字/图形/意图（结果可编辑） |
| **Reason** | 两阶段：① AI 给 **3 个候选方案**（多方案比选，用户决策）→ ② 选一个 → 生成动画脚本 JSON |
| 动画播放 | 声明式脚本解释器逐笔播放，支持 暂停 / 重播 / 步进 / 变速 |
| 内置兜底 | AI 失败时可用内置「勾股定理」示例动画 |

## 架构

```
白板 Canvas（世界坐标 + viewport 变换）
   │  截图（框选优先 → 内容 bbox）
   ▼
网关 http://localhost:3000/v1/chat/completions（OpenAI 兼容）
   │  Recognise ── gemini-2.5-flash（视觉，image_url base64）
   │  Reason 阶段1 ── 3 个候选方案
   │  Reason 阶段2 ── 动画脚本 JSON
   ▼
声明式动画解释器：{title, steps:[{t,type:text/line/rect/circle/arrow,...}]}
   坐标 0-100 归一化 → 屏幕中央播放区，按 t 逐笔绘制（line/arrow 带生长动画）
```

**动画脚本格式**（LLM 输出，前端解释）：
```json
{"title":"勾股定理","steps":[
  {"t":0,"type":"text","text":"直角三角形","x":50,"y":8,"size":16,"color":"#333"},
  {"t":1,"type":"line","x1":30,"y1":65,"x2":70,"y2":65,"color":"#c0392b","width":3},
  {"t":2,"type":"rect","x":20,"y":40,"w":20,"h":20,"fill":"rgba(241,196,15,0.5)","color":"#333","width":2}
]}
```

## AI 模型配置

右上角「⚙ 设置」可改网关地址与模型，配置存 localStorage：

| 用途 | 默认模型 | 备选 |
|------|---------|------|
| Recognise 视觉 | `gemini-2.5-flash` | `gemini-3-flash-preview`、Kimi K3（需网关渠道） |
| Reason 文本 | `gemini-2.5-flash` | `deepseek-v4-flash`（reasoner 生成长脚本会超时，慎用） |

## 设计决策（对齐需求文档 16 条已确认）

- ✅ **多方案比选**（#16）：Reason 一次给 3 个候选，用户选一个才生成脚本
- ✅ **自由动画**（#6/#2.5）：不绑定 SVG/模板，声明式脚本自由组合图形
- ✅ **直接接真实 AI**（#7）：不搞离线模型模板
- ✅ **先通用跑通**（#11）：识别→生成→播放链路优先，主画什么后定
- ✅ **识别结果可编辑**（§2.5）：避免「AI 误解就全错」
- ⚠️ **DeepSeek reasoner 坑**：实测 `deepseek-v4-flash` 生成长 JSON 脚本会因推理爆炸超时，Reason 默认改用 `gemini-2.5-flash`（非 reasoner，12s 稳定出 12 步）

## 路线（对齐文档 §三）

- [x] 阶段 0：画布交互原型（PenEchoLite）
- [x] **阶段 1：画布接入真实 AI（Recognise + Reason 生成自由动画）** ← 本次交付
- [ ] 阶段 2：词境挖空原型（项目一，独立目录）
- [ ] 阶段 3+：词境离线手写识别 / 词汇数据库 / 部署分享

## 文件

- `apps/ai-canvas/index.html` — 单文件应用（白板内核 + AI 接入 + 动画解释器）
