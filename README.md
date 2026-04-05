# HeartClaw

轻量级 AI Agent 框架。通过飞书单聊与机器人对话，它能执行命令、读取文件、管理记忆，还能通过「天工」自动锻造新的 CLI 工具来扩展自身能力。

## 它能做什么

- **智能对话**：在飞书单聊中与 Agent 对话，支持多轮上下文
- **执行命令**：通过 Bash 工具在服务器上运行 shell 命令
- **文件操作**：读取文件内容、列出目录结构
- **记忆系统**：短期记忆（会话历史）+ 长期记忆（偏好/知识），每日自动整理更新
- **Skill 扩展**：从约定目录扫描 `SKILL.md`，动态加载能力描述注入 system prompt
- **天工锻造**：向天工下达「锻造令」，自动编译生成新的 Rust CLI 工具，扩展 Agent 能力

## 架构

```
用户 ←→ 飞书机器人（单聊 p2p）←→ HeartClaw Agent
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

 ┌──────────────────────────────────────────┐
 │  天工容器（独立运行）                       │
 │  巡查锻造令 → 调度 Coding Agent → 交付工具  │
 │  Rust 工具链 + Node.js + Codex CLI        │
 └──────────────────────────────────────────┘
```

双容器架构：**heartclaw**（Agent 主服务）+ **tiangong**（天工锻造引擎），通过共享卷 `~/.heartclaw/` 通信。

## 快速开始

### 前置条件

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 包管理器
- 飞书开放平台企业自建应用（需开启机器人能力）

### 1. 克隆并安装依赖

```bash
git clone <repo-url> heartclaw
cd heartclaw
uv sync
```

### 2. 初始化目录结构

```bash
make bootstrap
```

这会在 `~/.heartclaw/` 下创建配置文件和数据目录：

```
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

### 4. 配置模型

编辑 `~/.heartclaw/config.json`，项目提供了合理的默认值：

| 模型层级 | 用途 | 默认模型 |
|---------|------|---------|
| high | 主对话 + 工具调用 | Kimi K2.5 |
| medium | 备用 | Kimi K2.5 |
| low | 上下文压缩 / 记忆整理 | Doubao Seed 2.0 Lite |

### 5. 配置飞书开放平台

1. 在 [飞书开放平台](https://open.feishu.cn/) 创建企业自建应用
2. 开启 **机器人** 能力
3. 配置事件订阅 → 添加事件 `im.message.receive_v1`，选择 **长连接** 模式
4. 申请权限：`im:message`、`im:message:send_as_bot`
5. 发布应用并通过管理员审核

### 6. 启动

```bash
# 飞书模式（连接飞书长连接 + API 服务）
HEARTCLAW_CHANNEL_MODE=feishu python src/main.py

# API-only 模式（不连接飞书，仅暴露 HTTP 接口）
python src/main.py

# CLI 模式（本地终端对话，用于调试）
make cli

# 开发模式（热重载）
make dev
```

### Docker 部署

```bash
cp .env.example .env
# 编辑 .env 填入配置

make up        # 构建并启动双容器（heartclaw + tiangong）
make logs      # 查看日志
make ps        # 查看容器状态
make down      # 停止
```

`docker compose` 会启动两个容器：

| 容器 | 作用 | 端口 |
|------|------|------|
| heartclaw | Agent 主服务（FastAPI + 飞书长连接） | 8000 |
| tiangong | 天工锻造引擎（巡查锻造令 → Codex Agent → Rust 工具） | - |

两个容器通过共享卷 `~/.heartclaw/` 通信——heartclaw 写入锻造令，tiangong 巡查并执行。

## 项目结构

```
heartclaw/
├── src/
│   ├── main.py                          # 入口：组装模块，启动服务
│   ├── config/settings.py               # 配置（config.json + .env 加载）
│   │
│   ├── core/
│   │   ├── agent/
│   │   │   ├── agent.py                 # Agent 编排（接收消息 → 上下文 → 引擎 → 回复）
│   │   │   ├── cli.py                   # CLI 交互模式
│   │   │   └── memory_update_agent.py   # 记忆整理 Agent
│   │   ├── engine/engine.py             # 执行引擎（LLM 调用 + 工具循环）
│   │   ├── llm/
│   │   │   ├── registry.py              # LLM 服务注册中心（high/medium/low）
│   │   │   ├── factory.py               # LLM 服务工厂
│   │   │   └── services/               # 各厂商适配（OpenAI/Kimi/Volcengine）
│   │   ├── context/
│   │   │   ├── manager.py               # 上下文管理器
│   │   │   ├── modules/                # 系统提示 / 短期记忆 / 长期记忆
│   │   │   └── utils/                  # 压缩器 / token 估算 / 消息清理
│   │   ├── tool/
│   │   │   ├── manager.py               # 工具注册与执行
│   │   │   ├── scheduler.py             # 工具调度（审批模式）
│   │   │   ├── memory_tools.py          # 记忆读写工具
│   │   │   └── tools/                  # 内置工具（bash/read_file/list_files/tiangong_evolve）
│   │   └── skill/
│   │       └── scanner.py               # Skill 目录扫描与 catalog 构建
│   │
│   ├── channels/feishu/                 # 飞书 Channel（WebSocket 长连接）
│   ├── storage/                         # 存储层（短期记忆/长期记忆/会话/配置）
│   ├── scheduler/                       # 定时任务（每日记忆整理）
│   ├── api/                             # FastAPI 路由（健康检查/对话/Webhook/卡片回调）
│   ├── tiangong/                        # 天工引擎（独立容器中运行）
│   │   ├── main.py                      # 天工入口
│   │   ├── engine.py                    # 巡查 + 调度 Coding Agent
│   │   └── adapters.py                  # Coding Agent 适配器（Codex）
│   └── utils/                           # 日志 / token 计数
│
├── docker/
│   ├── heartclaw.Dockerfile             # Agent 主服务镜像
│   ├── tiangong.Dockerfile              # 天工镜像（Rust + Node.js + Codex）
│   └── env/                             # 容器专用环境变量
├── docker-compose.yml
├── Makefile
├── config.json                          # 项目级配置模板
├── pyproject.toml                       # Python 依赖管理
└── .env.example                         # 环境变量模板
```

## 技术栈

| 组件 | 选型 |
|------|------|
| 语言 | Python 3.12+ |
| 包管理 | uv |
| API 框架 | FastAPI + uvicorn |
| 飞书 SDK | lark-oapi |
| LLM | OpenAI 兼容接口（Kimi / Doubao / DeepSeek / ...） |
| 定时任务 | APScheduler |
| 本地存储 | aiosqlite + JSONL 文件 |
| 容器化 | Docker Compose（双容器） |
| 天工工具链 | Rust + Codex CLI |

## 设计文档

- [总体架构设计](docs/architecture.md)
- [飞书工具封装设计](docs/feishu-tools-design.md)
- [记忆模块设计](docs/memory-design.md)

## License

MIT
