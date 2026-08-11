# AI Hub 拓扑（仓库结构与数据流）

> 初建：2026-08-10（P2-3 双写分工固化；P4-1 将补齐 CI 与完整拓扑）

## 飞书双写分工（P2-3 结论）

ETP 与 HUB 两份 feishu_sync 写入**不同的飞书 Base / 表，无交集**，不存在双写冲突：

| 脚本 | 仓库 | 写入 Base | 写入表 | 独占声明 |
|---|---|---|---|---|
| `00_工具/ops/feishu_sync.py` | english-teaching-production (ETP) | 英语教学流水线 | 课程进度看板 `tblDQL47cLPeDkqg` | 文件头已加 ✅ |
| `00_中央平台/feishu_sync.py` | ai-hub (HUB) | AI Hub 网关数据 | gateways / api_channels / conversations / daily_stats | 文件头已加 ✅ |

分工规则：**ETP 侧只写「课程进度看板」；HUB 侧只写「AI Hub 网关 4 表」**。
任一脚本不得写对方 Base。

## 网关拓扑（P2-1 结论）

AI Hub 网关三件套（01_网关模板 / 02_网关实例 / 03_共享组件）已于提交
`48eac65` 从仓库删除——网关能力由 **Cherry Studio** 提供，仓库保留中央平台
（`00_中央平台/`）与组件编排器（`06_组件编排器/`）。`D:\游戏\ds_v4_cli`
为仓库外的独立运行网关（聚合端口 :3000），与 ai-hub 仓库无代码共享关系。

<!-- P4-1 待补：CI 工作流拓扑、三仓库服务关系图 -->
