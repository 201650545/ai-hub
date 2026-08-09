# 任务卡 018：GitHub 整理与增量推送

## 执行模型：⚪ OpenCode（或任意仓库工程 Agent）

## 目标
将 `D:\项目` 工作区的未提交变更整理后推送到既有 GitHub 私有仓库。**这不是首次上传**——远程仓库已存在，任务是「分类整理 + 增量推送 + 验证」。

## 前置事实（已核实，勿重复操作）
- 远程仓库：`https://github.com/201650545/ai-hub.git`（私有），remote `origin` 已配置
- 历史提交已全部推送（`git log origin/main..HEAD` 为空）
- **禁止**创建新仓库、**禁止** force push、**禁止**删除远程分支

## 背景问题
过去两天执行 Agent 的作业产生约 152 个未跟踪文件，其中绝大多数是调试期临时脚本（`test_*.py` / `probe_*.py` / `check_*.py` / `run_*.py` / `verify_*.py` / `inspect_*.py` 等，集中在 `06_组件编排器\`），另有少量有价值的修改未入库。直接 `git add -A` 会把调试垃圾灌进仓库，必须先分类。

## 执行步骤

### 1. 盘点分类
```bash
cd D:\项目 && git status --short
```
将未跟踪文件分为两类：
- **A 类（调试脚本，隔离不入库）**：文件名匹配 `test_*` / `probe_*` / `check_*` / `run_*` / `verify_*` / `inspect_*` / `live_demo_*` / `search_*` 的脚本，及 `probe_results_raw.json` 等调试产物
- **B 类（有价值产出，提交入库）**：规则卡更新（`组件规则卡\*.yaml`）、勘探报告、orchestrator/components/canvas 的正装代码、文档更新等

拿不准归属的文件：看内容——含「调试/探针/临时」特征归 A 类；被 orchestrator/组件引用的归 B 类。**仍拿不准的列出来问用户，不要猜。**

### 2. A 类隔离（只移动，不删除）
```bash
mkdir "D:\项目\06_组件编排器\_debug_quarantine"
git mv 或 mv 把 A 类文件移入该目录
```
在 `.gitignore` 追加：
```
06_组件编排器/_debug_quarantine/
```
**安全红线**：只允许移动，禁止 `rm`/`del` 删除任何文件；单批移动不超过 20 个文件，每批后 `git status` 核对。

### 3. B 类提交
- 已修改文件（如 `image_gen_zhipu.yaml`、删除的 `gemini_pro.png`）：查看 diff 确认后随本批提交
- 提交信息：`chore: 第三期调试脚本隔离 + 有价值产出入库`

### 4. 敏感扫描（推送前必做）
```bash
git grep -E "sk-[a-zA-Z0-9_-]{15,}" 
git ls-files | grep -E "channels.json|auth.json|feishu.json"
```
两条都必须为空（占位符除外）。发现真实 key → 立即停止，把文件撤出暂存并报告用户。

### 5. 推送与验证
```bash
git push origin main
git ls-remote origin   # 确认远程 HEAD 与本地一致
```
最后在 GitHub 网页抽查文件树：`06_组件编排器/` 下无 test_/probe_ 脚本、无 config 敏感文件。

## 验收标准
- A 类脚本全部位于 `_debug_quarantine\` 且未入库
- B 类变更已提交并推送成功，远程 HEAD == 本地 HEAD
- 敏感扫描两条命令输出为空
- 仓库文件树干净（无调试脚本）
## 完成记录

- 时间：2026-08-09（America/Los_Angeles）
- 执行模型：仓库工程 Agent（git CLI）
- 移动文件数：151（A 类调试脚本全部移入 `06_组件编排器/_debug_quarantine/`，仅移动未删除，分 8 批每批≤20）
- 提交 hash：`3a6f3cb`（chore: 第三期调试脚本隔离 + 有价值产出入库）
- 验收结果：
  - A 类脚本全部位于 `_debug_quarantine/` 且已 gitignore 未入库 ✅
  - B 类变更（.gitignore 追加隔离规则 + 删除 gemini_pro.png）已提交并推送成功，远程 HEAD==本地 HEAD（3a6f3cb）✅
  - 敏感扫描两条命令为空（仅 3 处占位符）✅
  - 远程文件树干净：06_组件编排器/ 无 test_/probe_ 调试脚本、无 config 敏感文件 ✅
- 遗留问题：`06_组件编排器/run_master_qa_fix.py` 为早期已入库的 run_* 调试脚本（非本次 151 个未跟踪文件），因红线禁止删除文件未擅自移出仓库，待用户决定是否隔离。
