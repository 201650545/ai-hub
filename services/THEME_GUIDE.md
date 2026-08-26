# 网关前端多风格体系规范 v1（2026-08-25）

> 适用：:3000 hub_page / :3100 api_page(已有多风格) / :8791 orchestrator / :8000 central dashboard。
> 原则：**皮肤层注入，不重写页面**——每页追加一段 `<style id="skin-layer">` + 右下角悬浮切换器 + 少量 JS；
> token 化程度不同的页面用 `!important` 只压关键表面（body 画布/顶栏/主按钮/输入框），JS 内联样式的次要元素不强求。

## 一、token 架构（抄 :3100 api_page 模式）

- 存储：`localStorage('<页前缀>-skin')`；`document.documentElement.setAttribute('data-skin', s)`
- 结构：`html[data-skin="x"]{ --token 覆盖 }` + `html[data-skin="x"] .top-nav{...}` 定点覆盖
- 切换器：固定右下角圆形 🎨 按钮 → 展开皮肤 chips（emoji+名）；点击切换 + toast 提示

## 二、皮肤家族 token 表（六族，各网关取 3–4 族组合，不要求一致）

| 族 | data-skin | 底色画布 | 主色 | 圆角 | 字体 | 性格 |
|---|---|---|---|---|---|---|
| 苹果极简 | apple | #f5f5f7 | #0071e3 | 18px | 系统 SF/PingFang | 留白、毛玻璃、克制 |
| 华为商务 | huawei | #e8eef7→深蓝渐变 | #007dff + 华为红 #c7000b 点缀 | 10px 方正 | 加粗黑体大标题 | 网格纹理、科技蓝、企业感 |
| 小米活力 | xiaomi | #fff7f0 暖白 | #ff6900 橙 | 20px 大圆角 | 圆润加粗 | 渐变 hero、促销大字报感 |
| 可爱动画 | kawaii | #fdf0f5 奶油粉 | #ff7eb6 粉 + #a78bfa 紫 | 24px 胖圆 | 幼圆/Yuanti，fallback 圆体 | 贴纸描边卡、hover 弹跳、点击爱心粒子 |
| 修道仙侠 | xiuxian | 宣纸米 #f3ede1 | 朱砂 #a03a2a + 墨 #2b2b28 | 6px 直角如简牍 | KaiTi/STKaiti 楷体 | 卷轴卡片、云纹边框、竖排标题、随机道语 toast |
| 科技暗夜 | midnight | #0b1020 星空 | #22d3ee 青 + #818cf8 紫 | 14px | mono 点缀 | 星点背景、霓虹描边（暗色唯一族） |

### 各族定点覆盖清单（每皮肤必做）
`body`（画布底色/装饰渐变）· `.top-nav/.left-dock/.toolbar 类顶栏` · `.btn 主按钮`（黑→主色）·
`input/select 背景`（#fff→--bg-card）· `.brand 标题色/字体` · 滚动条 thumb · 卡片 border-radius 缩放

### 趣味元素菜单（按皮肤挂载）
- **全皮肤通用**：logo 点击彩蛋动画；切换皮肤 toast
- **kawaii**：鼠标点击 ❤️粒子；widget hover 弹跳 keyframes；标题波浪 emoji
- **xiuxian**：开屏/切肤随机「道语」toast（内置 12 条，不出网）；🎨按钮改「☯」
- **xiaomi**：主按钮按下「咔哒」缩放 + 价格签式 badge 样式
- **huawei**：画布网格线背景（CSS gradient 实现）
- **midnight**：CSS 星点闪烁（多层 radial-gradient 动画）
- **生图配图（可选后续）**：sensenova-u1.5-lite 生成各皮肤 banner/贴纸 → `/img/skins/*.png` 自托管，
  kawaii/xiuxian 收益最大；先纯 CSS 上线，图后补

## 三、各网关分配

| 网关 | 页面 | 皮肤集 | localStorage 前缀 |
|---|---|---|---|
| :3100 api_page | 已有 monet 等 4 套 | 不动 | gw-style |
| :3000 hub_page | 空间画布搜索门户 | apple(默认=现状)/huawei/xiaomi/kawaii | hub-skin |
| :8791 orchestrator canvas+gallery | 工作流编排器 | apple(默认=现状)/midnight/xiuxian | orch-skin |
| :8000 中央导航(/)+控制台(/dashboard) | 导航页+监控台 | apple(默认=现状)/huawei/xiaomi/xiuxian/midnight | nav-skin + cd-skin（两页独立） |

> 默认一律「保持现状」：首次打开不改变原观感，用户点右下角 🎨 后才换肤并记住。
> :8000 导航页皮肤走 /static/nav-skins.{css,js}（server.py 是 f-string 内联 HTML，塞花括号要双写，故用静态文件）；server.py 改动需重启（提权脚本自跑）。

## 四、红线
- 不改业务 JS 逻辑；只加样式层与独立 `<script id="skin-js">`
- 内联样式密集处不强改（验收=整体观感换风格，非像素级全覆盖）
- 每页完成后 `node --check` 校验脚本；浏览器 Ctrl+F5 由用户目验
