# CodeAgent 框架探索与架构选型

> 本文档整理自对 NanoClaw 项目的深度探索，记录了 CodeAgent 框架的设计哲学、工具体系、选型对比与安全考量。

---

## 一、NanoClaw 的设计哲学

NanoClaw 是 OpenClaw（前身 ClawBot）的极简替代品。OpenClaw 发展成了一个拥有 50 万行代码、70+ 依赖、4~5 个独立进程的庞然大物，安全隔离靠应用层 allowlist 实现，难以理解和审计。

NanoClaw 的核心主张：

- **小到可以完全读懂**：单个 Node.js 进程，少量源文件，无微服务
- **隔离靠 OS 而非代码**：agent 跑在 Linux 容器里，只能看到显式挂载的目录
- **为单一用户构建**：不追求支持所有人，只做自己需要的集成
- **定制 = 改代码**：不用配置文件，直接 fork 修改，代码足够小所以安全可控
- **Skills 而非 Features**：贡献者提交 `/add-telegram` 这样的 skill，而不是把 Telegram 支持塞进主干

---

## 二、NanoClaw 的三层架构

```
层1：主进程 (Node.js, src/index.ts)
     接收消息 → 存 SQLite → 拉起容器 → 等结果返回
     [自己写的，几百行胶水代码]
         ↓ stdin/stdout JSON
层2：Docker / Apple Container
     OS 级别隔离，挂载指定目录
     [不用自己写，OS 提供]
         ↓
层3：Claude Code CLI（跑在容器里）
     内置 Read / Write / Edit / Bash / Glob / Grep / WebSearch...
     [Anthropic 实现，不用自己写]
```

**NanoClaw 自己只写了：**
- 消息路由 + 数据库操作（主进程）
- 一个小 MCP server（`ipc-mcp-stdio.ts`），提供 `send_message`、`schedule_task` 等业务工具

### Claude Agent SDK 的位置

主项目 `package.json` 里看不到 SDK，因为它在容器内部：

```
nanoclaw/package.json           ← 主进程依赖（better-sqlite3, pino...）
container/agent-runner/package.json  ← 容器内依赖（@anthropic-ai/claude-agent-sdk）
```

容器里的 `agent-runner/src/index.ts` 调用 `query()` 函数，SDK 在这里。

---

## 三、工具（Tool）体系

### NanoClaw 的工具从哪来

NanoClaw 没有自己实现任何工具。工具全部来自 Claude Code 内置：

```typescript
// container/agent-runner/src/index.ts
allowedTools: [
  'Bash',
  'Read', 'Write', 'Edit', 'Glob', 'Grep',   // 文件系统工具
  'WebSearch', 'WebFetch',                     // 网络工具
  'Task', 'TaskOutput', 'TaskStop',            // 子 agent 工具
  'TeamCreate', 'TeamDelete', 'SendMessage',   // 团队协作
  'mcp__nanoclaw__*'                           // 业务自定义工具
]
```

`Bash` 工具安全的原因：命令在容器内执行，不在宿主机上。

### OpenClaw 的工具体系

OpenClaw 没有 Claude Code 这个现成的执行引擎，所以自己实现了：
- 文件读写工具（`fs` 操作）
- Shell 执行工具（`child_process`）
- 浏览器自动化工具
- 应用层权限管控（allowlist、pairing code）

这是它代码量巨大的根本原因。

---

## 四、Skill 系统

### NanoClaw 的 Skill

Skill 就是一个 Markdown 文件，内容是自然语言指令：

```
.claude/skills/setup/SKILL.md
---
name: setup
description: 什么时候触发这个 skill
---
# 步骤1: 检查 git 配置
运行 git remote -v ...
```

Claude Code 读到这个文件，理解指令，用自己内置的工具（Bash/Read/Write）去执行。**Skill 本身不是代码，是菜谱。**

### 没有 Claude Code 时实现 Skill

必须自己定义结构化格式（JSON/YAML）+ 实现四个基础工具：

```
Read   → fs.readFileSync()
Write  → fs.writeFileSync()
Search → glob / ripgrep
Exec   → child_process.exec()
```

---

## 五、框架选型对比

### Claude Agent SDK

- 只支持 Claude 模型（`sonnet` / `opus` / `haiku`）
- TypeScript/Python 两个版本
- Python 版可以直接 in-process 调用

### Neovate Code

- 支持 12 个内置工具：`bash`, `read`, `write`, `edit`, `glob`, `grep`, `ls`, `fetch`, `skill`, `task`, `todo`, `askUserQuestion`
- 支持多模型：Anthropic / OpenAI / DeepSeek / Gemini / GLM / 硅基流动...
- 插件系统（lifecycle hooks、自定义工具、slash commands）
- 支持 MCP
- headless 模式可作为子进程运行

### pi-mono（OpenClaw 的底层引擎）

| 包 | 职责 |
|---|---|
| `pi-ai` | 统一 LLM API（Anthropic/OpenAI/Google/DeepSeek/Ollama...） |
| `pi-agent-core` | Agent loop + 工具调用 |
| `pi-coding-agent` | 完整 coding agent（4 个工具 + session + skills） |
| `pi-tui` | Terminal UI |

默认只有 4 个工具：`read` / `write` / `edit` / `bash`，极简。

**专为非 Node.js 集成设计的 RPC 模式：**

```python
import subprocess, json

proc = subprocess.Popen(
    ['pi', '--rpc'],          # JSONL over stdin/stdout
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE
)
proc.stdin.write(json.dumps({"type": "message", "text": "..."}) + '\n')
```

### 对比总结

| | Claude Code | Neovate | pi-mono |
|---|---|---|---|
| 内置工具数 | 15+ | 12 | 4（极简） |
| 多模型支持 | ❌ 仅 Claude | ✅ | ✅ |
| Python 集成 | SDK / subprocess | headless | **RPC 模式**（专为此设计）|
| 生产验证 | Anthropic 官方 | 较新 | OpenClaw 在用 |
| 可定制深度 | MCP 扩展 | 插件 hook | 分层，可单独用 pi-agent-core |

---

## 六、容器安全分析

### 容器隔离保护的边界

| 威胁 | 容器能防？ |
|------|----------|
| Agent 破坏宿主机系统文件 | ✅ |
| Agent 读取宿主机其他进程 | ✅ |
| Agent 乱删**挂载目录**内的文件 | ❌ |
| Agent 通过网络调外部 API | ❌（需加网络策略） |
| Agent 读取容器内环境变量（API Key）| ❌ |

### 单容器 vs 嵌套容器

**项目本身已在 Docker 时，不需要嵌套容器：**

```
┌──────────────────────────────┐
│  Docker 容器                 │
│  ├── Python 主进程           │   ← 消息路由、数据库
│  └── Agent 进程（子进程）     │   ← bash 工具在容器内执行
└──────────────────────────────┘
        ↑ Docker 已提供对宿主机的隔离
```

NanoClaw 嵌套容器适用于**主进程跑在宿主机**的场景，为 agent 提供额外隔离层。

### 单容器加固清单

1. **目录隔离**：Agent 工作目录 `/workspace/` 与主进程目录 `/app/` 分开
2. **低权限用户**：Agent 进程以独立低权限用户运行
3. **禁用不需要的工具**：如果只是对话，不给 `bash` 工具
4. **环境变量隔离**：API Key 不注入 Agent 进程的环境

### 适用场景判断

| 场景 | 推荐方案 |
|---|---|
| 内部飞书 Bot，用户可信 | 单容器，做好目录和权限隔离 |
| 外部用户，不可控 | NanoClaw 模式：每会话独立子容器 |
| Agent 需要执行任意命令 | 嵌套容器，严格控制挂载点 |

---

## 七、PineClaw 架构建议

基于以上分析，Python + 飞书 + 容器的推荐架构：

```
飞书用户
    ↓ Bot API
┌──────────────────────────────────┐
│  Docker 容器                     │
│                                  │
│  Python 主进程                   │
│  ├── 飞书消息接收/发送            │
│  ├── 会话管理 / 数据库            │
│  └── subprocess → pi --rpc      │
│                                  │
│  pi-coding-agent（子进程）        │
│  ├── DeepSeek / 国内模型          │
│  ├── read/write/edit/bash        │
│  └── 自定义 MCP 工具              │
└──────────────────────────────────┘
```

- 主进程和 Agent 同容器，容器提供对宿主机的隔离
- 通过 RPC（JSONL over stdin/stdout）通信
- Agent 使用 DeepSeek 等国内模型，避免 Claude Code 的封锁风险
- 工具执行在容器内，文件系统天然受限
