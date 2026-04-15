# KAIROS队列的执行顺序

## 一、队列的本质

KAIROS（Assistant Mode）的运行依赖于一个全局的 `commandQueue`，位于 `utils/messageQueueManager.ts`。它不是 React state，而是一个模块级别的数组，配合 `useSyncExternalStore` 让 REPL 组件订阅其变化。

队列中的每个元素是一个 `QueuedCommand`，核心字段包括：
- `value`: 实际内容（字符串或 `ContentBlockParam[]`）
- `priority`: `'now' | 'next' | 'later'`
- `mode`: `'prompt' | 'bash' | 'task-notification'` 等
- `isMeta`: 是否为系统生成（如 tick）
- `agentId`: 是否属于子任务

## 二、优先级与出队规则

出队不是简单的 `shift()`，而是**扫描整个数组取优先级最高者**：

```
now(0) > next(1) > later(2)
```

同优先级按 FIFO 顺序。

| 来源 | 默认优先级 | 说明 |
|------|-----------|------|
| 用户输入 | `next` | 直接入队或立即执行 |
| tick | `next` | 系统注入的唤醒信号 |
| cron 任务 | `later` | 等主线程空闲后再处理 |
| 任务通知 | `later` | 不抢占用户输入 |

**注意**：tick 和用户输入在队列算法的数值上是同级的 `next`，但在系统设计中**并非平权**。tick 的入队受 `pauseProactive` 和队列状态等多重约束，本质上是"间隙维持信号"，而用户输入是对话主体。

## 三、队列消费的核心机制

真正消费队列的是 `hooks/useQueueProcessor.ts` + `utils/queueProcessor.ts`，它们同时监听两个信号：

1. `queryGuard`: 控制当前是否有 API 请求在执行
2. `commandQueue`: 队列是否有待处理消息

只有当以下条件同时满足时才会出队：
- `queryGuard.isActive === false`（没有 API turn 在跑）
- `queue.length > 0`
- 没有 active 的 local JSX UI 阻挡输入

## 四、QueryGuard 状态机

```
idle → dispatching (reserve)
idle → running (tryStart, 直接提交)
dispatching → running (tryStart, 队列消费路径)
running → idle (end / forceEnd)
dispatching → idle (cancelReservation)
```

`isActive` 在 `dispatching` 和 `running` 时都为 `true`，防止并发执行。

## 五、启动后的完整时序

### 1. 启动初始化
- `maybeActivateProactive()` 激活 proactive 模式
- `maybeActivateBrief()` 激活 `SendUserMessage` 工具
- 系统提示词切换为精简 proactive 版
- `commandQueue = []`, `queryGuard = idle`

### 2. 第一次 tick 注入
当检测到 `isLoading = false` 且队列为空时，`useProactive` 注入第一个 tick：
```xml
<tick>2026-04-13T10:00:00+08:00</tick>
```

系统提示词要求模型在首次 tick 时：
> "greet the user briefly and ask what they'd like to work on"

### 3. 队列处理器检测到 tick
`useQueueProcessor` effect 触发，调用 `processQueueIfReady()`，从队列中捞出 tick，执行 `executeQueuedInput([tick])`。

### 4. 执行 tick 发起 API 调用
- `queryGuard.reserve()` → `dispatching`
- `queryGuard.tryStart()` → `running`
- 发送 API 请求，模型收到 tick

如果用户尚未输入任何内容，模型会问候用户并询问需求，然后 turn 结束。

### 5. Turn 结束后的队列检查
`queryGuard.end()` 触发 `useQueueProcessor` 重新检查：
- 如果队列空 → 无事发生，等待下一个 tick
- 如果队列有消息 → 继续消费

### 6. 后续 tick 与 Sleep
当再次空闲时，`useProactive` 注入下一个 tick。模型在这个 turn 中自主决定：
- **有事做** → 调用 Read / Bash / Edit / Agent 等工具
- **没事做** → 调用 `Sleep(300)` 工具

**Sleep 的本质**：
- 是一个可中断的工具调用
- 内部启动 `setTimeout`，同时返回 tool_result
- 该 turn 在 tool_result 返回后正式结束
- 在 Sleep 期间 `queryGuard` 回到 `idle`，系统等待下一个事件

### 7. 用户输入打断 Sleep
用户在 Sleep 期间打字提交时：
1. `onSubmit()` 中调用 `proactiveModule?.pauseProactive()`，**暂停 tick 生产**
2. 如果当前有可中断工具（如 Sleep）在运行，`abortController.abort('interrupt')` **中断 Sleep**
3. Sleep 中断后 turn 结束，`queryGuard.end()` 触发队列检查
4. `useQueueProcessor` 出队用户输入并执行
5. 用户输入的完整 turn 处理完后，`resumeProactive()` 恢复 tick

## 六、批量合并（Batching）机制

`queueProcessor.ts` 在出队时会批量合并同 `mode` 的消息：

```ts
const commands = dequeueAllMatching(
  cmd => isMainThread(cmd) && !isSlashCommand(cmd) && cmd.mode === targetMode
)
```

如果队列里同时存在：
```
[tick1, tick2, "用户输入"]
```

它们 `mode` 都是 `'prompt'`，会被**一起捞出**，在同一个 API turn 中发给模型。模型侧的系统提示词教导：

> "Multiple ticks may be batched into a single message. Just process the latest one."

这意味着 batch 中前面的 tick 会被忽略，**只有用户输入是有效载荷**。

## 七、tick 与用户输入的权力层级

虽然队列数值上都是 `priority: 'next'`，但实际权力完全不同：

| 维度 | 用户输入 | tick |
|------|---------|------|
| 入队权限 | 无条件 | 受队列状态和 `useProactive` 约束 |
| 生产控制 | 自主 | 被 `pauseProactive` 管制 |
| 中断权 | 可中断 Sleep 和 proactive | 不能中断用户 turn |
| batch 待遇 | 有效载荷 | 可被模型忽略 |
| 语义地位 | 对话主体 | 间隙维持信号 |

`handleIncomingPrompt` 中有明确的防御逻辑：
```ts
if (getCommandQueue().some(cmd => cmd.mode === 'prompt' || cmd.mode === 'bash')) {
  return false; // 队列里已有用户输入，拒绝某些外部消息入队
}
```

## 八、常见误解纠正

### 误解 1：系统检查队列为空后自动让模型 Sleep
**事实**：Sleep 是模型在 turn 内部**自主调用**的工具，不是系统层面的自动决策。系统只负责在空闲时注入 tick，模型收到 tick 后自己决定 Sleep 还是工作。

### 误解 2：tick 和用户输入平级 FIFO，所以不会互相压制
**事实**：仅靠 FIFO 无法防止压制。真正的保护来自：
1. `pauseProactive` 在用户输入期间暂停 tick
2. `handleIncomingPrompt` 的防御性拒绝
3. tick 只在 `isLoading = false` 且队列为空时注入
4. batch 合并后模型侧主动忽略旧 tick

### 误解 3：队列处理器在每个 tick 时检查队列
**事实**：队列处理器（`useQueueProcessor`）是一个 React effect，它在 `queryGuard` 状态变化或队列引用变化时触发。它不会周期性轮询，而是**事件驱动**的。

## 九、一句话总结

> KAIROS 的队列是一个优先级驱动的全局事件收敛器。用户输入是主导者，tick 是间隙中的维持信号，Sleep 是模型自主选择的"冬眠工具"。整个系统通过 `QueryGuard` + `useQueueProcessor` 保证：任何时刻只有一个 API turn 在执行，而用户输入永远优先于机器唤醒。