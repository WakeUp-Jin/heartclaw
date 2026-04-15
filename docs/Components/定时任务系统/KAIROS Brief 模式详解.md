# KAIROS Brief 模式详解

> 本文聚焦 Claude Code KAIROS 自治模式中的 **Brief 模式**：它是什么、和普通模式的区别、以及系统如何通过工具+UI过滤实现"清爽对话"。

---

## 一、Brief 模式是什么

**Brief 模式是一种改变"模型如何与用户对话"的显示模式**。它的核心是引入了一个专属工具 `SendUserMessage`（内部也叫 `BriefTool`），用来把模型的普通文字输出和"正式给用户看的内容"分离开。

### 核心设计思想

系统提示词明确告诉模型：

> *"Text outside this tool is visible in the detail view, but most won't open it — **the answer lives here**.*"
> （工具外的文字在详情视图里可见，但大多数人不会点开——真正的答案在这里。）

也就是说，Brief 模式下模型有两个输出渠道：
1. **普通 assistant text** —— 被提示词降级为"detail view 补充内容"（工作过程、推理草稿）
2. **`SendUserMessage` 工具** —— 被提示词强调为"用户真正会读到的主内容"（答案、状态更新、里程碑通知）

---

## 二、和普通模式的区别

| 维度 | 普通模式 | Brief 模式 |
|------|---------|-----------|
| **输出方式** | 模型直接输出文字，用户直接在终端看到 | 模型被教导用 `SendUserMessage` 工具发送"正式回复" |
| **文字可见性** | 所有 assistant text 默认完全可见 | 同一 turn 中，如果模型调用了 `SendUserMessage`，前面的普通文字会被 UI 自动过滤掉 |
| **渲染样式** | 普通终端对话流 | 可切换到 `chat view`（类似聊天 App，带 "Claude" 标签和时间戳） |
| **附件能力** | 无 | 可以发文件附件（图片、log、diff） |
| **适用场景** | 日常交互、代码审查 | 自治 Agent 持续运行、后台任务状态汇报 |

---

## 三、系统提示词差异

`main.tsx:2201` 根据 brief 是否启用注入不同的行为指导：

```typescript
const briefVisibility = feature('KAIROS') || feature('KAIROS_BRIEF')
  ? (require('./tools/BriefTool/BriefTool.js')).isBriefEnabled()
    ? 'Call SendUserMessage at checkpoints to mark where things stand.'
    : 'The user will see any text you output.'
  : 'The user will see any text you output.';
```

- **普通模式**：*"The user will see any text you output."* —— 模型随便输出文字即可
- **Brief 模式**：*"Call SendUserMessage at checkpoints to mark where things stand."* —— 模型被要求在关键节点通过工具发消息

`constants/prompts.ts` 中还有一段更详细的 `BRIEF_PROACTIVE_SECTION`：

> *"SendUserMessage is where your replies go. Text outside it is visible if the user expands the detail view, but most won't — assume unread. Anything you want them to actually see goes through SendUserMessage."*

并且要求：
- 每次用户说话，正式回复必须走 `SendUserMessage`
- 长任务要先 ack（"On it"），再工作，最后发结果
- 关键节点发 checkpoint（决策、意外发现、阶段边界）
- 跳过 filler（"running tests..." 这种无信息量的占位符）

---

## 四、UI 过滤机制：dropTextInBriefTurns

Brief 模式下，模型通常会在一个 turn 里先输出普通 text（推理过程），再调用 `SendUserMessage` 工具（正式结论）。如果不加处理，用户就会看到重复内容。

`components/Messages.tsx:169` 中的 `dropTextInBriefTurns` 解决了这个问题：

```typescript
/**
 * 当 Brief 工具被调用时，该 turn 中的模型文字输出与 SendUserMessage
 * 内容重复 —— 丢弃文字，只保留 SendUserMessage 块。
 * 工具调用和结果仍然可见。
 */
export function dropTextInBriefTurns<T extends { ... }>(
  messages: T[],
  briefToolNames: string[]
): T[] {
  // 第一遍：找出哪些 turn（以非 meta 的 user 消息为界）包含 Brief 工具调用
  const turnsWithBrief = new Set<number>();
  const textIndexToTurn: number[] = [];
  let turn = 0;
  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i]!;
    const block = msg.message?.content[0];
    if (msg.type === 'user' && block?.type !== 'tool_result' && !msg.isMeta) {
      turn++;
      continue;
    }
    if (msg.type === 'assistant') {
      if (block?.type === 'text') {
        textIndexToTurn[i] = turn;
      } else if (block?.type === 'tool_use' && block.name && nameSet.has(block.name)) {
        turnsWithBrief.add(turn);
      }
    }
  }
  if (turnsWithBrief.size === 0) return messages;
  // 第二遍：过滤掉调用了 Brief 的 turn 中的普通 text
  return messages.filter((_, i) => {
    const t = textIndexToTurn[i];
    return t === undefined || !turnsWithBrief.has(t);
  });
}
```

**关键特性**：
- **按 turn 粒度过滤**，不是全局过滤。只有真正调用了 `SendUserMessage` 的 turn 才会隐藏普通文字。
- **防御性设计**：如果模型忘记调用 `SendUserMessage`，普通文字**仍然会显示**，避免用户看到空白。
- Tool calls 和 tool results 始终保留，不受影响。

---

## 五、三种渲染视图

`tools/BriefTool/UI.tsx` 中定义了 `SendUserMessage` 的三种显示方式：

### 1. Transcript mode (`ctrl+o`)
- 保留所有内容（包括被过滤掉的普通 text）
- `SendUserMessage` 用 ⏺ 标记，与普通 text 视觉区分

### 2. Brief-only / Chat view (`defaultView: 'chat'`)
- **只显示 `SendUserMessage`**，其他内容（普通 text、工具调用细节）隐藏
- 渲染成聊天 App 样式：
  - 左侧有 "Claude" 标签
  - 带时间戳
  - 用户输入显示为 "You" 标签

### 3. Default view（默认终端视图）
- 隐藏冗余的普通 text（通过 `dropTextInBriefTurns`）
- `SendUserMessage` 以纯文本形式渲染，不带工具 chrome（`userFacingName()` 返回空字符串）
- 间距和 `AssistantTextMessage` 对齐，保持阅读习惯一致

---

## 六、激活方式与门控

Brief 模式不是默认开启的，需要满足多层门控（`BriefTool.ts`）：

### 6.1 Entitlement（是否有资格）

```typescript
export function isBriefEntitled(): boolean {
  return feature('KAIROS') || feature('KAIROS_BRIEF')
    ? getKairosActive() ||
        isEnvTruthy(process.env.CLAUDE_CODE_BRIEF) ||
        getFeatureValue_CACHED_WITH_REFRESH('tengu_kairos_brief', false, KAIROS_BRIEF_REFRESH_MS)
    : false;
}
```

- 编译时门控：`feature('KAIROS') || feature('KAIROS_BRIEF')`
- 运行时门控：GrowthBook `tengu_kairos_brief` 灰度开关
- 环境变量绕过：`CLAUDE_CODE_BRIEF=true`（仅用于开发测试）

### 6.2 Activation（是否激活）

```typescript
export function isBriefEnabled(): boolean {
  return feature('KAIROS') || feature('KAIROS_BRIEF')
    ? (getKairosActive() || getUserMsgOptIn()) && isBriefEntitled()
    : false;
}
```

用户必须显式 opt-in 才能激活：
- `--brief` CLI 标志
- `/brief` slash 命令
- `defaultView: 'chat'` 设置项
- SDK `--tools` 选项显式包含 `SendUserMessage`

**例外**：
- **KAIROS/Assistant 模式 bypass opt-in**。因为系统提示词硬编码了 *"you MUST use SendUserMessage"*，所以 `getKairosActive()` 为 true 时直接启用。

---

## 七、SendUserMessage 工具定义

```typescript
// tools/BriefTool/prompt.ts
export const BRIEF_TOOL_NAME = 'SendUserMessage'

export const BRIEF_TOOL_PROMPT = `Send a message the user will read. Text outside this tool is visible in the detail view, but most won't open it — the answer lives here.

\`message\` supports markdown. \`attachments\` takes file paths for images, diffs, logs.

\`status\` labels intent: 'normal' when replying to what they just asked; 'proactive' when you're initiating — a scheduled task finished, a blocker surfaced during background work, you need input on something they haven't asked about.`
```

参数：
- `message`: Markdown 支持的字符串
- `attachments`: 可选文件路径数组（自动解析为图片或附件）
- `status`: `'normal'`（回应用户）或 `'proactive'`（主动推送）

返回值：
```typescript
{
  message: string;
  attachments?: { path, size, isImage, file_uuid? }[];
  sentAt?: string;
}
```

---

## 八、关键源码索引

| 功能 | 文件路径 | 行号/说明 |
|------|---------|----------|
| Brief 工具定义 | `tools/BriefTool/BriefTool.ts` | 完整工具对象、entitlement、activation |
| 工具提示词 | `tools/BriefTool/prompt.ts` | `SendUserMessage` 的 prompt 和描述 |
| UI 渲染 | `tools/BriefTool/UI.tsx` | 三种视图（transcript/chat/default） |
| 文字过滤逻辑 | `components/Messages.tsx` | `dropTextInBriefTurns` |
| 系统提示词注入 | `constants/prompts.ts` | `BRIEF_PROACTIVE_SECTION` |
| 启动时 brief 激活 | `main.tsx` | `maybeActivateBrief()`、`briefVisibility` |
| 激活条件判断 | `tools/BriefTool/BriefTool.ts` | `isBriefEnabled()`、`isBriefEntitled()` |

---

## 九、总结

> **普通模式** = 模型直接打字，用户直接看。所有文字一视同仁。  
> **Brief 模式** = 模型需要通过 `SendUserMessage` 工具来"发正式消息"，普通文字被降级为辅助说明。UI 在同一 turn 中自动隐藏冗余的普通 text，让对话更清爽、更接近聊天 App 的体验。特别适合 KAIROS 这种自治 Agent 需要持续汇报状态、又不希望淹没用户在工具细节中的场景。
