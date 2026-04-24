# HeartClaw

轻量级个人 AI Agent 框架。通过飞书单聊、Web 控制台或本地终端与 Agent 对话，它能执行命令、读写文件、管理记忆，还能通过「天工」自动锻造新的 CLI 工具来扩展自身能力，并具备 KAIROS 自治模式实现自主巡检和定时任务。

## HeartClaw 是什么

HeartClaw 是一个面向个人开发者的轻量级 AI Agent 系统。它的设计哲学来自 NanoClaw —— 代码量小到你能完全理解，不依赖任何重型 Agent 框架。

项目采用 **单仓库 monorepo** 架构，包含三个核心服务：

| 服务 | 说明 | 技术栈 |
|------|------|--------|
| **如意 API**（ruyi-api） | Agent 主服务，处理对话、工具调用、上下文管理 | Python 3.12+ / FastAPI / uvicorn |
| **天工 Worker**（tiangong-worker） | 自动化锻造引擎，巡查锻造令并调度 Coding Agent 生成 Rust CLI 工具 | Python / Codex / Kimi / OpenCode |
| **Web 控制台**（web） | 可视化操作界面，对话、日志、配置、KAIROS 状态一览 | React 19 / Vite / TypeScript |

## 功能概览

### 智能对话

- 支持飞书单聊（p2p）、Web 控制台、本地 CLI 三种交互通道
- 多轮上下文管理，自动压缩超长对话历史
- 支持多 LLM 后端：Kimi（Moonshot）、火山引擎（Doubao）、DeepSeek 等 OpenAI 兼容接口
- 三档模型分级：HIGH（主对话）、MEDIUM（中间任务）、LOW（摘要压缩）

### 内置工具集

Agent 具备以下内置工具，由 LLM 自主决定何时调用：

| 工具 | 功能 |
|------|------|
| **Bash** | 在服务器上执行 shell 命令（含安全权限控制） |
| **ReadFile** | 读取文件内容 |
| **Write** | 创建或覆写文件（原子写入） |
| **Edit** | 精确编辑文件中的指定内容 |
| **ListFiles** | 列出目录结构 |
| **Grep** | 正则搜索文件内容 |
| **Glob** | 按文件名模式匹配搜索 |
| **Memory** | 读取和更新长期记忆 |
| **CronCreate / CronList / CronDelete** | 定时任务管理（创建、查看、删除） |
| **TianGongEvolve** | 向天工下达锻造令，自动编译生成新工具 |
| **TianGongFeedback** | 对天工锻造结果进行反馈 |
| **Sleep** | KAIROS 模式专用，控制自治节奏 |

### 记忆系统

- **短期记忆**：基于 JSONL 的每日会话记录，支持按比例加载和自动压缩
- **长期记忆**：4 个主题文件（用户画像/偏好/事实/指令），存储在 `~/.heartclaw/skills/memory/long_term/`
- **自动更新**：每日定时由 LOW 模型分析对话，提取有价值信息更新长期记忆

### KAIROS 自治模式

独立于用户对话的自治执行器，拥有专属系统提示词和独立上下文：

- 自动巡检和定时任务执行
- 独立的短期记忆存储（不与用户对话混合）
- 共享长期记忆（用户画像/偏好/指令）
- 通过 Sleep 工具控制自治节奏

### 天工锻造系统

通过 Agent 下达「锻造令」，天工 Worker 自动：

1. 巡查 `~/.heartclaw/tiangong/orders/pending/` 目录
2. 调度 Coding Agent（Codex / Kimi / OpenCode）编写代码
3. 编译生成 Rust CLI 工具
4. 交付至 Agent 可用的工具目录

### 定时任务

- 支持 cron 表达式的定时任务调度
- Agent 可通过工具自主创建、查看、删除定时任务
- 每日自动执行记忆更新和锻造计划分析

### Web 控制台

- 对话聊天界面（Markdown 渲染、工具调用结果展示）
- 实时日志查看（WebSocket 推送）
- KAIROS 自治状态面板
- 配置文件编辑器
- 卷宗（对话历史）管理

### 统一输出系统

消息通过 OutputEmitter 统一分发到多个后端：

- **FutureBackend**：异步等待结果
- **LogBackend**：日志记录
- **WebSocketBackend**：实时推送到 Web 控制台
- **FeishuBackend**：推送到飞书单聊

## 架构

```text
用户 ←→ 飞书机器人 / Web 控制台 / CLI ←→ 如意 API（ruyi-api）
                                          │
                                ┌─────────┼─────────┐
                                │         │         │
                            Context    Engine     Tool
                            上下文模块   执行引擎   工具模块
                            │                     │
                            ├─ 系统提示词          ├─ Bash / ReadFile / Write / Edit
                            ├─ Skill 段            ├─ ListFiles / Grep / Glob
                            ├─ 长期记忆            ├─ Memory（读写记忆）
                            ├─ 短期记忆            ├─ Cron（定时任务管理）
                            └─ 上下文压缩          ├─ TianGongEvolve（锻造令）
                                                   └─ TianGongFeedback（锻造反馈）

            ┌──────────────────┐
            │   OutputEmitter  │ → Future / Log / WebSocket / 飞书
            └──────────────────┘

            ┌──────────────────┐
            │  KAIROS Runner   │ → 独立上下文 + 自治执行
            └──────────────────┘

 如意 API 写入共享目录：
 ~/.heartclaw/tiangong/orders/pending/*.md
                                      │
                                      ▼
 ┌──────────────────────────────────────────┐
 │  天工 Worker（tiangong-worker）            │
 │  巡查锻造令 → 调度 Coding Agent → 交付工具  │
 │  Rust 工具链 + Codex / Kimi / OpenCode     │
 └──────────────────────────────────────────┘
```

如意和天工通过共享卷 `~/.heartclaw/` 文件通信，不引入额外消息队列。

## 快速开始

### 前置条件

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 包管理器
- Node.js 22+（仅 Web 控制台开发需要）
- 飞书开放平台企业自建应用（飞书模式需要）

### 1. 克隆并安装后端依赖

```bash
git clone <repo-url> heartclaw
cd heartclaw
cd apps/ruyi-api
uv sync
```

### 2. 初始化目录结构

```bash
make bootstrap
```

在 `~/.heartclaw/` 下创建配置文件和数据目录：

```text
~/.heartclaw/
├── config.json                  # 主配置文件（模型、记忆、飞书、天工、KAIROS）
├── skills/
│   └── memory/
│       ├── long_term/           # 长期记忆（4 个主题文件）
│       ├── short_term/          # 短期记忆（每日 .jsonl）
│       ├── kairos/              # KAIROS 独立记忆
│       └── update_logs/         # 记忆更新日志
└── tiangong/
    ├── orders/                  # 锻造令（pending/processing/done/review）
    └── codex/                   # Codex Agent 配置
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入：

```env
# 飞书应用（从飞书开放平台获取，飞书模式必填）
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# 飞书事件（Webhook 模式需要，长连接模式可不填）
FEISHU_VERIFICATION_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
FEISHU_ENCRYPT_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# LLM - Kimi (Moonshot)，用于主对话（HIGH / MEDIUM 模型）
KIMI_API_KEY=sk-xxxxxxxx

# LLM - 火山引擎 (Doubao)，用于摘要压缩（LOW 模型）
VOLCENGINE_API_KEY=xxxxxxxx

# LLM - DeepSeek（可选，替代模型）
DEEPSEEK_API_KEY=sk-xxxxxxxx

# 应用
LOG_LEVEL=INFO
```

### 4. 启动如意 API

提供三种启动模式：

```bash
# API-only 模式（不连接飞书，仅暴露 HTTP + WebSocket 接口）
make dev

# 飞书模式（连接飞书长连接 + API 服务）
cd apps/ruyi-api
HEARTCLAW_CHANNEL_MODE=feishu PYTHONPATH=src uv run python src/main.py

# CLI 模式（本地终端对话，用于调试）
make cli
```

启动成功后，如意 API 监听 `http://localhost:8000`。

### 5. 启动 Web 控制台

```bash
cd apps/web
cp .env.example .env    # 默认指向 http://localhost:8000
npm install
npm run dev
```

Web 控制台默认监听 `http://localhost:5173`，如需调整后端地址，修改 `apps/web/.env`：

```env
VITE_API_BASE_URL=http://localhost:8000
```

### 6. 访问

| 地址 | 说明 |
|------|------|
| `http://localhost:8000` | 如意 API（FastAPI，含自动 API 文档 `/docs`） |
| `http://localhost:8000/docs` | Swagger UI 交互式 API 文档 |
| `http://localhost:5173` | Web 控制台 |

Web 控制台页面：

- **如意**（RuyiPage）：与 Agent 对话，支持 Markdown 渲染和工具调用结果展示
- **天工**（TiangongPage）：查看天工锻造状态和日志
- **卷宗**（JuanzongPage）：对话历史管理
- **KAIROS**（KairosPage）：KAIROS 自治模式状态面板

## Docker 部署

```bash
cp .env.example .env
# 编辑 .env 填入配置

make up        # 构建并启动 ruyi-api + tiangong-worker + web
make logs      # 查看日志
make ps        # 查看容器状态
make down      # 停止
```

`docker compose` 启动三个容器：

| 容器 | 作用 | 端口 |
|------|------|------|
| ruyi-api | Agent 主服务（FastAPI + 飞书长连接 + KAIROS） | 8000 |
| tiangong-worker | 天工锻造引擎（巡查锻造令 → Coding Agent → Rust 工具） | - |
| heartclaw-web | React + Vite 控制台 | 5173 |

如意和天工通过共享卷 `~/.heartclaw/` 通信：如意写入锻造令，天工巡查并执行。

## Makefile 命令速查

| 命令 | 说明 |
|------|------|
| `make bootstrap` | 初始化 `~/.heartclaw/` 目录结构和配置文件 |
| `make dev` | 启动如意 API（API-only 模式） |
| `make cli` | 启动本地终端对话（调试模式） |
| `make web-dev` | 启动 Web 控制台开发服务器 |
| `make web-build` | 构建 Web 控制台生产版本 |
| `make up` | Docker Compose 构建并启动所有服务 |
| `make down` | 停止 Docker 容器 |
| `make logs` | 查看 Docker 容器日志 |
| `make ps` | 查看容器状态 |
| `make chat TEXT="你好"` | 通过 curl 发送消息到 API（调试用） |

## 项目结构

```text
heartclaw/
├── apps/
│   ├── ruyi-api/                           # 如意 API（Agent 主服务）
│   │   ├── pyproject.toml
│   │   └── src/
│   │       ├── main.py                     # 入口：组装模块，启动服务
│   │       ├── config/settings.py          # 配置（config.json + .env 加载）
│   │       ├── core/
│   │       │   ├── agent/                  # Agent + KairosRunner 编排
│   │       │   ├── engine/                 # ExecutionEngine 执行引擎
│   │       │   ├── context/                # 上下文管理（系统提示 / 短期 / 长期记忆）
│   │       │   ├── llm/                    # LLM 服务（工厂模式 + OpenAI 兼容接口）
│   │       │   ├── tool/                   # 工具管理 + 调度 + 审批
│   │       │   │   └── tools/              # 内置工具集（bash/read/write/edit/grep/...）
│   │       │   ├── output/                 # 统一输出系统（OutputEmitter + 多后端）
│   │       │   ├── queue/                  # 消息队列 + QueueProcessor
│   │       │   └── prompts/                # 系统提示词模板
│   │       ├── channels/feishu/            # 飞书 Channel（WebSocket 长连接）
│   │       ├── storage/                    # 存储层（短期记忆 / 长期记忆 / SQLite）
│   │       ├── scheduler/                  # 定时任务（cron / 记忆更新 / 锻造计划）
│   │       ├── api/                        # FastAPI 路由
│   │       │   └── routes/                 # health / chat / webhook / ws / juanzong / logs
│   │       └── utils/                      # 日志 / token 计数
│   │
│   ├── tiangong-worker/                    # 天工锻造引擎
│   │   └── tiangong/
│   │       ├── main.py                     # 天工入口
│   │       ├── engine.py                   # 巡查 + 调度 Coding Agent
│   │       └── adapters.py                 # Coding Agent 适配器
│   │
│   └── web/                                # React + Vite 控制台
│       └── src/
│           ├── pages/                      # 页面：Ruyi / Tiangong / Juanzong / Kairos
│           ├── components/                 # 组件：chat / log / config / kairos
│           ├── hooks/                      # WebSocket 等自定义 Hook
│           ├── layouts/                    # 布局：AppLayout / Sidebar / TopBar
│           └── stores/                     # 状态管理
│
├── docs/                                   # 设计文档
├── docker/                                 # Dockerfile + 容器环境变量
├── docker-compose.yml
├── Makefile
├── config.json                             # 项目级配置模板
├── .env.example                            # 环境变量模板
└── CLAUDE.md / AGENTS.md                   # AI 协作规则
```

## 技术栈

| 组件 | 选型 |
|------|------|
| 后端语言 | Python 3.12+ |
| 后端包管理 | uv |
| API 框架 | FastAPI + uvicorn |
| 前端框架 | React 19 + Vite 7 + TypeScript |
| 路由 | react-router-dom v7 |
| Markdown 渲染 | react-markdown + remark-gfm |
| 图标 | lucide-react |
| 飞书 SDK | lark-oapi |
| LLM 调用 | OpenAI 兼容接口（Kimi / Doubao / DeepSeek） |
| 定时任务 | APScheduler + croniter |
| 本地存储 | aiosqlite + JSONL 文件 |
| 容器化 | Docker Compose |
| 天工工具链 | Rust + Codex / Kimi / OpenCode CLI |

## 设计文档

- [总体架构设计](docs/architecture.md)
- [飞书工具封装设计](docs/feishu-tools-design.md)
- [记忆模块设计](docs/memory-design.md)
- [Agent 消息输出模块设计](docs/Components/Agent消息输出模块设计/output-system-design.md)
- [上下文模块架构总览](docs/Components/上下文模块重构/00_架构总览.md)
- [LLM 模块架构与开发指南](docs/Components/LLM模块开发/LLM模块架构与开发指南.md)
- [定时任务系统](docs/Components/定时任务系统/定时任务系统.md)
- [天工模块架构总览](docs/Components/天工模块开发/00_需求与架构总览.md)
- [存储架构设计](docs/Components/存储架构设计/存储架构设计.md)

## License

MIT
