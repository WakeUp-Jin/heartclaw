# HeartClaw

轻量级 AI Agent 框架。通过飞书单聊与机器人对话，它能执行命令、读取文件、管理记忆，还能通过「天工」自动锻造新的 CLI 工具来扩展自身能力。

## 它能做什么

- **智能对话**：在飞书单聊或 Web 控制台中与 Agent 对话，支持多轮上下文
- **执行命令**：通过 Bash 工具在服务器上运行 shell 命令
- **文件操作**：读取文件内容、列出目录结构
- **记忆系统**：短期记忆（会话历史）+ 长期记忆（偏好/知识），每日自动整理更新
- **Skill 扩展**：从约定目录扫描 `SKILL.md`，动态加载能力描述注入 system prompt
- **天工锻造**：向天工下达「锻造令」，自动编译生成新的 Rust CLI 工具，扩展 Agent 能力

## 架构

```text
用户 ←→ 飞书机器人 / Web 控制台 ←→ 如意 API（ruyi-api）
                                      │
                            ┌─────────┼─────────┐
                            │         │         │
                        Context    Engine     Tool
                        上下文模块   执行引擎   工具模块
                        │                     │
                        ├─ 系统提示词          ├─ Bash（shell 命令）
                        ├─ Skill 目录          ├─ ReadFile（读文件）
                        ├─ 长期记忆            ├─ ListFiles（列目录）
                        ├─ 短期记忆            ├─ TianGongEvolve（锻造令）
                        └─ 上下文压缩          └─ Memory（读写记忆）

 如意 API 写入共享目录：
 ~/.heartclaw/tiangong/orders/pending/*.md
                                      │
                                      ▼
 ┌──────────────────────────────────────────┐
 │  天工 Worker（tiangong-worker）            │
 │  巡查锻造令 → 调度 Coding Agent → 交付工具  │
 │  Rust 工具链 + Node.js + Codex/Kimi/OpenCode │
 └──────────────────────────────────────────┘
```

项目采用单仓库 monorepo：**ruyi-api**（Agent 主服务）+ **tiangong-worker**（天工锻造引擎）+ **web**（React + Vite 控制台）。如意和天工通过共享卷 `~/.heartclaw/` 文件通信，不引入额外消息队列。

## 快速开始

### 前置条件

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 包管理器
- Node.js 22+（仅 Web 开发需要）
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

这会在 `~/.heartclaw/` 下创建配置文件和数据目录：

```text
~/.heartclaw/
├── config.json                  # 主配置文件（模型、记忆、飞书、天工）
├── skills/
│   └── memory/
│       ├── long_term/           # 长期记忆（4 个主题文件）
│       ├── short_term/          # 短期记忆（每日 .jsonl）
│       └── update_logs/         # 记忆更新日志
└── tiangong/
    ├── orders/                  # 锻造令（pending/processing/done）
    └── codex/                   # Codex Agent 配置
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入：

```env
# 飞书应用（从飞书开放平台获取）
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# 飞书事件（Webhook 模式需要，长连接模式可不填）
FEISHU_VERIFICATION_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
FEISHU_ENCRYPT_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# LLM - Kimi (Moonshot)，用于主对话（high/medium 模型）
KIMI_API_KEY=sk-xxxxxxxx

# LLM - 火山引擎 (Doubao)，用于摘要压缩（low 模型）
VOLCENGINE_API_KEY=xxxxxxxx
```

### 4. 启动如意 API

```bash
# API-only 模式（不连接飞书，仅暴露 HTTP 接口）
cd apps/ruyi-api
PYTHONPATH=src uv run python src/main.py

# 飞书模式（连接飞书长连接 + API 服务）
cd apps/ruyi-api
HEARTCLAW_CHANNEL_MODE=feishu PYTHONPATH=src uv run python src/main.py

# CLI 模式（本地终端对话，用于调试）
make cli
```

### 5. 启动 Web 控制台

```bash
cd apps/web
cp .env.example .env
npm install
npm run dev
```

默认 Web 会调用 `http://localhost:8000`。如需调整后端地址，修改 `apps/web/.env`：

```env
VITE_API_BASE_URL=http://localhost:8000
```

### Docker 部署

```bash
cp .env.example .env
# 编辑 .env 填入配置

make up        # 构建并启动 ruyi-api + tiangong-worker + web
make logs      # 查看日志
make ps        # 查看容器状态
make down      # 停止
```

`docker compose` 会启动三个容器：

| 容器 | 作用 | 端口 |
|------|------|------|
| ruyi-api | Agent 主服务（FastAPI + 飞书长连接） | 8000 |
| tiangong-worker | 天工锻造引擎（巡查锻造令 → Coding Agent → Rust 工具） | - |
| heartclaw-web | React + Vite 控制台 | 5173 |

如意和天工通过共享卷 `~/.heartclaw/` 通信：如意写入锻造令，天工巡查并执行。

## 项目结构

```text
heartclaw/
├── apps/
│   ├── ruyi-api/
│   │   ├── pyproject.toml              # 如意 API Python 依赖
│   │   ├── uv.lock
│   │   └── src/
│   │       ├── main.py                  # 如意入口：组装模块，启动服务
│   │       ├── config/settings.py       # 配置（config.json + .env 加载）
│   │       ├── core/                    # Agent / Engine / Tool / LLM / Context
│   │       ├── channels/feishu/         # 飞书 Channel（WebSocket 长连接）
│   │       ├── storage/                 # 存储层
│   │       ├── scheduler/               # 定时任务
│   │       ├── api/                     # FastAPI 路由
│   │       └── utils/                   # 日志 / token 计数
│   │
│   ├── tiangong-worker/
│   │   └── tiangong/
│   │       ├── main.py                  # 天工入口
│   │       ├── engine.py                # 巡查 + 调度 Coding Agent
│   │       └── adapters.py              # Coding Agent 适配器
│   │
│   └── web/                             # React + Vite 控制台
│
├── docker/
│   ├── ruyi-api.Dockerfile              # 如意 API 镜像
│   ├── tiangong-worker.Dockerfile       # 天工 Worker 镜像
│   └── env/                             # 容器专用环境变量
├── docker-compose.yml
├── Makefile
├── config.json                          # 项目级配置模板
└── .env.example                         # 环境变量模板
```

## 技术栈

| 组件 | 选型 |
|------|------|
| 后端语言 | Python 3.12+ |
| 后端包管理 | uv |
| API 框架 | FastAPI + uvicorn |
| 前端 | React + Vite + TypeScript |
| 飞书 SDK | lark-oapi |
| LLM | OpenAI 兼容接口（Kimi / Doubao / DeepSeek / ...） |
| 定时任务 | APScheduler |
| 本地存储 | aiosqlite + JSONL 文件 |
| 容器化 | Docker Compose |
| 天工工具链 | Rust + Codex/Kimi/OpenCode CLI |

## 设计文档

- [总体架构设计](docs/architecture.md)
- [飞书工具封装设计](docs/feishu-tools-design.md)
- [记忆模块设计](docs/memory-design.md)

## License

MIT
