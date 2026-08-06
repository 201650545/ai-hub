# 任务卡 002：管理面板 UI 实现

## 目标
实现 `00_中央平台/dashboard/` 下的管理面板，提供网关管理、GitHub 项目、飞书同步的可视化界面。

## 技术栈
- 纯 HTML/CSS/JS（无框架，保持轻量）
- 通过 Fetch API 调用后端接口
- 深色主题，科技感设计

## 页面结构

### 1. 导航首页（已实现基础版）
- 所有网关卡片，点击跳转
- 在线/离线状态标识

### 2. 网关管理页
- 网关列表（名称、端口、状态、最后在线时间）
- 启动/停止按钮
- 健康检查结果展示
- 注册新网关表单

### 3. GitHub 项目页
- 仓库列表（名称、语言、Stars、更新时间）
- Issue 列表
- 创建仓库表单

### 4. 飞书同步页
- 同步状态展示
- 手动触发同步按钮
- 同步历史记录

### 5. 统计页
- 各网关调用量统计
- 渠道使用分布
- 每日活跃用户

## API 接口（已定义）
```
GET  /api/gateways          # 网关列表
POST /api/gateways          # 注册网关
POST /api/gateways/{id}/start   # 启动
POST /api/gateways/{id}/stop    # 停止
GET  /api/gateways/{id}/health  # 健康检查
GET  /api/github/repos      # GitHub 仓库
POST /api/feishu/sync       # 飞书同步
GET  /api/stats             # 全局统计
```

## 验收标准
- 5 个页面都能正常访问和操作
- 数据实时刷新（或手动刷新）
- 响应式布局，适配不同屏幕
- 操作有明确的反馈（成功/失败提示）

## 完成记录
- 完成时间：2026-08-06 14:41
- 执行模型：Gemini 3.6 Flash
- 验收结果：已实现 `00_中央平台/dashboard/` 目录下的 `index.html`、`styles.css` 和 `app.js`。提供导航首页、网关管理、GitHub 项目、飞书同步、统计分析 5 大视图，纯 Vanilla JS + Flex/Grid 深色毛玻璃科技风格，全面接入后端 REST API 并配备 10 秒自动轮询刷新及 Toast 操作反馈。
- 遗留问题：无

