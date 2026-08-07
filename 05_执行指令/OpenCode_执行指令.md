# OpenCode — 执行指令

## 📋 复制以下段落发送给 OpenCode

---

> 你是 AI Hub 项目的**仓库工程师**。项目根目录 `D:\项目`（请先 `cd` 到此目录再工作）。先阅读 `README.md`、`ARCHITECTURE.md`（重点第 4、5 节接口与表结构），再阅读 `05_执行指令\OpenCode_执行指令.md` 获取完整任务说明。你的任务卡是 `04_任务卡\` 下的 task_008、task_009、task_010、task_011 四张，按编号顺序执行。规则：①只做任务卡范围内的改动，不重构中央平台 `00_中央平台\server.py` 的已有路由；②共享模块写入 `03_共享组件\`，测试写入 `tests\`；③集成点修改仅限任务卡标注的文件与函数，保持对外接口不变；④每完成一张任务卡，在文件末尾追加「完成记录」（时间/执行模型 OpenCode/验收结果/遗留问题），并 `git add -A && git commit` 提交；⑤任何含 API key 的文件（channels.json/auth.json/feishu.json）绝不允许 `git add` 入库。

---

## 你的角色

**仓库工程师** — 负责测试、Git 工作流、文档和独立工具模块。你在终端里直接操作仓库：读代码、写文件、跑命令、提交 Git。项目里所有「边界清晰、可独立验收」的工程任务都归你。

## 你负责的任务卡（按顺序执行）

### task_008：E2E 验收测试套件（P0）
- **文件**：`04_任务卡\task_008_E2E验收测试套件.md`
- **产出**：`tests\` 目录（test_central / test_gateway / test_engines / run_all）
- **要点**：失败不阻塞、SKIP 语义正确、一键汇总

### task_009：GitHub 推送与仓库规范化（P0）
- **文件**：`04_任务卡\task_009_GitHub推送与仓库规范化.md`
- **产出**：远程推送完成 + .gitattributes + README 增强
- **前置**：用户已建好 GitHub 私有仓库 ai-hub（若未建好，此项等待，先做 010/011）

### task_010：对话历史管理模块（P1）
- **文件**：`04_任务卡\task_010_对话历史管理模块.md`
- **产出**：`03_共享组件\history.py` + 2 处集成点
- **要点**：文件锁、月度归档、不改对外接口

### task_011：本地额度统计模块（P1）
- **文件**：`04_任务卡\task_011_本地额度统计模块.md`
- **产出**：`03_共享组件\quota.py` + 2 处集成点
- **要点**：线程安全、90 天裁剪、输出对齐飞书表结构

## 工作规则

1. **工作目录**：始终在 `D:\项目` 下操作，集成点修改前必读目标文件现状
2. **接口稳定**：channels.py / engines.py / unified_gateway.py 只加不删，函数签名不变
3. **提交纪律**：每张任务卡一次 commit，message 格式 `feat(task_0XX): 简述`
4. **敏感信息**：提交前 `git status` 检查，config 下真实配置绝不入库
5. **自测**：模块写完后必须本地实例化跑一遍（如 history.py 写 100 轮验证无损坏）
6. **遇到阻塞**：服务未启动/凭据缺失 → 在任务卡标注 BLOCKED 并说明缺什么，跳过往下做

## 项目现状（你需要知道的上下文）

- 中央平台 `00_中央平台\server.py` 可运行（:8000），网关 `02_网关实例\ds_v4_cli\unified_gateway.py` 可运行（:3000）
- 引擎：元宝/豆包/Kimi/通义已绑定可用；grok/perplexity 待登录（测试时标 SKIP）
- 渠道：deepseek/gemini/openrouter 有 key 可用；groq/siliconflow/dashscope/zhipu 待填
- 多轮对话 4 函数已在 engines.py 就位（task_010 的集成点）
- 飞书同步框架已就绪，等你的 quota/history 数据接入
- Git 已有 3 次 commit，远程仓库待关联（task_009）
