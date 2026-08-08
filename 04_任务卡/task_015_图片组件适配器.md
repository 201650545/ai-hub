# 任务卡 015：图片组件适配器（opencli 浏览器注入生图）

## 执行模型：🟢 Gemini 3.6 Flash

## 目标
实现 image_gen 组件：通过 opencli 控制浏览器打开生图网站、注入提示词、等待生成、提取下载图片到课时文件夹。

## 架构依据
`D:\项目\06_组件编排器\组件编排器架构设计.md` §6（技术路径已定）。
规则卡：`D:\项目\06_组件编排器\组件规则卡\image_gen_*.yaml`（schema 以此为准，含你 task_012 勘探产出的新卡）。

## 前置依赖
- task_012 勘探完成（至少 3 站 ✅ 可行）
- opencli daemon 运行中；豆包/通义已有 AI Hub 会话可复用或新建 `*_image` 会话

## 交付物
`D:\项目\06_组件编排器\components\image_gen.py`

## 接口契约（与 task_013 编排器对齐）

```python
# -*- coding: utf-8 -*-
"""图片生成组件 —— opencli 注入生图站点，下载图片到课时文件夹"""

def run(slot: dict, rule_card_path: str, lesson_dir: str) -> dict:
    """slot 含 {id, topic, prompt, mode=download}
    style_lock 自动拼接到 prompt 末尾
    成功：图片存为 lesson_dir/<slot_id>.png（或 .jpg），
         返回 {"ok": True, "asset": "<slot_id>.png", "site": 站点名}
    失败：按规则卡 fallback 链（换提示词→换备用站点），
         返回 {"ok": False, "asset": None, "error": str}"""

def inject_and_generate(session: str, url: str, prompt: str, card: dict) -> bool:
    """open 站点 → fill/type 注入提示词 → submit → 轮询 poll_js 至超时"""

def extract_image(session: str, card: dict, save_path: str) -> bool:
    """提取图片：
    - method=img_src：eval 取 img.src，https 直链 → urllib 下载
    - method=blob_canvas：eval 执行 canvas.toDataURL('image/png') 转 base64 → 解码保存
    prefer_last=true 时取 DOM 中最后一张匹配图"""

def list_sites() -> list:
    """扫描规则卡目录，返回可用站点列表（供 fallback 排序）"""
```

## 实现要点（浏览器自动化铁律）
1. **opencli 调用方式**：复用 AI Hub 引擎层模式——`D:/Program Files/nodejs/node.exe` + opencli main.js 直调，不走 PATH 中的 cmd 包装（参考 `02_网关实例\ds_v4_cli\engines.py` 的 `_cli_prefix()` 实现）
2. **JS 注入一律单引号**，参数内换行替换为空格（cmd 会截断换行）
3. **豆包是 React 受控输入**，必须用 `type`（真实键入）而非 `fill`（task_005 已踩过此坑）
4. **会话命名** `*_image`，与 AI Hub 搜索会话隔离；掉线自动 `open` 重连一次
5. **审核失败识别**：生成区出现失败/提示文案也算失败，触发 fallback

## 验收标准
- 豆包站点全链路实测：注入「a red apple on a table, flat cartoon style」→ 图片下载到指定目录且可打开
- blob_canvas 提取路径实测通过（至少一个站点）
- fallback 链实测：主站点人为制造失败后自动切换备用站点成功出图
- 三个初始站点（豆包/镜像/通义）至少两个 ✅ 可用

## 完成记录
（执行后填写）
