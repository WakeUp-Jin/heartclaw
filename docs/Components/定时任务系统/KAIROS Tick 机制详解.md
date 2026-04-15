# KAIROS Tick 机制详解

> 本文聚焦 Claude Code KAIROS 自治模式中 **Tick 的传入方式、生命周期、消息队列去重** 三个核心问题。

---

## 一、Tick 是什么

Tick 是 KAIROS/PROACTIVE 自治模式下的心跳唤醒信号。当 Agent 没有用户输入时，系统主动向模型发送一条 `<tick>` 消息，相当于问模型：

> "你还醒着吗？现在该做点什么？"

其本质是一个**携带 XML 标签的普通 user message**，直接插入到发给 Anthropic API 的 `messages` 数组中。

---

## 二、Tick 的构造与注入

### 2.1 字符串构造

Tick 内容由当前用户本地时间组装而成：

```typescript
// cli/print.ts:1845
const tickContent = `<${TICK_TAG}>${new Date().toLocaleTimeString()}</${TICK_TAG}>`
// 例如: <tick>3:45:22 PM</tick>
```

定义在 `constants/xml.ts`：

```typescript
export const TICK_TAG = 'tick'
```

### 2.2 入队方式

Tick 被当作一条系统生成的 prompt 入队，优先级为 `later`（最低），并标记 `isMeta: true`：

```typescript
// cli/print.ts
enqueue({
  mode: 'prompt' as const,
  value: tickContent,
  uuid: randomUUID(),
  priority: 'later',
  isMeta: true,
})
void run()
```

在交互式 REPL（`screens/REPL.tsx:4079`）中类似：

```typescript
useProactive?.({
  isLoading: isLoading || initialMessage !== null,
  // ...
  onSubmitTick: (prompt: string) => handleIncomingPrompt(prompt, { isMeta: true }),
  onQueueTick: (prompt: string) => enqueue({
    mode: 'prompt',
    value: prompt,
    isMeta: true
  })
});
```

### 2.3 最终形态——发给模型的 messages 参数

Tick 进入正常的 query 流程后，最终作为 Anthropic API `messages` 数组中的一个 `user` role text block：

```json
{
  "role": "user",
  "content": [
    { "type": "text", "text": "<tick>3:45:22 PM</tick>" }
  ]
}
```

系统提示词（`constants/prompts.ts:866`）告诉模型：

> *"You will receive `<tick>` prompts that keep you alive between turns — just treat them as 'you're awake, what now?' The time in each `<tick>` is the user's current local time."*

---

## 三、Tick 在消息队列中的位置

所有消息都经过 **统一 Command Queue**（`utils/messageQueueManager.ts`）。

**优先级定义**：

```typescript
const PRIORITY_ORDER: Record<QueuePriority, number> = {
  now: 0,    // 最高：用户中断
  next: 1,   // 中等：用户正常输入
  later: 2,  // 最低：tick / cron / 子 Agent 通知
}
```

**Tick 的入队特性**：
- `priority: 'later'` —— 永远低于用户输入（`next`）
- `isMeta: true` —— 系统生成，不显示在 UI 输入历史中
- 通过 `handleIncomingPrompt` 或 `enqueue` 进入队列后，由 `dequeue()` 在 turn 结束时按优先级弹出

### 为什么用户输入不会被 Tick 阻塞？

`cli/print.ts` 的 `run()` 结束后使用 `setTimeout(0)` 注入 tick：

```typescript
setTimeout(() => {
  // ...注入 tick
  enqueue({ ...tick... })
  void run()
}, 0)
```

这个 `setTimeout(0)` 把 tick 注册放到事件循环的下一轮。如果在当前 turn 结束的微小窗口内用户输入了消息，stdin 事件回调会先执行，用户消息以 `priority: 'next'` 入队；随后 setTimeout 回调执行，tick 以 `priority: 'later'` 入队。下一次 `dequeue()` 会优先取用户消息，tick 被延后。

---

## 四、Tick 的 UI 隐藏

虽然 Tick 存在于消息历史中并参与上下文，但前端渲染时会被过滤掉。

`components/messages/UserTextMessage.tsx:54`：

```typescript
if (extractTag(param.text, TICK_TAG)) {
  return null
}
```

因此用户在对话界面看不到 `<tick>` 消息，但模型确实能看到它并据此做出响应（例如调用 `SleepTool` 决定睡多久）。

---

## 五、Tick 相关的三层去重（"祛痘"）

### 5.1 Progress Tick 替换——防止消息数组无限膨胀

Sleep、Bash 等工具在执行期间会每秒 emit 一个 `progress` 消息。如果不加控制， sleep 一小时就能产生 3600 条 progress 消息。代码里观察到了 **13k+ 条 progress** 和 **120MB transcript**。

解决方案：`screens/REPL.tsx:2609`

```typescript
} else if (newMessage.type === 'progress' && isEphemeralToolProgress(newMessage.data.type)) {
  setMessages(oldMessages => {
    const last = oldMessages.at(-1);
    if (last?.type === 'progress' && last.parentToolUseID === newMessage.parentToolUseID && last.data.type === newMessage.data.type) {
      const copy = oldMessages.slice();
      copy[copy.length - 1] = newMessage;
      return copy;
    }
    return [...oldMessages, newMessage];
  });
}
```

**规则**：如果最后一条消息是同个 tool call 的同类型 ephemeral progress，**直接替换最后一条，不追加**。这保证了长 sleep 期间 messages 数组只会在末尾保留最新一条 progress tick。

> 注意：`agent_progress` / `hook_progress` / `skill_progress` **不替换**，因为它们代理了完整状态链，UI 需要看到历史。

### 5.2 Cron Scheduler 的 inFlight 去重

定时任务（`/loop`）触发后删除是异步的（写回 `.claude/scheduled_tasks.json`）。为了防止在异步删除完成前被下一个 check tick 重复触发：

```typescript
// utils/cronScheduler.ts
const inFlight = new Set<string>()

function process(t: CronTask) {
  if (inFlight.has(t.id)) return   // 已经在执行，跳过
  // ...触发任务...
  inFlight.add(t.id)
  void removeCronTasks([t.id], dir)
    .finally(() => inFlight.delete(t.id))
}
```

### 5.3 Bridge Echo 去重

本地/远程 Mailbox Bridge 使用 `BoundedUUIDSet` 环形缓冲区（`bridge/bridgeMessaging.ts`）过滤：
- WebSocket 回环消息（自己发出去的消息被 bounce 回来）
- 服务端重投递导致的重复 tick/prompt

---

## 六、熔断保护：防止 tick → error → tick 死循环

当模型在 tick 后遇到 API 错误（auth failure、rate limit、blocking limit）时，系统会暂停后续 tick 注入，防止无限烧钱循环。

`screens/REPL.tsx:2636`：

```typescript
if (newMessage.type === 'assistant' && 'isApiErrorMessage' in newMessage && newMessage.isApiErrorMessage) {
  proactiveModule?.setContextBlocked(true);   // 阻塞 tick
} else if (newMessage.type === 'assistant') {
  proactiveModule?.setContextBlocked(false);  // 恢复 tick
}
```

解除阻塞的条件：
- 上下文 compaction 成功完成
- 收到正常的 assistant 回复

---

## 七、Tick 的生命周期时序图

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│   系统/调度器    │     │  命令队列     │     │   LLM / run()   │
└────────┬────────┘     └──────┬───────┘     └────────┬────────┘
         │                     │                      │
         │  队列空且满足条件    │                      │
         │────────────────────►│                      │
         │  enqueue tick       │                      │
         │  (priority: later)  │                      │
         │                     │                      │
         │                     │◄─────────────────────│ turn 结束
         │                     │   dequeue()          │
         │                     │   取出 tick          │
         │                     │─────────────────────►│
         │                     │                      │
         │                     │                      │ LLM 看到 <tick>
         │                     │                      │ 决定：做事 或 Sleep
         │                     │                      │
         │                     │◄─────────────────────│ turn 结束
         │  队列空？            │                      │
         │────────────────────►│                      │
         │  是 → 再次注入 tick  │                      │
         │  (循环往复)          │                      │
```

---

## 八、关键源码索引

| 功能 | 文件路径 | 行号 |
|------|---------|------|
| Tick 标签定义 | `constants/xml.ts` | 25 |
| Tick 内容构造（headless） | `cli/print.ts` | 1845 |
| Tick 入队（REPL 交互） | `screens/REPL.tsx` | 4079-4091 |
| Tick Prompt 系统提示词 | `constants/prompts.ts` | 866 |
| 统一命令队列 | `utils/messageQueueManager.ts` | 52-193 |
| Progress Tick 替换去重 | `screens/REPL.tsx` | 2609-2628 |
| Cron inFlight 去重 | `utils/cronScheduler.ts` | 170-344 |
| Bridge Echo 去重 | `bridge/bridgeMessaging.ts` | BoundedUUIDSet |
| API 错误熔断 | `screens/REPL.tsx` | 2636-2641 |
| Tick UI 隐藏 | `components/messages/UserTextMessage.tsx` | 54 |
| SleepTool 提示词 | `tools/SleepTool/prompt.ts` | 1 |
