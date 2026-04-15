# Claude Code KAIROS 自治模式深度分析

> 基于 claudecode-src 源码的完整实现分析，用于 Heartclaw 借鉴参考。

## 一、KAIROS 是什么

KAIROS 是 Claude Code 的**常驻自治 Agent 模式**。核心理念：Agent 永不退出，在没有用户指令时也保持"活着"，自主寻找有意义的工作来做。

**一句话概括实现原理**：用最简单的数据结构（优先级队列 + 互斥锁 + 尾递归 tick）实现 Agent 的持续运行循环。不需要多线程、不需要后台进程、不需要复杂的调度器。

## 二、核心架构：单进程优先级队列

### 2.1 统一消息队列

KAIROS 的所有消息（用户输入、tick、cron 触发、子 Agent 通知）都经过**同一个优先级队列**，由同一个 `run()` 函数串行处理。

**优先级定义** (`utils/messageQueueManager.ts`)：

```typescript
const PRIORITY_ORDER: Record<QueuePriority, number> = {
  now: 0,     // 最高：用户中断（Ctrl+C）
  next: 1,    // 中等：用户正常输入
  later: 2,   // 最低：tick / cron 触发 / 子 Agent 通知
}
```

**入队方式**：

| 消息类型 | 优先级 | 入队函数 |
|---------|--------|---------|
| 用户正常输入 | `next` (1) | `enqueue()` — 默认 priority: 'next' |
| 用户中断 (Ctrl+C) | `now` (0) | `enqueue({ priority: 'now' })` |
| Proactive Tick | `later` (2) | `enqueue({ priority: 'later', isMeta: true })` |
| Cron 定时任务 | `later` (2) | `enqueuePendingNotification()` |
| 子 Agent 完成通知 | `later` (2) | `enqueuePendingNotification()` |

`dequeue()` 总是弹出优先级最高的消息，因此用户输入永远能抢先于 tick 被处理。

### 2.2 互斥执行器 `run()`

整个进程只有一个 `run()` 函数，通过 `running` 布尔标志实现互斥：

```typescript
// cli/print.ts
const run = async () => {
    if (running) {
      return    // 直接 return，什么都不做
    }
    running = true
    // ...处理消息...
    running = false
}
```

**关键特性**：
- 同一时间只能处理一条消息（一个 turn）
- 一个 turn 启动后不会被打断（除非 `priority: 'now'` 的中断信号通过 `abortController.abort()` 终止 API 调用）
- turn 结束后才检查队列中的下一条消息

### 2.3 `run()` 结束后的尾部调度

`run()` 完成后的检查逻辑是整个 KAIROS 的核心（`cli/print.ts`）：

```typescript
// run() 的 finally 块之后
running = false

// 步骤 1：检查队列是否有待处理消息
if (peek(isMainThread) !== undefined) {
    void run()    // 有消息 → 立刻处理（跳过 tick 注入！）
    return
}

// 步骤 2：只有队列空了，才注入 tick
if (proactiveModule?.isProactiveActive() &&
    !proactiveModule.isProactivePaused()) {
    if (peek(isMainThread) === undefined && !inputClosed) {
        scheduleProactiveTick()
        return
    }
}
```

**优先级链**：用户消息 > tick。如果用户在 turn 执行期间发了消息，turn 结束后会优先处理用户消息，不注入 tick。

## 三、Tick 心跳循环——KAIROS 的核心机制

### 3.1 Tick 是什么

Tick 是一个 XML 包裹的时间戳消息，作为 `isMeta: true` 的用户消息注入 LLM 对话：

```xml
<tick>10:35:42 AM</tick>
```

LLM 收到后把它当作"你醒了，该干嘛了？"的信号。

### 3.2 Tick 注入机制

```typescript
// cli/print.ts
const scheduleProactiveTick = () => {
    setTimeout(() => {
        if (!proactiveModule?.isProactiveActive() ||
            proactiveModule.isProactivePaused() ||
            inputClosed) {
            return
        }
        const tickContent = `<tick>${new Date().toLocaleTimeString()}</tick>`
        enqueue({
            mode: 'prompt',
            value: tickContent,
            uuid: randomUUID(),
            priority: 'later',    // 最低优先级
            isMeta: true,          // 系统消息，不显示给用户
        })
        void run()
    }, 0)   // setTimeout(0) —— 关键技巧！
}
```

**`setTimeout(0)` 的精妙之处**：

不是"立即执行"——它把回调放到 Node.js 事件循环的下一轮。这意味着：

1. `run()` 完成 → `running = false`
2. `setTimeout(0)` 注册回调，但不立即执行
3. 事件循环先检查 I/O：如果用户在这个微小窗口内输入了消息，stdin 的 `data` 事件回调先执行，用户消息以 `priority: 'next'` 入队
4. 然后 setTimeout 回调执行：tick 以 `priority: 'later'` 入队
5. `run()` 被调用：`dequeue()` 取出优先级最高的用户消息（next > later）

**这就是为什么用户输入永远不会被 tick 阻塞——即使它们共享同一个进程和同一个队列。**

### 3.3 Tick 的自循环

Tick 不是定时器触发的，而是**事件驱动的尾递归自循环**：

```
turn 结束 → 队列空？→ 注入 tick → run() → LLM 决策 → turn 结束 → 队列空？→ 注入 tick → ...
```

**LLM 在 tick 中的两条路**：

1. **有事做** → 调用工具 → 完成后 turn 结束 → 系统自动注入下一个 tick（间隔 ≈ 0）
2. **无事做** → 调用 `Sleep(N秒)` → 等待后 turn 结束 → 系统自动注入下一个 tick（间隔 ≈ N 秒）

**关键分工**：
- **tick 注入**：系统自动，无条件，LLM 没有决定权
- **tick 间隔**：LLM 通过 Sleep 控制——这是它的"节奏感"
- **tick 内容**：LLM 全权决定做什么或者不做什么

### 3.4 SleepTool

Sleep 是 KAIROS 模式专属的工具，仅在 `isProactiveActive()` 为 true 时才出现在工具列表中：

```typescript
// tools/SleepTool/prompt.ts
export const SLEEP_TOOL_PROMPT = `Wait for a specified duration.
The user can interrupt the sleep at any time.

Use this when the user tells you to sleep or rest, when you have nothing
to do, or when you're waiting for something.

You may receive <tick> prompts — these are periodic check-ins. Look for
useful work to do before sleeping.

Each wake-up costs an API call, but the prompt cache expires after 5 minutes
of inactivity — balance accordingly.`
```

LLM 需要权衡的成本考量：
- Sleep 太短 → API 调用费用太高
- Sleep 太长 → 超过 5 分钟 prompt cache 过期，下次调用变贵
- 等待外部进程时（如编译、测试）→ 适当延长 Sleep
- 主动迭代代码时 → 缩短或直接连续工作

## 四、激活条件与初始化流程

### 4.1 多层门控

KAIROS 的激活需要同时满足多个条件：

1. **编译时特性门控**：`feature('KAIROS')` 或 `feature('PROACTIVE')` — 构建时的死码消除标志
2. **运行时门控**：GrowthBook 特性开关 `tengu_kairos` 做远程灰度控制
3. **显式激活方式**：
   - `--assistant` 标志（Agent SDK 守护进程模式）
   - `--proactive` 标志
   - 环境变量 `CLAUDE_CODE_PROACTIVE=true`
   - API 远程控制接口开启
4. **信任检查**：目录必须经过 trust dialog 信任确认（防止恶意仓库自动触发）

```typescript
// main.tsx
let kairosEnabled = false;
if (feature('KAIROS') && assistantModule?.isAssistantMode() && ...) {
    kairosEnabled = assistantModule.isAssistantForced() ||
                    (await kairosGate.isKairosEnabled());
    if (kairosEnabled) {
        opts.brief = true;              // 强制简洁模式
        setKairosActive(true);          // 全局状态锁存
        assistantTeamContext = await assistantModule.initializeAssistantTeam();
    }
}
```

### 4.2 初始化关键顺序

```typescript
// main.tsx — 必须在 getTools() 之前激活
// 否则 SleepTool.isEnabled()（检查 isProactiveActive()）会返回 false
// Sleep 工具不会出现在工具列表中
maybeActivateProactive(options);
let tools = getTools(toolPermissionContext);
```

### 4.3 第一个 Tick 的产生

**交互模式** (`claude --proactive`)：

必须等用户发第一条消息。用户不输入 → KAIROS 等于没启动。

```
用户输入 → enqueue → run() → turn 结束 → 队列空 → scheduleProactiveTick() → 第一个 tick → 自循环开始
```

**守护进程模式** (`--assistant`)：

有三个额外的触发源可以绕过"等用户输入"：

1. **SDK 远程控制激活**：

```typescript
// cli/print.ts — SDK 客户端发送 set_proactive
if (req.enabled) {
    if (!proactiveModule!.isProactiveActive()) {
        proactiveModule!.activateProactive('command')
        scheduleProactiveTick!()    // 直接注入第一个 tick！
    }
}
```

2. **Cron 定时任务到期**：

```typescript
// cli/print.ts
cronScheduler = createCronScheduler({
    onFire: prompt => {
        enqueue({ mode: 'prompt', value: prompt, priority: 'later', isMeta: true })
        void run()    // Cron 到期直接踢 run()
    },
})
```

3. **错过任务检测**（重启后发现之前的 one-shot 任务没触发）：

```typescript
// utils/cronScheduler.ts
const missed = findMissedTasks(next, now).filter(t => !t.recurring)
if (missed.length > 0) {
    onFire(buildMissedTaskNotification(missed))   // 直接触发
}
```

## 五、用户交互与 KAIROS 的协作

### 5.1 Agent 执行用户任务时

**KAIROS tick 完全不运行**。因为 `run()` 互斥——`running = true` 期间任何新的 `run()` 调用直接 return。tick 只在 `run()` 结束后的"空闲检查点"才被注入。

### 5.2 用户在 turn 执行期间发消息

```
run() 正在执行（处理 tick 或上一条用户消息）
    ← 用户发送新消息
       enqueue({ value: "...", priority: 'next' })
       void run() → if(running) return → 无效
       但消息已在队列中
    
run() 结束 → running = false → 检查队列
    → 发现用户消息 (priority: next) → 处理用户消息
    → 跳过 tick 注入
```

### 5.3 用户在 Sleep 期间发消息

Sleep 执行时 `run()` 处于 `running = true`（在 await Sleep 的 Promise）：

1. 用户消息入队（priority: next）
2. `void run()` → if(running) return → 无效
3. Sleep 到期 → 工具返回 → turn 结束
4. 检查队列 → 发现用户消息 → 处理用户消息（跳过 tick）

**用户消息不会被丢失，但不会提前唤醒 Sleep。** 除非用户按 Esc/Ctrl+C（Interrupt）。

### 5.4 暂停/恢复机制

```typescript
// 用户按 Esc → 暂停 tick 循环
proactiveModule?.pauseProactive();

// 用户提交新输入 → 恢复 tick 循环
proactiveModule?.resumeProactive();
```

### 5.5 错误熔断（Error Circuit Breaker）

API 报错时自动暂停 tick，防止 tick → 报错 → tick → 报错 的死循环：

```typescript
// screens/REPL.tsx
if (newMessage.isApiErrorMessage) {
    proactiveModule?.setContextBlocked(true);   // 阻塞 tick
} else if (newMessage.type === 'assistant') {
    proactiveModule?.setContextBlocked(false);  // 恢复 tick
}
```

Context compaction（上下文压缩）完成后也会解除阻塞。

## 六、系统提示词——LLM 行为指导

KAIROS 模式下，系统提示词会注入完整的自治行为指导（`constants/prompts.ts`）：

```
# Autonomous work

You are running autonomously. You will receive `<tick>` prompts that keep
you alive between turns — just treat them as "you're awake, what now?"

## Pacing
Use the Sleep tool to control how long you wait between actions.
If you have nothing useful to do on a tick, you MUST call Sleep.

## First wake-up
On your very first tick, greet the user briefly and ask what they'd like
to work on. Do not start exploring unprompted.

## Subsequent wake-ups
Look for useful work. Ask yourself: what don't I know yet? What could go
wrong? What would I want to verify?

If a tick arrives and you have no useful action, call Sleep immediately.
Do not output text narrating that you're idle.

## Terminal focus
- Unfocused: lean into autonomous action — make decisions, commit, push
- Focused: be more collaborative — surface choices, ask before big changes

## Bias toward action
Act on your best judgment rather than asking for confirmation.
Read files, search code, run tests, check types — all without asking.
```

### 6.1 终端焦点感知

KAIROS 模式下会探测用户终端是否聚焦，并注入上下文：

```typescript
// screens/REPL.tsx
...((feature('PROACTIVE') || feature('KAIROS')) &&
    proactiveModule?.isProactiveActive() &&
    !terminalFocusRef.current ? {
    terminalFocus: 'The terminal is unfocused — the user is not actively watching.'
} : {})
```

### 6.2 Context Compaction 后的连续性

上下文压缩后，系统提示词告诉 LLM 保持连续性：

```
You are running in autonomous/proactive mode. This is NOT a first wake-up —
you were already working autonomously before compaction. Continue your work
loop: pick up where you left off. Do not greet the user or ask what to work on.
```

## 七、KAIROS 与 Cron 定时任务的协作

在 KAIROS 模式下，Cron 并不冗余——它们协同工作：

```typescript
// screens/REPL.tsx
// Assistant mode bypasses the isLoading gate
// (the proactive tick → Sleep → tick loop would otherwise starve the scheduler)
const assistantMode = store.getState().kairosEnabled;
useScheduledTasks!({
    isLoading,
    assistantMode,    // KAIROS 模式下绕过 isLoading 门控
    setMessages
});
```

**KAIROS 模式下 Cron 调度器会绕过 `isLoading` 检查**——因为 tick 循环让 Agent 几乎一直处于 busy 状态，不绕过的话 Cron 任务永远无法触发。

### KAIROS + Cron 定位区分

| 维度 | KAIROS Tick | Cron 定时任务 |
|------|------------|-------------|
| 调度本质 | 事件驱动的自循环（turn 结束 → tick → turn → ...） | 时间驱动的外部调度器（1 秒轮询 setInterval） |
| 间隔机制 | LLM 通过 Sleep 自主控制 | Cron 表达式精确定义 |
| 决策层 | LLM 每次 tick 都做决策 | 无智能，到时间就把 prompt 注入 |
| 任务来源 | LLM 自主判断 | 创建时固定的 prompt 字符串 |
| 适用场景 | 持续自治工作：值班、巡检、持续开发 | 精确定时：提醒、定期报告 |

### 子 Agent 强制异步

KAIROS 模式下，所有 AgentTool 调用强制走异步后台路径：

```typescript
// tools/AgentTool/AgentTool.tsx
const assistantForceAsync = feature('KAIROS') ? appState.kairosEnabled : false;
const shouldRunAsync = (run_in_background || assistantForceAsync || ...) && !isBackgroundTasksDisabled;
```

防止子 Agent 阻塞主 tick 循环。

## 八、完整运行时序图

```
┌─────────────────────────────────────────────────────────────────┐
│                      进程启动阶段                                │
│                                                                 │
│   main.tsx: 门控检查 → activateProactive()                      │
│   │                                                             │
│   ├── 交互模式: REPL 等待用户键盘输入                             │
│   │   └── 一直不输入 → 一直等着 → tick 永远不开始                  │
│   │       └── 用户输入第一条 → run() → turn 结束 → tick 开始循环   │
│   │                                                              │
│   └── 守护进程模式: 多个触发源                                    │
│       ├── SDK 客户端 set_proactive → 直接注入第一个 tick           │
│       ├── 初始 prompt (stdin) → enqueue → run()                  │
│       ├── Cron 任务到期 → enqueue → run()                        │
│       └── 错过任务检测 → onFire → enqueue → run()                │
│                                                                  │
│   所有路径最终都汇入: 第一个 run() 完成 → tick 自循环启动          │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                      稳态运行阶段                                │
│                                                                 │
│   run() ─┬─ 处理消息 ─→ running=false ─→ 队列尾部检查            │
│          │                                    │                  │
│          │                           ┌────────┴────────┐         │
│          │                           │                 │         │
│          │                      队列有消息          队列空        │
│          │                      (用户/cron)     (无人说话)       │
│          │                           │                 │         │
│          │                      void run()    scheduleProactive  │
│          │                      (跳过tick)     Tick()            │
│          │                           │          │                │
│          │                           │    setTimeout(0)          │
│          │                           │          │                │
│          │                           │    ┌─────┴──────┐        │
│          │                           │    │ 让出事件循环 │        │
│          │                           │    │ 检查 stdin  │        │
│          │                           │    └─────┬──────┘        │
│          │                           │          │               │
│          │                           │    有用户消息? ──YES──→   │
│          │                           │          │               │
│          │                           │    NO: 注入 tick          │
│          │                           │          │               │
│          │                           ▼          ▼               │
│          └────────────────── run() 重新启动 ◄───┘               │
│                                                                 │
│   中断机制:                                                      │
│   ├── 用户 Esc → pauseProactive() → tick 不再注入               │
│   ├── API 错误 → setContextBlocked(true) → tick 暂停            │
│   ├── Context 满 → 自动 compaction → 清除 blocked → tick 恢复    │
│   └── 用户再次输入 → resumeProactive() → tick 恢复               │
└─────────────────────────────────────────────────────────────────┘
```

## 九、Heartclaw 借鉴要点

### 9.1 核心设计可直接复用的部分

1. **优先级消息队列**：用一个队列统一管理所有消息来源（用户输入、定时任务、系统 tick），通过优先级保证用户体验
2. **互斥执行器**：单进程、单 `run()` 函数、`running` 布尔锁，避免并发复杂性
3. **尾递归 tick**：turn 结束后检查队列，空则注入 tick 自循环——极简的自治循环实现
4. **setTimeout(0) 让出事件循环**：确保用户消息在 tick 之前被处理
5. **错误熔断**：API 错误时停止 tick，防止死循环

### 9.2 KAIROS vs Heartclaw Heartbeat 对比

| 维度 | KAIROS Tick | Heartclaw Heartbeat |
|------|------------|-------------------|
| 节奏 | LLM 通过 Sleep 自适应（0 秒到数分钟） | 固定 30 分钟 |
| 任务来源 | LLM 自主判断 + 历史对话上下文 | `HEARTBEAT.md` 文件 |
| 决策层数 | 1 层（每次 tick 直接决策） | 2 层（执行前判断 + 执行后通知评估） |
| 成本控制 | LLM 自律 + prompt cache 5 分钟窗口引导 | 固定间隔天然限制 |
| 用户操控 | 对话中说话或改 agent 定义 | 编辑 HEARTBEAT.md 文件 |

### 9.3 可以融合的方向

1. **将 Heartbeat 改造为 tick 自循环模式**：不再固定 30 分钟，而是 LLM 每次决定下次唤醒间隔
2. **保留 HEARTBEAT.md 作为 file-as-interface**：这是 Heartclaw 的优势——用户可以随时编辑文件改变 Agent 行为，比 KAIROS 的纯对话控制更直观
3. **引入优先级队列**：统一管理用户输入、心跳 tick、cron 定时任务
4. **添加错误熔断和暂停/恢复机制**：防止失控循环

### 9.4 需要注意的成本风险

KAIROS 的成本完全依赖 LLM 的"自律"——如果 LLM 不调 Sleep 或 Sleep 时间太短，API 调用会飙升。Claude Code 通过以下手段缓解：

- 系统提示词反复强调"each wake-up costs an API call"
- 提及 prompt cache 5 分钟过期机制引导合理 Sleep 时长
- `isMeta: true` 让 tick 消息不占用上下文
- 错误熔断防止错误循环烧钱

Heartclaw 的固定间隔 + 双层 LLM 评估在成本控制上更稳健，两种方案可以取长补短。
