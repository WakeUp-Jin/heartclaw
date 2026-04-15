# Nanobot 定时任务系统分析（Cron + Heartbeat）

## 一、系统概述

Nanobot 实现了一套**自研的轻量级定时任务系统**，由两个互补的子系统组成：

- **Cron Service**：核心调度引擎，精确定时执行预设任务
- **Heartbeat Service**：智能心跳巡检，周期性唤醒 LLM 判断是否需要行动

两者共同构成了 Agent 的"自主时间感知"能力——不需要用户触发，Agent 也能在正确的时间做正确的事。

### 核心特性

- 三种调度模式：一次性（at）、固定间隔（every）、cron 表达式
- 纯 asyncio 实现，不依赖 APScheduler 等重量级框架
- JSON 文件持久化 + FileLock 文件锁保证多实例安全
- Action 日志（WAL）机制支持非运行状态下的任务修改
- Agent 可通过 CronTool 自主创建/管理定时任务
- 支持 IANA 时区的 cron 表达式（依赖 croniter 库）
- LLM 驱动的智能心跳决策（两阶段：先判断再执行）
- 执行后 LLM 评估是否值得通知用户

### 文件结构

```
nanobot/
├── cron/
│   ├── __init__.py          # 模块导出
│   ├── types.py             # 数据类型定义（CronJob, CronSchedule, CronStore 等）
│   └── service.py           # 调度引擎核心（CronService）
├── heartbeat/
│   ├── __init__.py          # 模块导出
│   └── service.py           # 心跳服务（HeartbeatService）
├── agent/tools/
│   └── cron.py              # CronTool — 让 Agent 可以自主管理定时任务
├── utils/
│   └── evaluator.py         # 执行后评估器（判断是否通知用户）
├── skills/cron/
│   └── SKILL.md             # Cron 技能描述文档
├── templates/
│   ├── HEARTBEAT.md         # 心跳任务模板文件
│   └── AGENTS.md            # Agent 行为指引（含 cron/heartbeat 使用规范）
└── cli/
    └── commands.py           # 启动入口，组装 CronService + HeartbeatService
```

---

## 二、Cron Service — 核心调度引擎

### 2.1 三种调度模式

Nanobot 没有使用标准 5 字段 cron 作为唯一的时间格式，而是定义了三种调度类型：

| 模式 | `kind` 值 | 说明 | 适用场景 |
|------|-----------|------|---------|
| 一次性 | `at` | 指定毫秒时间戳，执行一次后自动禁用或删除 | "明天下午 3 点提醒我" |
| 固定间隔 | `every` | 按固定毫秒间隔循环执行 | "每 10 分钟检查一下" |
| Cron 表达式 | `cron` | 标准 cron 表达式 + 可选时区 | "工作日早上 9 点" |

对应的数据结构：

```python
@dataclass
class CronSchedule:
    kind: Literal["at", "every", "cron"]
    at_ms: int | None = None       # "at" 模式：目标时间戳（毫秒）
    every_ms: int | None = None    # "every" 模式：间隔（毫秒）
    expr: str | None = None        # "cron" 模式：cron 表达式
    tz: str | None = None          # "cron" 模式：IANA 时区
```

**与 Claude Code 的关键差异**：Claude Code 只用 cron 表达式统一表示所有时间（一次性任务通过固定日/月字段实现），Nanobot 则用三种独立的 `kind` 区分，语义更清晰。

### 2.2 数据结构

#### CronJob — 任务定义

```python
@dataclass
class CronJob:
    id: str                    # 8 位短 UUID
    name: str                  # 人类可读名称
    enabled: bool = True       # 是否启用
    schedule: CronSchedule     # 调度配置
    payload: CronPayload       # 执行内容
    state: CronJobState        # 运行时状态
    created_at_ms: int = 0     # 创建时间
    updated_at_ms: int = 0     # 最后更新时间
    delete_after_run: bool = False  # 执行后是否自动删除
```

#### CronPayload — 任务载荷

```python
@dataclass
class CronPayload:
    kind: Literal["system_event", "agent_turn"] = "agent_turn"
    message: str = ""          # Agent 要执行的指令
    deliver: bool = False      # 是否投递结果到用户渠道
    channel: str | None = None # 目标渠道（如 "whatsapp"）
    to: str | None = None      # 目标用户（如手机号）
```

两种 `kind`：
- `agent_turn`：用户创建的任务，通过 Agent Loop 执行
- `system_event`：系统内部任务（如 Dream 记忆巩固），用户不能删除

#### CronJobState — 运行状态

```python
@dataclass
class CronJobState:
    next_run_at_ms: int | None = None       # 下次运行时间
    last_run_at_ms: int | None = None       # 上次运行时间
    last_status: Literal["ok", "error", "skipped"] | None = None
    last_error: str | None = None
    run_history: list[CronRunRecord] = []   # 最近 20 条执行记录
```

### 2.3 调度核心逻辑 — Timer 机制

Nanobot 采用**单 asyncio Timer 递归调度**模式，而不是固定间隔的 `setInterval`：

```
start()
  ├── _load_store()          # 从磁盘加载所有任务
  ├── _recompute_next_runs() # 为所有启用的任务计算 next_run_at_ms
  ├── _save_store()          # 写回磁盘
  └── _arm_timer()           # 设置下一次唤醒
         │
         ├── 找到最近的 next_run_at_ms
         ├── delay = min(max_sleep_ms, next - now)
         └── asyncio.create_task(sleep(delay) → _on_timer())
                │
                _on_timer()
                  ├── _load_store()    # 重新加载（合并外部修改）
                  ├── 找出所有到期任务（now >= next_run_at_ms）
                  ├── 逐个 _execute_job()
                  ├── _save_store()    # 写回状态
                  └── _arm_timer()     # 递归，设置下一次唤醒
```

**关键设计点：**

1. **最大休眠上限** `max_sleep_ms = 300_000`（5 分钟）：即使没有任务到期，也会定期醒来，确保能及时发现新增任务或外部修改

2. **每次唤醒都重新加载磁盘**：支持多实例场景下的任务同步

3. **`_timer_active` 锁**：timer 执行期间，如果有其他调用（如 `list_jobs`）触发 `_load_store`，会返回当前内存中的 store 而不是重新从磁盘加载，防止执行中途被替换

### 2.4 下次运行时间计算

```python
def _compute_next_run(schedule: CronSchedule, now_ms: int) -> int | None:
    if schedule.kind == "at":
        # 一次性：如果目标时间在未来则返回，否则 None（已过期）
        return schedule.at_ms if schedule.at_ms > now_ms else None

    if schedule.kind == "every":
        # 固定间隔：当前时间 + 间隔
        return now_ms + schedule.every_ms

    if schedule.kind == "cron":
        # Cron 表达式：使用 croniter 库计算，支持时区
        tz = ZoneInfo(schedule.tz) if schedule.tz else 本地时区
        base_dt = datetime.fromtimestamp(now_ms / 1000, tz=tz)
        return croniter(schedule.expr, base_dt).get_next(datetime)
```

### 2.5 任务执行流程

```python
async def _execute_job(self, job: CronJob) -> None:
    # 1. 调用 on_job 回调（由 cli/commands.py 注入）
    await self.on_job(job)

    # 2. 记录执行状态
    job.state.last_run_at_ms = start_ms
    job.state.run_history.append(CronRunRecord(...))
    job.state.run_history = job.state.run_history[-20:]  # 最多保留 20 条

    # 3. 处理执行后逻辑
    if job.schedule.kind == "at":
        # 一次性任务：删除或禁用
        if job.delete_after_run:
            从 store 中移除
        else:
            job.enabled = False
    else:
        # 循环任务：从当前时间重新计算下次执行
        job.state.next_run_at_ms = _compute_next_run(job.schedule, _now_ms())
```

**循环任务从 `_now_ms()` 而不是从 `next_run_at_ms` 重新计算**——这与 Claude Code 的设计一致，避免系统繁忙导致延迟触发后的"快速追赶"问题。

### 2.6 持久化机制

#### 主存储文件

路径：`{workspace}/cron/jobs.json`，JSON 格式，字段使用 camelCase：

```json
{
  "version": 1,
  "jobs": [
    {
      "id": "a1b2c3d4",
      "name": "weather-check",
      "enabled": true,
      "schedule": { "kind": "every", "everyMs": 600000 },
      "payload": { "kind": "agent_turn", "message": "检查天气", "deliver": true, "channel": "telegram", "to": "12345" },
      "state": { "nextRunAtMs": 1712830600000, "lastRunAtMs": 1712830000000, "lastStatus": "ok", "runHistory": [...] },
      "createdAtMs": 1712820000000,
      "updatedAtMs": 1712830000000,
      "deleteAfterRun": false
    }
  ]
}
```

#### Action 日志（WAL 机制）

路径：`{workspace}/cron/action.jsonl`

当 CronService 未运行时（如 Agent 处于 CLI 聊天模式），对任务的修改不会直接写入 `jobs.json`，而是追加到 action 日志：

```jsonl
{"action": "add", "params": {...完整的 CronJob 字段...}}
{"action": "del", "params": {"job_id": "a1b2c3d4"}}
{"action": "update", "params": {...完整的 CronJob 字段...}}
```

当 CronService 启动或 timer 触发时，`_merge_action()` 会将 action 日志合并回主 store，然后清空日志。

整个过程使用 `FileLock` 文件锁保证并发安全。

### 2.7 CronTool — Agent 自主管理定时任务

CronTool 是暴露给 LLM 的工具接口，支持三个 action：

| Action | 说明 | 必须参数 |
|--------|------|---------|
| `add` | 创建任务 | `message` + (`every_seconds` 或 `cron_expr` 或 `at`) |
| `list` | 列出所有任务 | 无 |
| `remove` | 删除任务 | `job_id` |

**CronTool 的防递归设计**：

通过 `ContextVar` 标记当前是否在 cron job 回调中执行：

```python
if self._in_cron_context.get():
    return "Error: cannot schedule new jobs from within a cron job execution"
```

防止 cron 任务执行过程中又创建新的 cron 任务，避免无限递归。

### 2.8 on_cron_job 回调 — 任务执行入口

`CronService.on_job` 回调在 `cli/commands.py` 中注入，处理逻辑：

```
on_cron_job(job)
  │
  ├─ job.name == "dream"?
  │   └─ 是 → 直接调用 agent.dream.run()（不走 Agent Loop）
  │
  ├─ 构造 reminder_note：
  │   "[Scheduled Task] Timer finished.
  │    Task 'xxx' has been triggered.
  │    Scheduled instruction: {message}"
  │
  ├─ 设置 cron_context = True（防递归）
  │
  ├─ agent.process_direct(reminder_note, session_key=f"cron:{job.id}")
  │   └─ 通过完整的 Agent Loop 执行任务
  │
  ├─ 检查 MessageTool 是否已主动发送消息
  │   └─ 已发送 → 跳过后续通知
  │
  └─ job.payload.deliver && 有结果?
      └─ evaluate_response() → LLM 评估是否值得通知用户
          └─ 值得 → 通过 MessageBus 推送到用户渠道
```

### 2.9 系统级任务：Dream（记忆巩固）

Dream 是 Nanobot 的长期记忆巩固机制，通过 cron 注册为受保护的系统任务：

```python
cron.register_system_job(CronJob(
    id="dream",
    name="dream",
    schedule=dream_cfg.build_schedule(timezone),
    payload=CronPayload(kind="system_event"),
))
```

- `payload.kind = "system_event"` 使其不可被用户删除或修改
- 执行时直接调用 `agent.dream.run()`，不经过 Agent Loop
- `register_system_job` 是幂等的，每次重启都会重新注册

---

## 三、Heartbeat Service — 智能心跳巡检

### 3.1 设计思路

Heartbeat 不是传统意义上的"心跳检测"（检查服务是否存活），而是一个**LLM 驱动的智能巡检机制**：

> 定期唤醒 Agent，让它读取一份"待办清单"（HEARTBEAT.md），由 LLM 判断是否有需要处理的任务。

### 3.2 两阶段执行模型

```
_tick()（每隔 interval_s 执行一次，默认 30 分钟）
  │
  ├─ Phase 1: 决策
  │   ├─ 读取 HEARTBEAT.md 文件内容
  │   ├─ 构造 Prompt + 当前时间 → 发给 LLM
  │   ├─ LLM 通过 heartbeat 虚拟工具返回决策：
  │   │   ├─ action="skip" → 没事做，结束
  │   │   └─ action="run", tasks="..." → 有任务要处理
  │   └─ （skip 时不消耗 Agent Loop 资源）
  │
  └─ Phase 2: 执行（仅当 Phase 1 返回 run）
      ├─ on_execute(tasks) → agent.process_direct(tasks, session_key="heartbeat")
      ├─ 裁剪 heartbeat session 历史（保持有界）
      ├─ evaluate_response() → LLM 评估结果是否值得通知用户
      └─ 值得通知 → on_notify(response) → 推送到用户渠道
```

### 3.3 HEARTBEAT.md — 任务清单

```markdown
# Heartbeat Tasks

This file is checked every 30 minutes by your nanobot agent.
Add tasks below that you want the agent to work on periodically.

## Active Tasks

<!-- Add your periodic tasks below this line -->

## Completed

<!-- Move completed tasks here or delete them -->
```

用户或 Agent 通过编辑此文件来管理心跳任务，无需 API 调用。

### 3.4 虚拟工具调用（Virtual Tool Call）

Phase 1 的 LLM 决策通过"虚拟工具"实现，避免了不可靠的自由文本解析：

```python
_HEARTBEAT_TOOL = [{
    "type": "function",
    "function": {
        "name": "heartbeat",
        "parameters": {
            "properties": {
                "action": { "enum": ["skip", "run"] },
                "tasks": { "description": "active tasks summary" },
            },
            "required": ["action"],
        },
    },
}]
```

LLM 被要求通过工具调用返回结构化的决策结果，而不是生成自由文本。

### 3.5 执行回调

```python
async def on_heartbeat_execute(tasks: str) -> str:
    channel, chat_id = _pick_heartbeat_target()  # 自动选择最合适的投递渠道
    resp = await agent.process_direct(
        tasks,
        session_key="heartbeat",
        channel=channel,
        chat_id=chat_id,
        on_progress=_silent,  # 静默执行，不显示中间过程
    )
    # 裁剪 session 历史，防止无限增长
    session = agent.sessions.get_or_create("heartbeat")
    session.retain_recent_legal_suffix(keep_recent_messages)
    agent.sessions.save(session)
    return resp.content if resp else ""
```

---

## 四、执行后评估器（Evaluator）

Cron 和 Heartbeat 共享同一个执行后评估机制：

```python
async def evaluate_response(response, task_context, provider, model) -> bool:
    """用 LLM 判断后台任务的结果是否值得通知用户。"""
    # 通过虚拟工具调用返回结构化决策
    # should_notify=True  → 结果包含重要/可操作的信息，需要通知
    # should_notify=False → 常规或空结果，可以静默
    # 任何异常 → 默认通知（宁可多通知，不可漏重要信息）
```

这保证了后台任务不会用无意义的消息打扰用户。

---

## 五、启动与生命周期

在 `cli/commands.py` 的 `gateway` 命令中完成组装：

```
gateway 启动
  │
  ├── 创建 CronService(store_path)
  ├── 创建 AgentLoop(..., cron_service=cron)
  ├── 注入 on_cron_job 回调
  ├── 创建 HeartbeatService(...)
  ├── 注册 Dream 系统任务
  │
  └── async run():
        ├── cron.start()       # 启动定时调度
        ├── heartbeat.start()  # 启动心跳巡检
        ├── agent.run()        # 启动 Agent 消息循环
        └── channels.start_all() # 启动所有渠道
```

关闭顺序：
```
heartbeat.stop() → cron.stop() → agent.stop() → channels.stop_all()
```

---

## 六、与 Claude Code 定时任务系统的对比

| 维度 | Nanobot | Claude Code |
|------|---------|-------------|
| **时间格式** | 三种独立类型（at/every/cron） | 统一用 5 字段 cron 表达式 |
| **调度实现** | asyncio Timer 递归调度 | setInterval 每秒轮询 |
| **存储方式** | JSON 文件 + Action 日志（WAL） | JSON 文件 + 内存双路径 |
| **并发控制** | FileLock 文件锁 | O_EXCL 原子文件锁 |
| **任务上限** | 无硬限制 | 50 个 |
| **自动过期** | 无（用户手动管理） | 循环任务 7 天自动过期 |
| **抖动机制** | 无 | 确定性 hash jitter |
| **错过检测** | 无 | 启动时检测并提示 |
| **心跳机制** | 有（HeartbeatService） | 无 |
| **系统任务保护** | 有（system_event 不可删除） | 有（permanent 标记） |
| **Agent 自主创建** | 有（CronTool） | 有（CronCreateTool） |
| **执行后评估** | 有（LLM evaluate_response） | 无 |
| **语言** | Python (asyncio) | TypeScript (Node.js) |
