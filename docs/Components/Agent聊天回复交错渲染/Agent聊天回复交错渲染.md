# Agent 聊天回复交错渲染

## 需求背景

如意 Agent 在回复用户时，一个完整的 assistant 回合中 **content（文本）和 tool_calls（工具调用）是交错出现的**，而非简单的"先全部文本再全部工具"。例如一个典型的回复流程：

1. LLM 输出 content："你好！让我看看周围有什么"
2. LLM 发起工具调用：`Bash("pwd && ls")`、`ReadFile("/root/.heartclaw/...")`
3. 工具执行完成，LLM 继续输出 content："好的，让我再检查一下配置"
4. LLM 发起新的工具调用：`ReadFile("/root/.heartclaw/config.json")`
5. 工具执行完成，LLM 输出最终回复

前端需要**按接收顺序**依次渲染文本块和工具调用块，而不是把它们分成两组。

## 核心问题

旧的 `ChatMsg` 数据模型把 `content: string` 和 `toolResults: ToolResult[]` 作为两个独立字段存储，渲染时只能"先文本后工具"或"先工具后文本"，无法表达交错顺序。

## 解决方案：有序 Blocks 列表

### 数据模型

在 `ChatMsg` 中引入 `blocks: MsgBlock[]` 有序列表，每个 block 要么是文本块，要么是工具块：

```typescript
// apps/web/src/components/chat/ChatMessage.tsx

type TextBlock = { kind: 'text'; text: string }
type ToolBlock = { kind: 'tool'; tool: ToolResult }
type MsgBlock = TextBlock | ToolBlock

type ChatMsg = {
  id: string
  role: 'user' | 'assistant'
  content: string          // 保留用于兼容/全文搜索
  timestamp: string
  toolResults?: ToolResult[] // 保留用于降级渲染
  blocks?: MsgBlock[]        // 有序内容块列表（优先使用）
}
```

### 渲染逻辑

`ChatMessage` 组件优先使用 `blocks` 渲染，按数组顺序依次输出：

- `TextBlock` → 渲染为 Markdown 气泡（`ReactMarkdown` + `remarkGfm`）
- `ToolBlock` → 渲染为 `ToolResultItem` 组件（显示执行状态、可展开预览）

如果 `blocks` 为空则降级为旧模式（`toolResults` + `content`）。

### WS 消息处理时序

在 `useAppStore` 的 `handleWsMessage` 中，按 WebSocket 事件到达顺序构建 blocks：

```
事件流                              blocks 变化
────────────────────────────────────────────────────────────
tool_status(executing, content="你好")  → [TextBlock("你好"), ToolBlock(Bash, executing)]
tool_status(success, call_id=...)       → [TextBlock("你好"), ToolBlock(Bash, success)]
tool_status(executing, content="好的")  → [..., TextBlock("好的"), ToolBlock(ReadFile, executing)]
tool_status(success, call_id=...)       → [..., TextBlock("好的"), ToolBlock(ReadFile, success)]
HTTP response(reply="最终回复")         → [..., TextBlock("最终回复")]
```

关键辅助函数：

| 函数 | 作用 |
|------|------|
| `appendBlock(m, block)` | 在 blocks 末尾追加一个块 |
| `appendTextToLastBlock(m, text)` | 如果最后一个块是 TextBlock 则追加文本，否则新建 TextBlock |
| `updateToolInBlocks(m, callId, updater)` | 通过 call_id 定位 ToolBlock 并更新其状态 |

### 后端数据源

后端通过 `OutputEmitter` 的 `ToolExecutingEvent` 推送工具调用事件。该事件的 `content` 字段携带"LLM 在本轮工具调用前返回的伴随文本"（如"让我搜索一下"），同一批 tool_calls 中只有第一个工具携带 content，后续为空。

```python
# apps/ruyi-api/src/core/output/types.py

@dataclass
class ToolExecutingEvent(OutputEvent):
    call_id: str = ""
    tool_name: str = ""
    args_summary: str = ""
    content: str = ""       # LLM 伴随文本
```

前端收到 `tool_status(executing)` 时：
1. 如果 `data.content` 非空，先插入 `TextBlock`
2. 再插入 `ToolBlock(status=executing)`

收到 `tool_status(success/error)` 时，通过 `call_id` 找到对应 `ToolBlock` 更新状态。

## 涉及文件

| 文件 | 变更 |
|------|------|
| `apps/web/src/components/chat/ChatMessage.tsx` | 新增 `MsgBlock` 类型体系，组件优先按 blocks 渲染 |
| `apps/web/src/stores/useAppStore.tsx` | WS 处理逻辑改为构建 blocks 列表，新增辅助函数 |
| `apps/ruyi-api/src/core/output/types.py` | `ToolExecutingEvent.content` 字段（已有） |

## 最终效果

前端渲染效果严格按照后端事件到达顺序：

```
┌─────────────────────────────────────┐
│ 你好！让我看看周围有什么 👀          │  ← TextBlock
├─────────────────────────────────────┤
│ ⟳ Bash  echo "=== 📁 当前工作..."   │  ← ToolBlock (executing → success)
│ ⟳ ReadFile  /root/.heartclaw/...    │  ← ToolBlock (executing → success)
├─────────────────────────────────────┤
│ 好的，让我再检查一下配置             │  ← TextBlock
├─────────────────────────────────────┤
│ ✓ ReadFile  /root/.heartclaw/...    │  ← ToolBlock (success)
├─────────────────────────────────────┤
│ 根据检查结果，你的环境配置如下...    │  ← TextBlock (最终回复)
└─────────────────────────────────────┘
```
