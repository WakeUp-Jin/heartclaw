# 天工任务取消与 KAIROS 巡检机制

本文档说明天工锻造任务的取消机制，重点解决 Coding Agent 陷入循环或长时间不退出时，天工主循环被卡住的问题。

## 背景

HeartClaw 和 TianGong 在 Docker 中是两个独立容器：

- HeartClaw 运行主 Agent 和 KAIROS。
- TianGong 运行锻造巡查循环，并在自己的容器内启动 `kimi`、`codex` 等 Coding Agent CLI。
- 两个容器共享 `.heartclaw` 目录，但不共享进程空间。

因此，KAIROS 不能直接 `kill` TianGong 容器里的 Agent 子进程。正确做法是：KAIROS 通过共享目录写入取消请求，TianGong 在自己的进程里读取请求，并负责终止 Agent 子进程。

## 两层取消机制

### 1. 天工硬超时

天工自己会监控单个锻造任务的执行时长。默认情况下，任务执行超过 3600 秒后，天工会主动取消当前 Agent 子进程。

配置项位于 `config.json` 的 `tiangong` 段：

```json
{
  "tiangong": {
    "enable_forge_timeout": true,
    "max_forge_seconds": 3600,
    "cancel_check_interval_seconds": 10,
    "agent_log_tail_lines": 80
  }
}
```

字段含义：

- `enable_forge_timeout`：是否启用天工硬超时，默认 `true`。
- `max_forge_seconds`：单个锻造任务最长执行秒数，默认 `3600`。
- `cancel_check_interval_seconds`：天工检查超时和取消请求的间隔，默认 `10` 秒。
- `agent_log_tail_lines`：建议 KAIROS 巡检时读取的 Agent 日志尾部行数，默认 `80`。

### 2. KAIROS 主动取消

KAIROS 每次 tick 时会检查天工运行状态。如果发现 pending 队列为空，但当前 active task 仍长时间运行，KAIROS 会读取 Agent 输出日志尾部，并判断任务是在正常收尾，还是已经进入无意义循环。

KAIROS 不会因为 `pending/` 为空就自动取消任务。`pending/` 为空只是一个风险信号，说明当前任务可能处于收尾阶段，也可能已经陷入循环。

KAIROS 可以取消的典型情况：

- 日志长期重复同一类命令或同一段输出。
- 反复调用同一个工具但没有新的文件修改、测试结果或交付进展。
- 反复报同一个错误且没有明显改变方案。
- pending 已空，active task 仍运行很久，日志看起来只是在循环尝试。

KAIROS 不应取消的典型情况：

- 日志显示正在跑测试、安装依赖、构建或生成文件。
- 日志显示正在修复明确错误，且每轮尝试都有新进展。
- 任务刚开始不久，或明显处于正常收尾阶段。
- 没有读取到足够证据判断任务已经无效。

## Runtime 文件协议

天工运行时状态保存在共享目录：

```text
.heartclaw/tiangong/runtime/
├── active_task.json
├── cancel_requests/
│   └── <order_id>.json
└── logs/
    └── <order_id>.log
```

### active_task.json

天工开始处理锻造令时写入 `active_task.json`，任务结束后清理。

示例：

```json
{
  "order_id": "2026-04-23-example",
  "order_file": "/shared/tiangong/orders/processing/2026-04-23-example.md",
  "tool_name": "example",
  "forge_type": "首次",
  "agent_type": "kimi",
  "tool_workspace": "/workspace/example",
  "started_at": "2026-04-23T10:00:00+08:00",
  "last_heartbeat_at": "2026-04-23T10:03:00+08:00",
  "last_output_at": "2026-04-23T10:02:55+08:00",
  "agent_log_path": "/shared/tiangong/runtime/logs/2026-04-23-example.log",
  "status": "running"
}
```

### cancel_requests

KAIROS 如果判断任务应取消，就写入：

```text
.heartclaw/tiangong/runtime/cancel_requests/<order_id>.json
```

示例：

```json
{
  "order_id": "2026-04-23-example",
  "requested_by": "kairos",
  "requested_at": "2026-04-23T10:30:00+08:00",
  "reason": "pending 为空且日志持续重复同一错误",
  "evidence": "最近 80 行日志反复执行同一命令并得到相同失败结果，没有新的修改或测试进展"
}
```

天工读取到对应取消请求后，会终止当前 Agent 子进程，并将锻造令归档到 `done/`，状态写为失败。

### Agent 日志

天工会把 Agent 的 stdout 和 stderr 合并追加到：

```text
.heartclaw/tiangong/runtime/logs/<order_id>.log
```

每一行包含时间、输出流名称和文本内容，便于 KAIROS 或人工排查。

## 取消流程

### 天工硬超时流程

1. 天工把锻造令从 `pending/` 移动到 `processing/`。
2. 天工写入 `active_task.json`。
3. 天工启动 Agent 子进程。
4. 天工每隔 `cancel_check_interval_seconds` 秒检查一次运行时长。
5. 如果启用了硬超时，并且运行时间超过 `max_forge_seconds`，天工取消 Agent。
6. 天工将锻造令归档到 `done/`，失败原因写为超时取消。

### KAIROS 主动取消流程

1. KAIROS tick 被触发。
2. KAIROS 检查 `orders/pending/` 和 `runtime/active_task.json`。
3. 如果存在 active task，KAIROS 读取 `agent_log_path` 的尾部日志。
4. KAIROS 判断当前任务是否仍有有效进展。
5. 如果判断无效，KAIROS 写入 `cancel_requests/<order_id>.json`。
6. 天工下一次巡检取消请求时，终止当前 Agent 子进程。
7. KAIROS 写入请求后应调用 `Sleep(30)`，等待天工处理。

## 子进程终止方式

天工启动 Agent 子进程时会创建独立进程组。取消时采用两段式终止：

1. 先发送 `SIGTERM`，给 Agent 正常退出机会。
2. 等待 5 秒。
3. 如果仍未退出，发送 `SIGKILL` 强制结束。

这样可以尽量避免 Agent 留下孤儿子进程。

## 常见排查

- 如果任务一直在 `processing/`，先查看 `tiangong/runtime/active_task.json` 是否存在。
- 如果 active task 存在，查看 `agent_log_path` 指向的日志尾部。
- 如果需要人工取消，可以手动创建 `cancel_requests/<order_id>.json`。
- 如果不希望天工自动超时取消，可以在配置中设置 `"enable_forge_timeout": false`。
- 如果任务通常很长，可以调大 `"max_forge_seconds"`。
