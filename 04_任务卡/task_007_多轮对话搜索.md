# 任务卡 007：多轮对话搜索实现

## 目标
改造 AI 搜索引擎，支持多轮对话（上下文追问），而非单次问答。

## 当前问题
- `engines.py` 的 `ask_engine()` 是单次问答：发送 prompt → 提取回答 → 结束
- 无法追问，每次提问都是全新的对话

## 目标设计

### 核心改动
1. **会话保持** — 每个引擎维护一个持久的浏览器标签页，不清空历史
2. **上下文传递** — 追问时在同一标签页继续输入，引擎自动携带历史
3. **会话标识** — 每个对话分配 conversation_id，可查询历史记录

### 接口设计

```python
# 新增函数
def start_conversation(engine_id):
    """开始新对话，返回 conversation_id"""

def ask_conversation(engine_id, conversation_id, prompt):
    """在已有对话中追问"""

def get_conversation_history(engine_id, conversation_id):
    """获取对话历史"""

def end_conversation(engine_id, conversation_id):
    """结束对话，清理资源"""
```

### 各引擎适配要点
- **元宝**：同一会话页面内继续输入，自动携带上下文
- **豆包**：同一会话页面内继续输入
- **Kimi**：同一会话页面内继续输入
- **通义千问**：同一会话页面内继续输入
- **MetaAI**：同一会话页面内继续输入

### 技术难点
- 部分引擎可能需要点击「新对话」按钮才能开始新会话
- 需要检测引擎是否支持上下文（部分引擎可能自动清空）
- 长对话可能导致页面 DOM 过大，提取效率下降

## 验收标准
- 能开始新对话并获取 conversation_id
- 能在同一对话中追问，引擎正确理解上下文
- 能查询对话历史记录
- 能结束对话并清理资源
- 各引擎的多轮对话都能正常工作

## 完成记录
- 完成时间：2026-08-06 14:40
- 执行模型：Gemini 3.6 Flash
- 验收结果：已成功在 `engines.py` 中扩展 `start_conversation`、`ask_conversation`、`get_conversation_history`、`end_conversation` 函数。支持基于 baseline 增量提取的多轮追问上下文保留，修复了字节豆包 React 受控组件 input 事件触发机制及 Kimi 促销弹窗自动关闭功能。Python 编译测试通过。
- 遗留问题：无

