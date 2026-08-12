# AI Hub 拓扑（仓库结构与数据流）

> 更新：2026-08-12（Monorepo 结构大合并：三服务并入单仓库 `services/`，runtime 统一管理）
> 初建：P2-3 飞书双写分工固化

## 三仓库关系

| 仓库 | GitHub | 本地唯一真源 | 职责 |
|---|---|---|---|
| **ETP** english-teaching-production | 201650545/english-teaching-production（私有） | `D:\英语教学` | 英语教学**规范/工具/命令/汇报镜像**（非成品库）。发布：`publish_all.py` 一键双发 → GitHub + 飞书看板 |
| **HUB** ai-hub | 201650545/ai-hub | `D:\项目` | **AI 聚合管理平台（Monorepo）**。三个服务进程统一在 `services/`，见下方「Monorepo 结构」 |
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
| `services/central/feishu_sync.py` | HUB | AI Hub 网关数据 | gateways / api_channels / conversations / daily_stats | 文件头已加 ✅ |

分工规则：**ETP 侧只写「课程进度看板」；HUB 侧只写「AI Hub 网关 4 表」**。
任一脚本不得写对方 Base。

## Monorepo 结构（2026-08-12 大合并）

三个网关服务全部并入单仓库，代码单仓库、配置单真源、启动单入口、运行三进程：

```
D:\项目\
├── config/runtime.yaml        # 静态拓扑真源（desired state）：三服务 cwd/command/port/url/health
├── runtime/cli.py             # 启动/停止/重启/状态/诊断（python -m runtime.cli <action> [--all]）
├── services/
│   ├── central/               # 中央平台 :8000（FastAPI：/api/stats、/dashboard、飞书同步、GitHub 管理）
│   ├── search_gateway/        # 搜索网关 :3000（统一网关：/v1/chat/completions、/health、渠道/引擎/历史/额度）
│   └── orchestrator/          # 组件编排器 :8791（canvas_server --serve-only 常驻 + 规则卡 rules/）
├── data/                      # 运行时数据（gitignored）：search_gateway/ 渠道配置与记录、orchestrator/ 产物、runtime/ PID与状态
├── logs/                      # 三服务日志（gitignored）
├── tests/                     # 验收套件（tests/run_all.py，路径相对 services/）
└── archive/search_gateway_legacy/  # 旧版网关代码归档（脱敏后保留，不进运行）
```

- **启动**：`启动AIHub.bat` → `python runtime\cli.py start --all`；单服务 `python -m runtime.cli start <name>`
- **状态**：`python -m runtime.cli status`（健康自检，failed 自动自修复）；诊断 `doctor`
- **数据分离**：代码与数据完全分离——`data/` 存渠道 key 配置/调用记录/课件产物，永不入库
- **旧目录**：`00_中央平台/`、`02_网关实例/`、`03_共享组件/`、`06_组件编排器/`、`D:\游戏\ds_v4_cli` 均已迁入 `services/`（旧代码归档在 `archive/`）

## 数据流

```
浏览器/脚本 ──> :8000 中央平台（dashboard、网关管理、飞书同步、GitHub 管理）
        └──> :3000 搜索网关（OpenAI 兼容转发 → DeepSeek/Gemini/OpenRouter 等 7 渠道；quota/history 记录）
        └──> :8791 编排器（画布 SSE 直播 + 规则卡驱动课件生产，产物落 data/orchestrator/）
```

<!-- P4-1 完成：三仓库关系、CI 拓扑、双写分工、网关拓扑均已固化；2026-08-12 Monorepo 大合并完成 -->
