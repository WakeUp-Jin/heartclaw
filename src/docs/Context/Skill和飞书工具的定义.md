# Skill 与飞书工具的定义

> 本文档记录 PineClaw 项目中 Skill 和 Tool 的设计边界，以及飞书能力的实现策略。

---

## 一、核心设计原则

**Tool 存在的唯一理由**：需要拦截、审核、控制执行流程（审批卡片 → 等待回调 → 继续执行）。

**Skill 的定位**：可插拔的能力单元，兼顾执行和说明，与框架解耦，可在 Claude Code、pi、任何支持 Skill 格式的 Agent 框架中加载使用。

```
需要审核控制流  →  Tool（PineClaw ToolScheduler 拦截）
不需要审核控制流 →  Skill（Agent 直接执行）
```

---

## 二、Tool vs Skill vs MCP 的本质区别

| 概念 | 本质 | 执行方 | 典型用途 |
|---|---|---|---|
| **Tool** | 注册到 Agent 的可调用函数 | PineClaw Python 进程 | 需要审核的写操作 |
| **Skill** | Markdown 菜谱 + 可执行脚本 | Agent 的 bash 原语 | 读取、查询、创建等无需审核的操作 |
| **MCP** | 外部工具执行协议（JSON-RPC） | 外部 MCP Server | 对接第三方能力（如 mcp.feishu.cn） |

**关键结论**：Skill 不只是说明文档，也可以包含可执行脚本，通过 Agent 内置的 `bash` 工具直接运行。

---

## 三、为什么写操作不能用 Skill 实现审核流

审核流的控制权在 PineClaw Python 主进程：

```
AI 调用写操作 Tool
    ↓
PineClaw ToolScheduler 拦截
    ↓ 发送飞书审批卡片
    ↓ await asyncio.Future  ← 阻塞等待（Python 主进程）
    ↓
用户点击「批准」→ HTTP 回调 → resolve Future
    ↓
继续执行写操作
```

如果用 Skill 执行写操作（bash 运行脚本），整个过程在 pi 子进程内部完成，**无法在执行中途插入一个等待外部 HTTP 回调的阻塞点**。因此写操作的审核流必须是 Tool，不能是 Skill。

---

## 四、PineClaw 飞书工具的分类

### 保留为 Tool（带审核控制流）

| Tool 名 | 对应操作 | 原因 |
|---|---|---|
| `feishu_doc_edit` | 向文档追加/写入内容块 | 修改共享文档，不可逆 |
| `feishu_record_edit` | 更新/删除多维表格记录 | 修改或破坏已有数据 |
| `feishu_task_update` | 更新任务状态/内容 | 修改已有任务 |

### 迁移为 Skill（无需审核，bash 执行）

| Skill 名 | 对应飞书操作 |
|---|---|
| `feishu-read-doc` | 读取云文档内容 |
| `feishu-list-files` | 浏览云空间文件列表 |
| `feishu-get-file-info` | 获取文件信息 |
| `feishu-list-records` | 查询多维表格记录 |
| `feishu-list-fields` | 查看数据表字段定义 |
| `feishu-list-tasks` | 查询任务列表 |
| `feishu-get-message-history` | 获取消息历史 |
| `feishu-create-doc` | 创建新云文档 |
| `feishu-create-bitable` | 创建多维表格 |
| `feishu-create-records` | 新增记录 |
| `feishu-create-task` | 创建任务 |
| `feishu-create-folder` | 创建文件夹 |

---

## 五、Skill 的目录结构

```
skills/
  feishu-read-doc/
    SKILL.md          ← Agent 读的指令 + 参数说明
    scripts/
      run.sh          ← 直接 curl 飞书 API，无 SDK 依赖

  feishu-list-records/
    SKILL.md
    scripts/
      run.sh

  feishu-create-task/
    SKILL.md
    scripts/
      run.sh
  ...
```

---

## 六、Skill 脚本的实现策略：直接 curl，不用 SDK

**选择 curl 而非 lark-oapi SDK 的原因**：

| | lark-oapi SDK | curl 脚本 |
|---|---|---|
| 依赖 | Python + SDK 包 | 只需 bash + curl |
| 移植性 | 绑定 Python 环境 | 任何有 bash 的环境 |
| 复杂度 | 需初始化 Client 对象 | 两步：拿 token → 调 API |
| 与 Skill 理念契合度 | 低 | 高 |

### 脚本模板

```bash
#!/bin/bash
# 用法: ./run.sh <参数>

# 1. 获取 tenant_access_token
TOKEN=$(curl -s -X POST \
  "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal" \
  -H "Content-Type: application/json" \
  -d "{\"app_id\":\"$FEISHU_APP_ID\",\"app_secret\":\"$FEISHU_APP_SECRET\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['tenant_access_token'])")

# 2. 调飞书 API
curl -s \
  "https://open.feishu.cn/open-apis/..." \
  -H "Authorization: Bearer $TOKEN"
```

**Token 策略**：每次现取（简单可靠）。调用频繁时可缓存到 `/tmp/feishu_token` 文件复用（有效期 2 小时）。

---

## 七、SKILL.md 文件格式

参考 openclaw-lark 的实践，一个完整的 SKILL.md 包含：

```markdown
---
name: feishu-read-doc
description: 读取飞书云文档内容，需要提供 document_id
---

## 使用场景
用户想查看/获取某篇飞书文档的内容时使用。

## 执行

```bash
bash {skill_path}/scripts/run.sh <document_id>
```

## 返回格式
JSON，content 字段为文档纯文本内容。

## 常见参数说明
- document_id：从文档 URL 中获取，形如 `doxXXXXXX`

## 常见错误
| 错误码 | 原因 | 解决 |
|-------|------|------|
| 99991663 | token 无效 | 检查 FEISHU_APP_ID / FEISHU_APP_SECRET 环境变量 |
| 230001 | 无权限访问该文档 | 确认应用已申请 docx:document:readonly 权限 |
```

---

## 八、与外部生态的兼容性

Skills 目录可直接被以下框架加载使用：

| 框架 | 加载路径 | 调用方式 |
|---|---|---|
| **pi-mono** | `.pi/agent/skills/` | `/skill:feishu-read-doc` |
| **Claude Code** | `.claude/skills/` | `/skill:feishu-read-doc` |
| **NanoClaw** | `.claude/skills/` | `/skill:feishu-read-doc` |

可以用符号链接让多个框架共享同一份 Skills 目录，保持同步。

---

## 九、整体架构图

```
PineClaw Agent
  │
  ├── Tools（3-5 个，含审核控制流）
  │     ├── feishu_doc_edit
  │     ├── feishu_record_edit
  │     └── feishu_task_update
  │           ↓
  │     ToolScheduler 拦截
  │     → 发飞书审批卡片
  │     → await 等待用户点击
  │     → 执行或取消
  │
  └── Skills（可插拔，跨框架）
        ├── feishu-read-doc/      scripts/run.sh → curl API
        ├── feishu-list-records/  scripts/run.sh → curl API
        ├── feishu-create-task/   scripts/run.sh → curl API
        └── ...（无审核，Agent bash 直接执行）
```
