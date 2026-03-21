# LLM 模块架构与开发指南

## 概述

LLM 模块是 PineClaw Agent 的核心驱动层，负责对接大语言模型供应商的 API。采用**统一接口 + 工厂模式 + 分层注册表**的架构，支持多供应商、多模型分级和自动重试。

设计原则：
- 不使用 LangChain 等框架，自定义封装保持轻量
- 所有供应商统一为 `complete()` 和 `simple_chat()` 两个核心接口
- 通过 ModelTier 分级实现质量与成本的平衡

---

## 目录结构

```
src/core/llm/
├── __init__.py              # 统一导出
├── types.py                 # 类型定义：LLMConfig, LLMResponse, ToolCall, ModelTier
├── factory.py               # create_llm_service 工厂函数
├── registry.py              # LLMServiceRegistry（按 ModelTier 缓存）
├── services/
│   ├── __init__.py
│   ├── base.py              # BaseLLMService 基类（含重试、simple_chat）
│   ├── kimi_service.py      # Kimi / Moonshot 服务
│   ├── volcengine_service.py # 火山引擎 / Doubao 服务
│   └── openai_service.py    # OpenAI / DeepSeek 通用服务
└── utils/
    ├── llm_helpers.py       # 辅助函数（extract_api_key, get_base_url 等）
    └── tool_loop.py         # LLM ↔ 工具 循环执行器
```

关联模块：

```
config.json                  # 项目配置（LLM 模型分级、重试参数等）
.env                         # 敏感 API Key
src/config/settings.py       # AppConfig 全局配置单例
src/utils/logger.py          # 模块级日志
```

---

## 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                        调用方                                │
│   SimpleAgent / ContextManager / 任何需要 LLM 的模块          │
└──────────┬──────────────────────────────────┬───────────────┘
           │                                  │
           ▼                                  ▼
  registry.get_high()                registry.get_low()
           │                                  │
           ▼                                  ▼
┌──────────────────────────────────────────────────────────────┐
│                   LLMServiceRegistry                         │
│                                                              │
│   ┌─────────┐    ┌──────────┐    ┌─────────┐                │
│   │  HIGH   │    │  MEDIUM  │    │   LOW   │    ← ModelTier │
│   │  缓存   │    │   缓存   │    │  缓存   │                │
│   └────┬────┘    └────┬─────┘    └────┬────┘                │
│        │              │               │                      │
│        └──────────────┴───────────────┘                      │
│                       │                                      │
│              create_llm_service()   ← 工厂函数               │
│                       │                                      │
│            ┌──────────┼──────────┐                           │
│            ▼          ▼          ▼                           │
│       KimiService  VolcEngine  OpenAIService                 │
│            │          │          │                           │
│            └──────────┴──────────┘                           │
│                       │                                      │
│               BaseLLMService                                 │
│          (complete / simple_chat / retry)                     │
└──────────────────────────────────────────────────────────────┘
```

---

## 核心概念

### ModelTier 模型分级

不同场景使用不同质量的模型，平衡推理质量和调用成本：

| 层级 | 用途 | 默认模型 | 选择原则 |
|------|------|---------|---------|
| **HIGH** | Agent 主循环、核心推理、工具调用 | kimi-k2.5（Moonshot） | 质量优先 |
| **MEDIUM** | 辅助任务、次要推理 | kimi-k2.5（Moonshot） | 质量与成本兼顾 |
| **LOW** | 历史压缩、摘要、简单分类 | doubao-seed-2.0-lite（火山引擎） | 成本优先，快且便宜 |

```python
from core.llm.types import ModelTier

# 枚举值
ModelTier.HIGH    # "high"
ModelTier.MEDIUM  # "medium"
ModelTier.LOW     # "low"
```

### ILLMService 统一接口

所有 LLM 服务类都满足同一个 Protocol，上层代码不关心具体供应商：

```python
class ILLMService(Protocol):
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse: ...

    async def simple_chat(
        self,
        user_input: str,
        system_prompt: str = "",
    ) -> str: ...
```

- **`complete`**：核心方法，接收消息列表和工具定义，返回 `LLMResponse`
- **`simple_chat`**：便捷方法，无工具的单轮对话，直接返回文本

---

## 类型定义

文件：`src/core/llm/types.py`

### LLMConfig

```python
@dataclass
class LLMConfig:
    provider: str = ""        # "kimi" | "volcengine" | "openai" | "deepseek"
    api_key: str = ""
    base_url: str = ""
    model: str = ""           # 模型名称
    temperature: float = 0.7
    max_tokens: int = 4096
    max_retries: int = 3      # 重试次数
```

### LLMResponse

```python
@dataclass
class LLMResponse:
    content: str | None = None           # 模型返回的文本
    tool_calls: list[ToolCall] = []      # 工具调用列表
    usage: TokenUsage = TokenUsage()     # token 用量
    finish_reason: str = "stop"          # "stop" | "tool_calls" | "length"

    @property
    def has_tool_calls(self) -> bool:    # 是否包含工具调用
        return len(self.tool_calls) > 0
```

### ToolCall

```python
@dataclass
class ToolCall:
    id: str           # 工具调用 ID
    name: str         # 函数名
    arguments: str    # 参数 JSON 字符串
```

### TokenUsage

```python
@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens
```

---

## 服务类体系

### BaseLLMService 基类

文件：`src/core/llm/services/base.py`

基类承担三个职责：

1. **统一接口**：`complete()` 和 `simple_chat()` 对外暴露
2. **自动重试**：`_complete_with_retry()` 实现指数退避 + 随机抖动
3. **子类契约**：子类只需实现 `_do_complete()` 一个抽象方法

```
调用方
  │
  ▼
complete()
  │
  ▼
_complete_with_retry()  ← 重试逻辑（指数退避）
  │
  ▼
_do_complete()          ← 子类实现（实际 API 调用）
```

**重试策略：**
- 最大重试次数由 `config.max_retries` 控制（默认 3）
- 退避公式：`delay = min(1.0 * 2^attempt + random(0,1), 30.0)`
- 可重试错误：429（限流）、5xx（服务端错误）、网络超时
- 不可重试错误：400（请求错误）、401（认证错误）、403（权限错误）

**simple_chat 的实现：**

`simple_chat` 不需要子类重写，它在基类中自动将参数包装为消息列表后调用 `complete`：

```python
async def simple_chat(self, user_input: str, system_prompt: str = "") -> str:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_input})
    response = await self.complete(messages, tools=None)
    return response.content or ""
```

### KimiService

文件：`src/core/llm/services/kimi_service.py`

- 供应商：Moonshot AI（Kimi）
- 默认 Base URL：`https://api.moonshot.cn/v1`
- 兼容 OpenAI SDK 格式
- 默认模型：`kimi-k2.5`（256K 上下文窗口）

### VolcEngineService

文件：`src/core/llm/services/volcengine_service.py`

- 供应商：火山引擎（字节跳动）
- 默认 Base URL：`https://ark.cn-beijing.volces.com/api/v3`
- 兼容 OpenAI SDK 格式
- 默认模型：`doubao-seed-2.0-lite`（256K 上下文，极低成本）

### OpenAIService

文件：`src/core/llm/services/openai_service.py`

- 通用 OpenAI SDK 兼容服务（同时覆盖 OpenAI 和 DeepSeek）
- 作为向后兼容保留

---

## 工厂函数

文件：`src/core/llm/factory.py`

`create_llm_service(config)` 根据 `LLMConfig.provider` 创建对应的服务实例：

```python
_PROVIDERS = {
    "kimi":       KimiService,
    "volcengine": VolcEngineService,
    "openai":     OpenAIService,
    "deepseek":   OpenAIService,
}
```

创建前会通过 `llm_helpers` 自动解析 `api_key` 和 `base_url`：

```python
service = create_llm_service(LLMConfig(
    provider="kimi",
    api_key="sk-xxx",
    model="kimi-k2.5",
))
```

---

## LLMServiceRegistry 注册表

文件：`src/core/llm/registry.py`

按 ModelTier 管理服务实例的核心组件，具有三个特性：

1. **延迟创建**：首次调用 `get_service()` 时才创建实例
2. **单例缓存**：同一 tier 返回相同实例
3. **配置感知**：检测到 provider/model 变更时自动重建

```python
from config.settings import settings
from core.llm.registry import LLMServiceRegistry

registry = LLMServiceRegistry(settings)

# 获取不同层级的服务
high_llm = registry.get_high()      # KimiService (kimi-k2.5)
medium_llm = registry.get_medium()  # KimiService (kimi-k2.5)
low_llm = registry.get_low()        # VolcEngineService (doubao-seed-2.0-lite)

# 缓存生效：第二次调用返回同一实例
assert registry.get_high() is high_llm  # True

# 清除所有缓存（配置更新后调用）
registry.invalidate_all()
```

---

## 辅助函数

文件：`src/core/llm/utils/llm_helpers.py`

### extract_api_key

提取 API Key，优先使用 config 中的值，对无需 Key 的供应商返回占位符：

```python
extract_api_key(LLMConfig(provider="kimi", api_key="sk-xxx"))  # → "sk-xxx"
extract_api_key(LLMConfig(provider="ollama"))                   # → "not-required"
extract_api_key(LLMConfig(provider="kimi"))                     # → ValueError
```

### get_base_url

获取供应商的 Base URL，优先用户配置，否则查默认映射表：

```python
get_base_url(LLMConfig(provider="kimi"))  # → "https://api.moonshot.cn/v1"
get_base_url(LLMConfig(provider="kimi", base_url="https://custom.url"))  # → "https://custom.url"
```

内置默认 Base URL 映射表：

| Provider | Base URL |
|----------|----------|
| kimi | `https://api.moonshot.cn/v1` |
| volcengine | `https://ark.cn-beijing.volces.com/api/v3` |
| deepseek | `https://api.deepseek.com` |
| openai | `https://api.openai.com/v1` |
| anthropic | `https://api.anthropic.com` |
| siliconflow | `https://api.siliconflow.cn/v1` |
| qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| openrouter | `https://openrouter.ai/api/v1` |
| ollama | `http://localhost:11434/v1` |
| lmstudio | `http://localhost:1234/v1` |

### get_default_context_window

获取供应商/模型的默认上下文窗口大小：

```python
get_default_context_window("kimi", "kimi-k2.5")           # → 256000
get_default_context_window("volcengine")                   # → 128000
get_default_context_window("openai", "gpt-4o")             # → 128000
get_default_context_window("unknown_provider")             # → 8192 (兜底)
```

---

## 配置系统

### config.json

项目根目录的 JSON 配置文件，通过 `${VAR}` 引用环境变量：

```json
{
  "llm": {
    "models": {
      "high": {
        "provider": "kimi",
        "model": "kimi-k2.5",
        "api_key": "${KIMI_API_KEY}",
        "base_url": "https://api.moonshot.cn/v1",
        "temperature": 0.7,
        "max_tokens": 4096
      },
      "medium": { ... },
      "low": {
        "provider": "volcengine",
        "model": "doubao-seed-2.0-lite",
        "api_key": "${VOLCENGINE_API_KEY}",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "temperature": 0.7,
        "max_tokens": 2048
      }
    },
    "retry": {
      "max_retries": 3,
      "base_delay": 1.0,
      "max_delay": 30.0
    }
  }
}
```

### .env

仅存放敏感的 API Key：

```
KIMI_API_KEY=sk-xxxxxxxx
VOLCENGINE_API_KEY=xxxxxxxx
```

### AppConfig 单例

`settings = load_config()` 在 import 时自动加载，全局可用：

```python
from config.settings import settings

# 直接访问 LLM 模型配置
cfg = settings.get_llm_model_config("high")
print(cfg.provider)  # "kimi"
print(cfg.model)     # "kimi-k2.5"

# 访问重试配置
print(settings.llm.retry.max_retries)  # 3
```

加载流程：

```
.env → os.environ → config.json → ${VAR} 替换 → AppConfig dataclass
```

---

## 日志模块

文件：`src/utils/logger.py`

支持模块级日志，通过 `get_logger(name)` 获取子 logger：

```python
from utils.logger import get_logger

logger = get_logger("llm.kimi")
logger.info("request sent")
# 输出：[2026-03-21 20:00:00] INFO pineclaw.llm.kimi - request sent
```

日志层级映射关系：

```
pineclaw                    ← 根 logger
├── pineclaw.agent          ← SimpleAgent
├── pineclaw.llm            ← LLM 基类
│   ├── pineclaw.llm.kimi       ← KimiService
│   ├── pineclaw.llm.volcengine ← VolcEngineService
│   ├── pineclaw.llm.openai     ← OpenAIService
│   ├── pineclaw.llm.factory    ← 工厂函数
│   ├── pineclaw.llm.registry   ← 注册表
│   └── pineclaw.llm.tool_loop  ← 工具循环
└── ...
```

---

## 使用示例

### 在 Agent 中使用（推荐方式）

通过 `LLMServiceRegistry` 获取不同层级的服务：

```python
from config.settings import settings
from core.llm.registry import LLMServiceRegistry

registry = LLMServiceRegistry(settings)

# 主循环使用 HIGH 模型
llm = registry.get_high()
response = await llm.complete(messages, tools)

# 压缩摘要使用 LOW 模型（省成本）
summary = await registry.get_low().simple_chat(
    long_text,
    system_prompt="请将对话压缩为简洁摘要。",
)
```

### 直接创建服务（灵活方式）

不经过 Registry，直接用工厂函数创建：

```python
from core.llm.types import LLMConfig
from core.llm.factory import create_llm_service

service = create_llm_service(LLMConfig(
    provider="kimi",
    api_key="sk-xxx",
    model="kimi-k2.5",
))

answer = await service.simple_chat("什么是大语言模型？")
```

### 工具循环

`execute_tool_loop` 实现 LLM → 工具调用 → 结果返回 → LLM 的多轮循环：

```python
from core.llm.utils.tool_loop import execute_tool_loop

response_text, usage, tool_messages = await execute_tool_loop(
    llm=registry.get_high(),
    messages=context_messages,
    tools=formatted_tools,
    scheduler=tool_scheduler,
    chat_id=chat_id,
)
```

---

## 添加新的 LLM 供应商

按以下步骤操作：

### 第 1 步：创建服务类

在 `src/core/llm/services/` 下新建文件，继承 `BaseLLMService`，只需实现 `_do_complete`：

```python
# src/core/llm/services/new_provider_service.py

from core.llm.services.base import BaseLLMService
from core.llm.types import LLMConfig, LLMResponse, TokenUsage, ToolCall

class NewProviderService(BaseLLMService):
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        # 初始化客户端...

    async def _do_complete(self, messages, tools=None, **kwargs):
        # 调用供应商 API...
        # 返回 LLMResponse
        return LLMResponse(content=..., tool_calls=..., usage=..., finish_reason=...)
```

### 第 2 步：注册到工厂

在 `factory.py` 的 `_PROVIDERS` 字典中添加映射：

```python
_PROVIDERS = {
    ...
    "new_provider": NewProviderService,
}
```

### 第 3 步：更新辅助函数

在 `llm_helpers.py` 的 `DEFAULT_BASE_URLS` 中添加默认 URL：

```python
DEFAULT_BASE_URLS = {
    ...
    "new_provider": "https://api.new-provider.com/v1",
}
```

### 第 4 步：配置

在 `config.json` 中配置对应的模型层级，在 `.env` 中添加 API Key。

完成。`complete()`、`simple_chat()`、重试机制全部自动继承，无需额外代码。

---

## 数据流全景

```
用户输入
  │
  ▼
SimpleAgent.run()
  │
  ├─── registry.get_high()  → KimiService
  │         │
  │         ▼
  │    execute_tool_loop()
  │         │
  │         ├── llm.complete(messages, tools)
  │         │       │
  │         │       ▼
  │         │   BaseLLMService._complete_with_retry()
  │         │       │
  │         │       ▼
  │         │   KimiService._do_complete()
  │         │       │
  │         │       ▼
  │         │   OpenAI SDK → Moonshot API
  │         │       │
  │         │       ▼
  │         │   LLMResponse (content / tool_calls)
  │         │
  │         ├── [有 tool_calls] → ToolScheduler.schedule_batch()
  │         │                          │
  │         │                          ▼
  │         │                     工具执行结果
  │         │                          │
  │         │                     ┌────┘
  │         └── 循环直到无 tool_calls
  │
  ├─── [需要压缩] → registry.get_low()  → VolcEngineService
  │         │
  │         ▼
  │    simple_chat(对话内容, "请压缩为摘要")
  │         │
  │         ▼
  │    VolcEngine API → 摘要文本
  │
  ▼
返回给用户
```
