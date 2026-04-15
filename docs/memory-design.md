# PineClaw 记忆模块设计

> 基于飞书云文档的长期记忆系统，单文件增量写入 + 本地缓存

---

## 1. 设计理念

PineClaw 的记忆不是对话历史（那是 ConversationContext 的职责），而是 **用户画像和长期事实**。

**核心判断**：用户与 Agent 产生的长期记忆数据量有限（偏好、习惯、重要事实），一个 Markdown 文件完全够用。不需要数据库、不需要向量检索——简单、可读、可直接在飞书打开查看编辑。

**设计原则**：
- **单文件**：飞书云空间一个 `memory.md`，所有记忆以 Markdown 增量追加
- **可读**：用户随时可在飞书中打开这个文件查看/手动编辑
- **省 API**：本地缓存 + 脏标记，不变不读，改了才写
- **每次注入**：每轮 LLM 调用都把记忆注入上下文，让 Agent 始终「认识」用户

## 2. 飞书云空间存储结构

```
飞书云空间（机器人根目录）
└── PineClaw/                    # 由 Agent 首次启动时自动创建
    └── memory.md                # 唯一的记忆文件
```

- **文件夹名**：`PineClaw`（可通过 `FEISHU_MEMORY_FOLDER_NAME` 配置）
- **文件名**：`memory.md`（固定）
- **创建时机**：Agent 首次启动时检测，不存在则自动创建文件夹和空文件

### 初始化流程

```
Agent 启动
  │
  ├── GET /drive/v1/files（列出根目录，查找 PineClaw 文件夹）
  │     ├── 找到 → 记录 folder_token
  │     └── 未找到 → POST /drive/v1/files/create_folder 创建
  │
  ├── GET /drive/v1/files（列出 PineClaw 文件夹，查找 memory.md）
  │     ├── 找到 → 记录 document_id
  │     └── 未找到 → POST /docx/v1/documents 创建空文档
  │
  └── 读取 memory.md 内容 → 加载到本地缓存
```

## 3. memory.md 文件格式

采用结构化 Markdown，LLM 既能读懂也能按格式追加：

```markdown
# PineClaw Memory

## 用户画像
- 名字：小明
- 角色：后端开发工程师
- 常用技术栈：Python, TypeScript, FastAPI
- 偏好：喜欢简洁的代码风格，不喜欢过度封装

## 工作习惯
- 每天 10 点开始工作
- 习惯用飞书文档做技术方案
- 喜欢用多维表格做项目管理

## 重要事实
- [2026-03-10] 正在开发 PineClaw 项目，Python + FastAPI
- [2026-03-11] 确定使用飞书单聊模式作为唯一入口
- [2026-03-11] 记忆文件存放在飞书云空间 PineClaw 文件夹下

## 偏好指令
- 回复使用中文
- 代码注释尽量少，只注释非显而易见的逻辑
```

**格式约定**：
- 一级标题固定为 `# PineClaw Memory`
- 二级标题为分类（用户画像 / 工作习惯 / 重要事实 / 偏好指令，可由 LLM 自行扩展）
- 重要事实条目带日期 `[YYYY-MM-DD]`
- LLM 负责判断什么值得记住，并按此格式追加或修改

## 4. 缓存与同步机制

核心问题：memory.md 存在飞书云端，但不能每次对话都调 API 读一遍。

### 4.1 状态模型

```
                  ┌──────────────┐
                  │  飞书云文档   │
                  │  memory.md   │
                  └──────┬───────┘
                         │
              ┌──────────┴──────────┐
              │  MemoryStore        │
              │  ┌────────────────┐ │
              │  │ _cache: str    │ │  ← 内存中的 memory.md 全文
              │  │ _dirty: bool   │ │  ← 是否有本地未同步的修改
              │  │ _doc_id: str   │ │  ← 飞书 document_id
              │  │ _version: int  │ │  ← 本地版本号（每次写入 +1）
              │  └────────────────┘ │
              └─────────────────────┘
```

### 4.2 读取策略（省 API）

```
get_context() 被调用（每轮对话）
  │
  ├── _cache 不为空 且 _dirty == False
  │     └── 直接返回 _cache（零 API 调用）
  │
  └── _cache 为空（首次）
        └── 从飞书读取 → 存入 _cache → 返回
```

**关键规则**：
- Agent 进程生命周期内，**只在启动时从飞书读取一次**
- 之后每次 `get_context()` 直接读内存缓存，**不调 API**
- 只有当 LLM 通过工具修改了 memory.md 后，才需要重新同步（见写入策略）

### 4.3 写入策略（增量追加）

LLM 判断对话中产生了值得记录的长期记忆时，调用 `memory_append` 工具：

```
LLM 调用 memory_append 工具
  │
  ├── 1. 将新内容追加到 _cache（本地内存）
  │
  ├── 2. 标记 _dirty = True, _version += 1
  │
  ├── 3. 异步写入飞书云文档
  │     └── POST /docx/v1/documents/{doc_id}/blocks/{block_id}/children
  │         （在文档末尾追加新的文本块）
  │
  └── 4. 写入成功 → _dirty = False
        写入失败 → 保持 _dirty = True，下次重试
```

**为什么不需要写入后重新读取**：
- 写入的内容就是从 `_cache` 来的，本地已经是最新
- 只有一个 Agent 实例在写，不存在并发冲突
- 如果用户在飞书手动编辑了文件，需要 Agent 重启才会读到最新（可接受的取舍）

### 4.4 完整数据流

```
Agent 启动
  │
  ▼ 初始化 MemoryStore
  │  ├── 从飞书读取 memory.md → _cache
  │  └── _dirty = False
  │
  ▼ 用户发来消息
  │
  ▼ ContextManager.get_context()
  │  ├── system_prompt  ← 系统提示词
  │  ├── memory         ← MemoryStore._cache（零 API）
  │  ├── conversation   ← 对话历史
  │  └── tool_sequence  ← 工具序列
  │
  ▼ LLM 推理 + 工具循环
  │  ├── LLM 判断需要记住某些信息
  │  └── 调用 memory_append(content="- [2026-03-11] 用户喜欢...")
  │       ├── _cache 追加
  │       └── 异步写入飞书
  │
  ▼ LLM 返回最终回复
  │
  ▼ 下一轮对话…（memory 已是最新，无需 API）
```

## 5. MemoryStore 类设计

```python
class MemoryStore:
    """飞书云文档记忆管理器，本地缓存 + 按需同步"""

    def __init__(self, feishu_client: FeishuClient, folder_name: str = "PineClaw"):
        self._client = feishu_client
        self._folder_name = folder_name
        self._cache: str = ""
        self._dirty: bool = False
        self._version: int = 0
        self._doc_id: str | None = None
        self._folder_token: str | None = None
        self._initialized: bool = False

    async def initialize(self) -> None:
        """启动时调用：确保文件夹和文件存在，加载缓存"""
        self._folder_token = await self._ensure_folder()
        self._doc_id = await self._ensure_document()
        self._cache = await self._read_from_feishu()
        self._initialized = True

    def get_memory_text(self) -> str:
        """返回当前记忆全文（直接读缓存，零 API 调用）"""
        return self._cache

    async def append(self, content: str) -> bool:
        """追加记忆条目：先更新缓存，再异步写飞书"""
        self._cache += f"\n{content}"
        self._dirty = True
        self._version += 1
        
        success = await self._write_to_feishu(content)
        if success:
            self._dirty = False
        return success

    async def replace(self, new_content: str) -> bool:
        """全量替换记忆（用于 LLM 整理/去重场景）"""
        old_cache = self._cache
        self._cache = new_content
        self._dirty = True
        self._version += 1

        success = await self._overwrite_feishu_doc(new_content)
        if success:
            self._dirty = False
        else:
            self._cache = old_cache  # 回滚
            self._dirty = True
        return success

    async def force_sync(self) -> None:
        """强制从飞书重新读取（用户手动编辑后调用）"""
        self._cache = await self._read_from_feishu()
        self._dirty = False

    # --- 私有方法 ---

    async def _ensure_folder(self) -> str:
        """确保云空间中存在 PineClaw 文件夹，返回 folder_token"""
        # GET /drive/v1/files 查找
        # 不存在则 POST /drive/v1/files/create_folder
        ...

    async def _ensure_document(self) -> str:
        """确保文件夹内存在 memory.md，返回 document_id"""
        # GET /drive/v1/files 查找
        # 不存在则 POST /docx/v1/documents 创建
        ...

    async def _read_from_feishu(self) -> str:
        """从飞书读取 memory.md 全文"""
        # GET /docx/v1/documents/{doc_id}/raw_content
        ...

    async def _write_to_feishu(self, content: str) -> bool:
        """增量追加内容到飞书文档末尾"""
        # POST /docx/v1/documents/{doc_id}/blocks/{block_id}/children
        ...

    async def _overwrite_feishu_doc(self, content: str) -> bool:
        """全量覆写飞书文档（清空后重写）"""
        ...
```

## 6. Agent 工具：memory_append 和 memory_rewrite

LLM 通过两个工具操作记忆，由 LLM 自主决定何时调用：

### 6.1 memory_append

```python
memory_append_def = {
    "type": "function",
    "function": {
        "name": "memory_append",
        "description": "向长期记忆追加一条新信息。当对话中出现值得长期记住的用户偏好、"
                       "个人信息、工作习惯或重要事实时调用。不要记录临时性信息。"
                       "格式：Markdown 列表项，重要事实带日期前缀 [YYYY-MM-DD]。",
        "parameters": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": "记忆分类，如：用户画像、工作习惯、重要事实、偏好指令",
                },
                "content": {
                    "type": "string",
                    "description": "要追加的记忆内容，Markdown 格式",
                },
            },
            "required": ["section", "content"],
        },
    },
}
```

**handler 逻辑**：

```python
async def memory_append_handler(memory_store: MemoryStore, args: dict) -> str:
    section = args["section"]
    content = args["content"]

    # 查找缓存中是否已有该 section
    if f"## {section}" in memory_store.get_memory_text():
        # 在该 section 末尾追加
        append_text = f"- {content}"
    else:
        # 新建 section
        append_text = f"\n## {section}\n- {content}"

    success = await memory_store.append(append_text)
    if success:
        return f"已记住：{content}"
    else:
        return "记忆写入飞书失败，已缓存在本地，将在下次对话时重试"
```

### 6.2 memory_rewrite

当记忆变得冗长或有重复时，LLM 可以调用此工具整理记忆：

```python
memory_rewrite_def = {
    "type": "function",
    "function": {
        "name": "memory_rewrite",
        "description": "整理和重写整个记忆文件。当记忆内容出现重复、过时或需要重新组织时调用。"
                       "传入整理后的完整 Markdown 内容，将替换现有记忆。谨慎使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "整理后的完整记忆内容，Markdown 格式，必须以 '# PineClaw Memory' 开头",
                },
            },
            "required": ["content"],
        },
    },
}
```

## 7. ContextManager 集成

记忆作为 MemoryContext 注入，位于 system_prompt 之后、conversation 之前：

```python
class MemoryContext(BaseContext):
    """从 MemoryStore 读取记忆，注入到 LLM 上下文"""

    def __init__(self, memory_store: MemoryStore):
        self._store = memory_store

    def get_messages(self) -> list[dict]:
        text = self._store.get_memory_text()
        if not text.strip():
            return []

        return [
            {
                "role": "system",
                "content": (
                    "以下是你对用户的长期记忆，请基于这些信息个性化回复：\n\n"
                    f"{text}"
                ),
            }
        ]
```

**上下文组装顺序**：

```
messages = [
    system_prompt,      # 你是 PineClaw，一个飞书 AI 助手...
    memory,             # 用户画像、偏好、历史事实（来自飞书 memory.md）
    *conversation,      # 近期对话历史
    *tool_sequence,     # 当前工具调用序列
]
```

每次 LLM 调用都会包含记忆，让 Agent 始终「认识」用户，但 **不产生任何额外 API 调用**（直接读 MemoryStore 的内存缓存）。

## 8. API 调用开销分析

| 场景 | 飞书 API 调用次数 | 说明 |
|------|-------------------|------|
| Agent 启动 | 2-4 次 | 查找/创建文件夹 + 查找/创建文档 + 读取内容 |
| 普通对话（无记忆更新） | 0 次 | 直接读内存缓存 |
| 对话中产生新记忆 | 1 次 | 追加写入飞书文档 |
| 记忆整理 | 1 次 | 全量覆写飞书文档 |
| Agent 重启 | 2 次 | 查找文件夹 + 读取内容 |

**预期**：大部分对话不会触发记忆写入，Agent 长期运行期间飞书 API 的记忆相关调用极少。

## 9. 边界情况处理

| 场景 | 处理策略 |
|------|---------|
| 飞书 API 写入失败 | `_dirty` 保持 True，本地缓存不丢，下次 append 时重试 |
| 用户在飞书手动编辑 memory.md | Agent 不感知，重启后自动加载最新。可扩展轮询机制（暂不做） |
| memory.md 内容过长（>50KB） | LLM 调用 `memory_rewrite` 精简。系统提示词中提醒 LLM 关注文件大小 |
| Agent 异常崩溃 | 本地缓存丢失但飞书云端有最新数据，重启即恢复 |
| 多个 Agent 实例 | 当前设计为单实例。多实例需引入飞书文档版本号做乐观锁（暂不做） |

## 10. 目录结构

```
memory/
├── __init__.py
├── memory_store.py       # MemoryStore 类（本文档第 5 节）
└── memory_context.py     # MemoryContext 类（本文档第 7 节）
```

工具注册在 `core/tool/feishu/` 目录，或单独放置：

```
core/tool/
├── memory_tools.py       # memory_append / memory_rewrite 定义和 handler
└── feishu/
    └── ...
```

## 11. 系统提示词中的记忆指引

在 system_prompt 中加入以下指引，让 LLM 知道如何使用记忆系统：

```
你有一个长期记忆系统。你可以通过以下方式使用它：

1. **读取记忆**：每次对话开始时，你的上下文中会自动包含记忆内容，无需手动读取。

2. **写入记忆**：当对话中出现以下情况时，调用 memory_append 工具记录：
   - 用户提到个人信息（名字、职业、团队等）
   - 用户表达偏好（代码风格、回复语言、工作习惯等）
   - 发生重要事件或决策
   - 不要记录临时性、一次性的信息

3. **整理记忆**：如果记忆内容变得冗长或有重复，调用 memory_rewrite 整理。

4. **基于记忆回复**：始终参考记忆中的用户画像和偏好来个性化你的回复。
```
