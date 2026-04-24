# 统一输出系统设计

> OutputEmitter — 所有 Agent 输出的统一分发管道  
> 如意、Kairos、定时任务的输出通过同一套事件体系，分发到日志、WebSocket、飞书等多个后端

---

## 1. 设计理念

HeartClaw 中存在多种"输出"：
- 如意 Agent 的最终回复文本
- Kairos 自治模式的回复和生命周期状态
- 定时任务的执行结果
- 工具调用过程中的实时状态（开始执行、完成、失败）
- LLM 在调用工具前返回的伴随文本（如"好的！让我搜索一下"）

这些输出需要被送到不同的目的地：
- **日志终端** — 开发调试观察
- **WebSocket** — 前端实时展示
- **飞书消息** — 飞书单聊回复
- **HTTP Future** — API 调用方等待最终结果

**核心原则**：产生输出的组件只需调用 `emitter.emit(event)` 一个函数，不需要关心输出会被送到哪里。输出后端的注册和分发由 `OutputEmitter` 统一管理。

---

## 2. 架构总览

```
┌──────────────────── 输出产生方 ────────────────────┐
│                                                     │
│  ToolScheduler          QueueProcessor              │
│  ├─ ToolExecutingEvent  ├─ FinalReplyEvent          │
│  └─ ToolDoneEvent       ├─ KairosLifecycleEvent     │
│                         └─ (tick/sleep 生命周期)     │
│                                                     │
│  LLM 伴随文本通过 ToolExecutingEvent.content 携带    │
└─────────────────────────────────────────────────────┘
                         │
                   emitter.emit(event)
                         │
                         ▼
              ┌── OutputEmitter ──┐
              │                   │
              │  遍历所有后端      │
              │  逐个调用 handle() │
              │  单个异常不影响其他  │
              └───────────────────┘
                    │  │  │  │
          ┌─────────┘  │  │  └──────────┐
          ▼            ▼  ▼             ▼
    FutureBackend  LogBackend  WebSocket  FeishuBackend
    (HTTP 响应)    (终端日志)  Backend    (飞书消息)
                               (前端推送)
```

---

## 3. 事件类型体系

所有输出事件继承自 `OutputEvent` 基类，定义在 `core/output/types.py`。

### 3.1 基类

```python
@dataclass
class OutputEvent:
    source: str       # "ruyi" | "kairos" | "cron" — 谁产生的
    timestamp: str    # 自动填充的时间戳
```

`source` 字段标识事件来源，下游后端可据此做过滤或路由。

### 3.2 四种事件子类

| 事件类型 | 产生者 | 用途 |
|----------|--------|------|
| `ToolExecutingEvent` | ToolScheduler | 工具开始执行，携带 LLM 伴随文本 |
| `ToolDoneEvent` | ToolScheduler | 工具执行完成（成功 / 失败 / 取消） |
| `FinalReplyEvent` | QueueProcessor | Agent 最终回复文本（替代原 ReplyEnvelope） |
| `KairosLifecycleEvent` | QueueProcessor | Kairos tick / sleep 生命周期事件 |

#### ToolExecutingEvent

```python
@dataclass
class ToolExecutingEvent(OutputEvent):
    call_id: str       # 工具调用 ID，如 "Grep:74"
    tool_name: str     # 工具名，如 "Grep"
    args_summary: str  # 参数摘要，如 "path=/root/.heartclaw/tmp, pattern=猫咪"
    content: str = ""  # LLM 伴随文本（仅同一批第一个工具携带）
```

**伴随文本机制**：LLM 返回 `content + tool_calls` 时（如"好的！让我搜索一下" + 两个 Grep 调用），`content` 只附着在第一个工具的 `ToolExecutingEvent` 上，后续工具的 `content` 为空字符串。这样前端能在展示第一个工具加载状态的同时，显示 LLM 的解释文本。

#### ToolDoneEvent

```python
@dataclass
class ToolDoneEvent(OutputEvent):
    call_id: str           # 与 ToolExecutingEvent 的 call_id 对应
    tool_name: str
    success: bool
    status: str            # "success" | "error" | "cancelled"
    result_preview: str    # 成功时的结果预览（前 500 字符）
    error: str | None      # 失败时的错误信息
    duration_ms: float     # 执行耗时
```

#### FinalReplyEvent

```python
@dataclass
class FinalReplyEvent(OutputEvent):
    text: str              # 回复文本
    mode: str              # "user" | "cron" | "tick"
    chat_id: str
    open_id: str
    source_channel: str    # "feishu" | "api" | ""
    source_msg_id: str
    _future: Future | None # HTTP 请求的 asyncio.Future
```

#### KairosLifecycleEvent

```python
@dataclass
class KairosLifecycleEvent(OutputEvent):
    event: str   # "tick_start" | "tick_done" | "sleep_start" | "sleep_interrupted" | "sleep_done"
    detail: dict # 附加信息，如 {"sleep_seconds": 300}
```

---

## 4. OutputEmitter（分发器）

定义在 `core/output/emitter.py`，是整个系统的核心枢纽。

```python
class OutputEmitter:
    def __init__(self) -> None:
        self._backends: list[OutputBackend] = []

    def add_backend(self, backend: OutputBackend) -> None:
        self._backends.append(backend)

    async def emit(self, event: OutputEvent) -> None:
        for backend in self._backends:
            try:
                await backend.handle(event)
            except Exception:
                logger.error(...)  # 单个后端异常不影响其他
```

**关键特性**：
- 后端按注册顺序执行
- 单个后端 `handle()` 抛异常时只记录日志，不中断其他后端
- 后端可以选择性处理事件（在 `handle()` 里 `isinstance` 判断后 return）

---

## 5. 内置后端

### 5.1 FutureBackend

- **只响应** `FinalReplyEvent`
- 将回复文本写入 `event._future`，供 HTTP 接口 `await future` 拿到结果
- 不关心其他事件类型

### 5.2 LogBackend

- **响应所有事件类型**
- 将事件格式化为可读日志输出到终端
- 示例：`[ruyi] Tool > Grep 开始执行 (path=/tmp)`

### 5.3 WebSocketBackend

- **响应** `ToolExecutingEvent`、`ToolDoneEvent`、`KairosLifecycleEvent`
- **不响应** `FinalReplyEvent`（HTTP 通过 Future 返回，不需要 WebSocket 推送）
- 将事件转为 JSON，通过 `ConnectionManager.broadcast()` 推送到前端

**WebSocket 消息映射**：

| 事件 | WS `type` | WS `data.status` |
|------|-----------|-------------------|
| `ToolExecutingEvent` | `"tool_status"` | `"executing"` |
| `ToolDoneEvent` | `"tool_status"` | `"success"` / `"error"` / `"cancelled"` |
| `KairosLifecycleEvent` | `"kairos_event"` | — |

### 5.4 FeishuBackend

- **只响应** `FinalReplyEvent`
- 发送条件：`chat_id` 非空、`text` 非空、`source_channel` 为 `"feishu"` 或 `""`
- 调用 `FeishuChannel.send_message()` 发送飞书消息

---

## 6. OutputBackend 协议

所有后端必须满足 `OutputBackend` 协议：

```python
class OutputBackend(Protocol):
    name: str
    async def handle(self, event: OutputEvent) -> None: ...
```

只有两个要求：
1. 一个 `name` 类属性（字符串），用于日志标识
2. 一个 `async def handle()` 方法，接收 `OutputEvent`

---

## 7. 如何添加新的输出后端

以添加**微信后端**为例，完整步骤如下：

### 7.1 创建后端类

在 `core/output/backends.py`（或新建文件如 `core/output/wechat_backend.py`）中添加：

```python
class WeChatBackend:
    """通过微信 API 发送消息。"""

    name = "wechat"

    def __init__(self, wechat_client: WeChatClient) -> None:
        self._client = wechat_client

    async def handle(self, event: OutputEvent) -> None:
        # 1. 决定响应哪些事件类型
        if isinstance(event, FinalReplyEvent):
            # 只在来源渠道是微信时发送
            if event.source_channel != "wechat":
                return
            if not event.chat_id or not event.text:
                return
            await self._client.send_text(event.chat_id, event.text)

        elif isinstance(event, ToolDoneEvent):
            # 可选：工具完成时发送状态通知
            if event.source != "ruyi":
                return
            status = "✅" if event.success else "❌"
            await self._client.send_text(
                some_chat_id,
                f"{status} {event.tool_name} ({event.duration_ms:.0f}ms)",
            )

        # 不关心的事件类型直接忽略（不需要写 else: return）
```

**编写要点**：
- `name` 属性：给后端取一个唯一的名字，出现在错误日志中
- `handle()` 方法：用 `isinstance` 判断事件类型，不关心的直接 `return`
- 按需过滤：通过 `event.source`（谁产生的）和 `event.source_channel`（来自哪个渠道）做细粒度控制
- 异常安全：`handle()` 内部尽量 try-except，但即使抛出异常也不会影响其他后端

### 7.2 在 `core/output/__init__.py` 中导出

```python
from core.output.backends import WeChatBackend

__all__ = [
    # ... 已有的导出
    "WeChatBackend",
]
```

### 7.3 在 `main.py` 中注册

```python
from core.output import WeChatBackend

# 在 startup() 函数中，emitter 创建之后：
if settings.channel_mode == "wechat":
    wechat_client = WeChatClient(...)
    emitter.add_backend(WeChatBackend(wechat_client))
    logger.info("WeChatBackend registered")
```

完成。不需要修改 `OutputEmitter`、`ToolScheduler`、`ExecutionEngine`、`QueueProcessor` 或任何产生事件的组件。

### 7.4 可选：添加新的事件类型

如果微信有独特的输出需求（如发送模板消息），可以在 `core/output/types.py` 中新增事件子类：

```python
@dataclass
class WeChatTemplateEvent(OutputEvent):
    """微信模板消息事件。"""
    template_id: str = ""
    data: dict = field(default_factory=dict)
    user_openid: str = ""
```

然后在产生该输出的组件中 `await emitter.emit(WeChatTemplateEvent(...))`，在 `WeChatBackend.handle()` 中增加 `isinstance(event, WeChatTemplateEvent)` 分支即可。

---

## 8. 数据流详解

### 8.1 如意用户消息流程

```
用户发送消息
  │
  ▼ POST /api/chat
  QueueProcessor.dequeue() 取出消息
  │
  ▼ Agent.run()
  ExecutionEngine.run(source="ruyi")
  │
  ├─ LLM 返回: content="让我搜索一下" + tool_calls=[Grep, Grep]
  │   │
  │   ▼ ToolScheduler.schedule_batch(assistant_content="让我搜索一下")
  │     ├─ schedule(Grep:74, content="让我搜索一下")
  │     │   ├─ emit(ToolExecutingEvent(content="让我搜索一下"))  ← 第一个工具携带文本
  │     │   ├─ 执行 Grep
  │     │   └─ emit(ToolDoneEvent(status="success"))
  │     │
  │     └─ schedule(Grep:75, content="")
  │         ├─ emit(ToolExecutingEvent(content=""))  ← 第二个工具不携带文本
  │         ├─ 执行 Grep
  │         └─ emit(ToolDoneEvent(status="success"))
  │
  ├─ LLM 返回: content="搜索完成！找到了 3 条..."（纯文本，无 tool_calls）
  │   └─ 返回 EngineResult(text="搜索完成！...")
  │
  ▼ QueueProcessor 创建 FinalReplyEvent
  emit(FinalReplyEvent(text="搜索完成！...", _future=future))
    │
    ├─ FutureBackend  → future.set_result("搜索完成！...")
    │                    → HTTP 200 返回给前端
    ├─ LogBackend     → 终端打印 [ruyi] Agent > 搜索完成！...
    ├─ WebSocketBackend → 不广播 FinalReplyEvent
    └─ FeishuBackend  → 如果 source_channel=feishu，发送飞书消息
```

### 8.2 Kairos tick 流程

```
QueueProcessor 注入 tick 消息
  │
  ▼ emit(KairosLifecycleEvent(event="tick_start"))
  KairosRunner.handle_tick()
  │ ← 内部工具调用同样产生 ToolExecutingEvent / ToolDoneEvent (source="kairos")
  │
  ▼ emit(FinalReplyEvent(source="kairos", mode="tick"))
  emit(KairosLifecycleEvent(event="tick_done"))
  │
  ▼ 进入 sleep
  emit(KairosLifecycleEvent(event="sleep_start", detail={"sleep_seconds": 300}))
  │
  ├─ 正常结束 → emit(KairosLifecycleEvent(event="sleep_done"))
  └─ 被中断   → emit(KairosLifecycleEvent(event="sleep_interrupted"))
```

---

## 9. 文件清单

| 文件 | 职责 |
|------|------|
| `core/output/__init__.py` | 统一导出所有公开类 |
| `core/output/types.py` | `OutputEvent` 基类 + 4 种事件子类 |
| `core/output/emitter.py` | `OutputEmitter` 分发器 + `OutputBackend` 协议 |
| `core/output/backends.py` | 4 个内置后端：Future / Log / WebSocket / Feishu |

**改造的文件**：

| 文件 | 改动 |
|------|------|
| `core/tool/scheduler.py` | 注入 emitter，schedule() 新增 source/content 参数，状态变更时 emit |
| `core/engine/engine.py` | run() 新增 source 参数，将 LLM content 传给 schedule_batch() |
| `core/agent/agent.py` | run() 传入 source="ruyi" |
| `core/agent/kairos_agent.py` | handle_tick() 传入 source="kairos" |
| `core/queue/processor.py` | 用 OutputEmitter 替换 ReplyDispatcher，emit FinalReplyEvent + KairosLifecycleEvent |
| `main.py` | 创建 OutputEmitter，注册后端，注入各组件 |

---

## 10. 扩展指南速查表

| 需求 | 操作 | 需要改动的文件 |
|------|------|----------------|
| **添加新的输出后端**（如微信、钉钉、Telegram） | 新建类实现 `OutputBackend` 协议，在 `main.py` 中 `emitter.add_backend()` | `backends.py`（或新文件）+ `main.py` |
| **添加新的事件类型** | 在 `types.py` 中新增 `OutputEvent` 子类 | `types.py` + 产生事件的组件 + 处理事件的后端 |
| **让某个后端响应更多事件** | 在后端的 `handle()` 中增加 `isinstance` 分支 | 对应后端文件 |
| **让某个后端不再响应某类事件** | 在 `handle()` 中删除或 return 对应分支 | 对应后端文件 |
| **新增输出来源**（如新的 Agent 类型） | 在调用 `emitter.emit()` 时传入新的 `source` 值 | 新 Agent 组件 |
| **过滤特定来源的事件** | 在后端 `handle()` 中检查 `event.source` | 对应后端文件 |

---

## 11. 与旧系统的关系

`OutputEmitter` 是原 `ReplyDispatcher` 的**超集替代**：

| 旧 (core/reply/) | 新 (core/output/) |
|---|---|
| `ReplyDispatcher` | `OutputEmitter` |
| `ReplyEnvelope` | `FinalReplyEvent` + 3 种新事件 |
| `ReplyBackend` 协议 | `OutputBackend` 协议 |
| `FutureBackend` | `FutureBackend`（逻辑不变） |
| `CliBackend` | `LogBackend`（增强，处理所有事件类型） |
| `FeishuBackend` | `FeishuBackend`（逻辑不变，可扩展） |
| 无 | `WebSocketBackend`（新增） |

`core/reply/` 目录保留作为参考，确认新系统稳定后可整体删除。
