# AI Hub 拓扑（仓库结构与数据流）

> 更新：2026-08-10（P4-1 补齐三仓库关系与 CI 工作流拓扑）
> 初建：P2-3 飞书双写分工固化

## 三仓库关系

| 仓库 | GitHub | 本地唯一真源 | 职责 |
|---|---|---|---|
| **ETP** english-teaching-production | 201650545/english-teaching-production（私有） | `D:\英语教学` | 英语教学**规范/工具/命令/汇报镜像**（非成品库）。发布：`publish_all.py` 一键双发 → GitHub + 飞书看板 |
| **HUB** ai-hub | 201650545/ai-hub | `D:\项目` | AI 聚合管理平台。中央平台 `00_中央平台/`（:8000）；网关能力由 **Cherry Studio** 提供（网关三件套已于 `48eac65` 删除）；组件编排器 `06_组件编排器/` |
| **FDH** feishu-data-hub | 201650545/feishu-data-hub | `D:\feishu-learning-english-export` | 飞书多维表格数据导出 Hub。定时同步 → GitHub Pages |

> 独立运行网关 `D:\游戏\ds_v4_cli`（聚合端口 :3000）在 HUB 仓库外，与 ai-hub 无代码共享。

## CI 工作流拓扑

| 仓库 | 工作流 | 触发 | 校验内容 |
|---|---|---|---|
| ETP | `.github/workflows/verify.yml` | push / PR | `validate_banks.py`（题库 Schema）+ `validate_content.py`（内容 JSON 有效性） |
| HUB | `.github/workflows/test.yml` | push / PR | `tests/run_all.py`（依赖缺失的网关时代套件 SKIP） |
| FDH | `sync-daily.yml` / `sync-hourly.yml` | schedule / manual | 同步飞书 → validate → security scan → GitHub Pages；**P3-2 防噪音**：内容无实质变化时跳过部署 |
| FDH | `sync-manual.yml` | manual | 手动同步（始终部署） |
| FDH | `validate.yml` | push / PR | 校验 + 安全扫描 |

## 飞书双写分工（P2-3 结论）

ETP 与 HUB 两份 feishu_sync 写入**不同的飞书 Base / 表，无交集**，不存在双写冲突：

| 脚本 | 仓库 | 写入 Base | 写入表 | 独占声明 |
|---|---|---|---|---|
| `00_工具/ops/feishu_sync.py` | ETP | 英语教学流水线 | 课程进度看板 `tblDQL47cLPeDkqg` | 文件头已加 ✅ |
| `00_中央平台/feishu_sync.py` | HUB | AI Hub 网关数据 | gateways / api_channels / conversations / daily_stats | 文件头已加 ✅ |

分工规则：**ETP 侧只写「课程进度看板」；HUB 侧只写「AI Hub 网关 4 表」**。
任一脚本不得写对方 Base。

## 网关拓扑（P2-1 结论）

AI Hub 网关三件套（01_网关模板 / 02_网关实例 / 03_共享组件）已于提交
`48eac65` 从仓库删除——网关能力由 **Cherry Studio** 提供，仓库保留中央平台
（`00_中央平台/`）与组件编排器（`06_组件编排器/`）。`D:\游戏\ds_v4_cli`
为仓库外的独立运行网关（聚合端口 :3000），与 ai-hub 仓库无代码共享关系。

<!-- P4-1 完成：三仓库关系、CI 拓扑、双写分工、网关拓扑均已固化 -->
