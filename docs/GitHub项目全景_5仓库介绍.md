# AI Hub 体系 · GitHub 项目全景（5 仓库路由图）

> 用途：给高级模型（GLM5.3 等）与任何 Agent 看——每个仓库负责什么、边界在哪、深入该读哪里。
> 与记忆仓库 global/PROJECTS.md 一致（2026-08-14 GPT 审查后瘦身为纯路由图）。

## 一句话全景
- ai-hub-memory = 记忆（共享记忆/路由）
- ai-resource-hub = 资源（AI 资源运营/配置真源）
- ai-hub = 操作（网关/搜索/编排）
- feishu-data-hub = 数据桥（飞书 → 公开静态数据）
- english-teaching-production = 教学业务（教学生产规范/工具/流程）

## 仓库路由表
| Repo | 负责什么 | 不负责什么 | 深入读取 |
|------|---------|-----------|---------|
| ai-hub-memory | Agent 共享记忆、路由规则、项目状态 | 业务实现、资源实时状态 | MEMORY.json / 对应 project STATE |
| ai-resource-hub | AI 资源运营与配置来源（API/账号/额度） | Agent 记忆规则 | repo README / 资源真源 |
| ai-hub | AI 网关、搜索、编排操作面 | 资源台账真源 | repo README |
| feishu-data-hub | 飞书数据公开/静态桥接 | 飞书业务数据的编辑逻辑 | repo README |
| english-teaching-production | 教学生产规范、工具和流程 | 通用 Agent 基础设施 | repo README / teaching STATE |

## 关系
- 飞书数据 → feishu-data-hub → AI 消费端
- 资源配置 → ai-resource-hub → ai-hub / Agents
- ai-hub-memory → 为所有 Agent 提供共享记忆
- english-teaching-production → 教学业务执行层

## 记忆系统架构（ai-hub-memory 内部）
- v2.1：项目隔离 + 分层记忆 + 隔离暂存（inbox）+ 16 条宪法（R1'~R16）。
- 常读链：PROJECTS（全景）→ RULES（规则）→ DECISIONS（决策）→ 对应项目 STATE（状态）→ 需要时 RESOURCES（资源）/ TOOLS（工具）。
- 命令：memory.py（route/read/search/write/validate/register + capture/status/settle-plan/resolve/settle/sync）。
- 5 分法：RULES=MUST / PROJECTS=WHERE / RESOURCES=WHAT / TOOLS=HOW / STATE=NOW。

## 审查提示（给 GLM5.3）
1. 5 仓库职责是否有重叠/缺失？（重点：ai-hub-memory 与 ai-hub 的边界）
2. ai-resource-hub 的调度器与 ai-hub 的网关是否该整合？
3. 数据流（飞书 → data-hub → 各消费方）是否合理？
4. 记忆系统的 16 条宪法 + 5 分法是否有漏洞？

## 关联文档
- 记忆同步操作：`Agent记忆同步操作文档_memory-sync.md`（同目录）
- 详细实现：各仓库 README / ai-hub-memory global/ 各文件
