# BashTool 实现分析

> 基于 Claude Code（claudecode-src）源码的深度分析文档

## 1. 总体架构概览

BashTool 是 Claude Code 中最核心的工具之一，负责在终端中执行 shell 命令。其架构围绕三个核心关注点设计：**命令执行**、**权限控制**、**安全验证**。

### 1.1 文件结构

```
tools/BashTool/
├── BashTool.tsx              # 主工具定义，包含 call()、prompt()、权限检查入口等
├── bashPermissions.ts        # 权限系统核心：规则匹配、deny/ask/allow 决策逻辑
├── bashSecurity.ts           # 安全检查：命令注入检测、危险模式识别
├── bashCommandHelpers.ts     # 管道/操作符的权限处理
├── readOnlyValidation.ts     # 只读命令判定（自动放行逻辑）
├── pathValidation.ts         # 路径约束检查（防止越权操作）
├── sedValidation.ts          # sed 命令专项验证
├── modeValidation.ts         # 模式相关的权限处理
├── shouldUseSandbox.ts       # 沙箱启用判断
├── commandSemantics.ts       # 退出码语义解释（grep返回1不是错误等）
├── prompt.ts                 # 系统提示词构建
├── toolName.ts               # 工具名常量 "Bash"
├── UI.tsx                    # 渲染工具使用消息的 UI 组件
├── BashToolResultMessage.tsx  # 结果展示 UI 组件
├── utils.ts                  # 通用工具函数
├── destructiveCommandWarning.ts # 破坏性命令警告
├── commentLabel.ts           # 注释标签
└── sedEditParser.ts          # sed 编辑命令解析

utils/
├── Shell.ts                  # Shell 执行引擎：进程 spawn、cwd 管理
├── ShellCommand.ts           # ShellCommand 包装器
├── shell/
│   ├── bashProvider.ts       # Bash shell provider（命令构建、快照、环境变量）
│   ├── shellProvider.ts      # ShellProvider 接口定义
│   ├── powershellProvider.ts # PowerShell provider
│   └── resolveDefaultShell.ts # shell 路径解析
├── bash/
│   ├── ast.ts                # tree-sitter AST 解析与安全检查
│   ├── commands.ts           # 命令分割、操作符提取
│   ├── shellQuote.ts         # shell 引号解析
│   ├── shellQuoting.ts       # 命令引号化
│   ├── ParsedCommand.ts      # 解析后的命令结构
│   ├── heredoc.ts            # heredoc 提取
│   ├── shellPrefix.ts        # CLAUDE_CODE_SHELL_PREFIX 支持
│   ├── ShellSnapshot.ts      # shell 环境快照
│   └── bashPipeCommand.ts    # 管道命令重排
└── permissions/
    ├── bashClassifier.ts     # AI 分类器权限决策
    └── shellRuleMatching.ts  # shell 权限规则匹配
```

## 2. 工具定义（BashTool.tsx）

### 2.1 输入 Schema

```typescript
const fullInputSchema = z.strictObject({
  command: z.string().describe('The command to execute'),
  timeout: semanticNumber(z.number().optional())
    .describe(`Optional timeout in milliseconds (max ${getMaxTimeoutMs()})`),
  description: z.string().optional()
    .describe('Clear, concise description of what this command does'),
  run_in_background: semanticBoolean(z.boolean().optional())
    .describe('Set to true to run in background'),
  dangerouslyDisableSandbox: semanticBoolean(z.boolean().optional())
    .describe('Override sandbox mode'),
  _simulatedSedEdit: z.object({...}).optional()  // 内部字段，不暴露给模型
})
```

**关键设计决策：**
- `_simulatedSedEdit` 从模型可见的 schema 中排除（`.omit()`），防止模型绕过权限检查
- 当 `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` 启用时，`run_in_background` 也被隐藏
- 使用 `semanticNumber` 和 `semanticBoolean` 包装，支持模型发送语义化值

### 2.2 输出 Schema

```typescript
const outputSchema = z.object({
  stdout: z.string(),
  stderr: z.string(),
  rawOutputPath: z.string().optional(),     // 大输出文件路径
  interrupted: z.boolean(),                  // 命令是否被中断
  isImage: z.boolean().optional(),           // stdout 是否包含图片数据
  backgroundTaskId: z.string().optional(),   // 后台任务ID
  backgroundedByUser: z.boolean().optional(),
  assistantAutoBackgrounded: z.boolean().optional(),
  dangerouslyDisableSandbox: z.boolean().optional(),
  returnCodeInterpretation: z.string().optional(), // 退出码语义解释
  noOutputExpected: z.boolean().optional(),
  structuredContent: z.array(z.any()).optional(),
  persistedOutputPath: z.string().optional(),     // 持久化输出路径
  persistedOutputSize: z.number().optional(),
})
```

### 2.3 核心方法

#### `buildTool()` 配置

```typescript
export const BashTool = buildTool({
  name: 'Bash',
  searchHint: 'execute shell commands',
  maxResultSizeChars: 30_000,  // 30K字符 - 超出则持久化到文件
  strict: true,

  // 并发安全检查：只有只读命令可以并发
  isConcurrencySafe(input) {
    return this.isReadOnly?.(input) ?? false
  },

  // 只读判定
  isReadOnly(input) {
    const compoundCommandHasCd = commandHasAnyCd(input.command)
    return checkReadOnlyConstraints(input, compoundCommandHasCd).behavior === 'allow'
  },

  // 权限检查入口
  async checkPermissions(input, context) {
    return bashToolHasPermission(input, context)
  },

  // 输入验证（sleep 命令拦截）
  async validateInput(input) {
    if (feature('MONITOR_TOOL') && !isBackgroundTasksDisabled) {
      const sleepPattern = detectBlockedSleepPattern(input.command)
      if (sleepPattern !== null) return { result: false, message: '...' }
    }
    return { result: true }
  },
  // ...
})
```

#### 命令分类

工具内部维护了多组命令集合，用于 UI 折叠和语义判断：

| 命令集合 | 包含命令 | 用途 |
|---------|---------|------|
| `BASH_SEARCH_COMMANDS` | find, grep, rg, ag, ack, locate, which, whereis | 搜索类，UI 可折叠 |
| `BASH_READ_COMMANDS` | cat, head, tail, less, more, wc, stat, jq, awk, cut, sort, uniq, tr | 读取类，UI 可折叠 |
| `BASH_LIST_COMMANDS` | ls, tree, du | 目录列举类 |
| `BASH_SEMANTIC_NEUTRAL_COMMANDS` | echo, printf, true, false, : | 语义中性，不影响管道属性 |
| `BASH_SILENT_COMMANDS` | mv, cp, rm, mkdir, chmod, touch, ln, cd, export... | 成功时无 stdout |

#### `call()` 执行流程

```
call(input, context)
  ├── 1. 检查 _simulatedSedEdit → applySedEdit() 直接写入
  ├── 2. 创建 runShellCommand 异步生成器
  ├── 3. 消费生成器，报告进度 (onProgress)
  ├── 4. 获取最终结果
  ├── 5. trackGitOperations() 追踪 git 操作
  ├── 6. interpretCommandResult() 语义化退出码
  ├── 7. 处理大输出 → 持久化到文件
  ├── 8. 检查代码索引命令
  ├── 9. 返回 { stdout, stderr, interrupted, ... }
  └── 10. 图像输出检测 → isImage 标记
```

## 3. 权限系统（bashPermissions.ts）

### 3.1 权限决策流水线

权限系统是 BashTool 最复杂的部分。核心函数 `bashToolHasPermission()` 实现了一个多层权限检查流水线：

```
bashToolHasPermission(input, context)
│
├── 0. AST 安全解析（tree-sitter）
│   ├── too-complex → 检查 deny 规则 → ask
│   ├── simple → checkSemantics() 语义检查
│   │   ├── 不通过 → 检查 deny 规则 → ask
│   │   └── 通过 → 获取 astSubcommands
│   └── parse-unavailable → 回退到 legacy 路径
│
├── 1. 沙箱自动允许（如果启用）
│   └── checkSandboxAutoAllow() → 仍尊重 deny/ask 规则
│
├── 2. 精确匹配检查
│   └── bashToolCheckExactMatchPermission()
│       ├── deny → 立即拒绝
│       ├── ask → 立即询问
│       └── allow/passthrough → 继续
│
├── 3. AI 分类器检查（deny/ask 描述）
│   ├── classifyBashCommand('deny') → 高置信度匹配 → deny
│   └── classifyBashCommand('ask')  → 高置信度匹配 → ask
│
├── 4. 操作符权限检查
│   └── checkCommandOperatorPermissions()
│       ├── 子 shell、命令组 → ask
│       └── 管道 → 按段检查
│
├── 5. Legacy 误解析防护（无 AST 时）
│   └── bashCommandIsSafeAsync() 注入检测
│
├── 6. 拆分子命令
│   ├── AST 提取 / splitCommand 分割
│   ├── 过滤 `cd ${cwd}` 前缀
│   └── 限制最大 50 个子命令
│
├── 7. cd + git 组合检查
│   └── 防止裸仓库 fsmonitor 攻击
│
├── 8. 逐子命令权限检查
│   └── bashToolCheckPermission(subcommand)
│       ├── 精确匹配 → deny/ask/allow
│       ├── 前缀/通配符匹配 → deny/ask/allow
│       ├── 路径约束检查
│       ├── sed 约束检查
│       ├── 模式检查（plan mode 等）
│       └── 只读检查 → auto allow
│
├── 9. 命令注入二次检查
│   └── bashCommandIsSafeAsync(subcommand)
│
├── 10. 汇总子命令结果
│   ├── 任一 deny → deny
│   ├── 全部 allow 且无注入 → allow
│   └── 存在 ask/passthrough → 收集建议规则 → ask
│
└── 11. 附加 pendingClassifierCheck（异步分类器自动批准）
```

### 3.2 规则匹配系统

权限规则支持三种类型：

```typescript
type ShellPermissionRule =
  | { type: 'exact'; command: string }    // 精确匹配
  | { type: 'prefix'; prefix: string }    // 前缀匹配（如 "git commit:*"）
  | { type: 'wildcard'; pattern: string } // 通配符匹配（如 "git *"）
```

匹配优先级：**deny > ask > allow**

#### 安全剥离处理

在匹配前，命令会经过安全剥离（`stripSafeWrappers()`）：

1. **环境变量剥离**：安全环境变量（如 NODE_ENV, GOARCH, RUST_LOG 等）从命令前缀中移除
2. **包装命令剥离**：timeout, time, nice, nohup, stdbuf 等命令前缀被剥离
3. **注释行剥离**：`stripCommentLines()` 移除纯注释行

**关键安全约束：**
- allow 规则仅剥离白名单环境变量（`SAFE_ENV_VARS`）
- deny/ask 规则使用激进的环境变量剥离（`stripAllLeadingEnvVars()`），防止 `FOO=bar denied_command` 绕过
- 包装命令的剥离严格匹配正则，防止参数注入
- 前缀/通配符规则不匹配复合命令（防止 `cd /path && python3 evil.py` 匹配 `cd:*`）

#### 安全环境变量白名单

```typescript
const SAFE_ENV_VARS = new Set([
  // Go 构建设置
  'GOEXPERIMENT', 'GOOS', 'GOARCH', 'CGO_ENABLED', 'GO111MODULE',
  // Rust 日志
  'RUST_BACKTRACE', 'RUST_LOG',
  // Node
  'NODE_ENV',
  // Python
  'PYTHONUNBUFFERED', 'PYTHONDONTWRITEBYTECODE',
  // 区域设置
  'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ',
  // 终端/颜色
  'TERM', 'NO_COLOR', 'FORCE_COLOR',
  // ... 更多
])
```

**绝不能添加的变量：** PATH, LD_PRELOAD, LD_LIBRARY_PATH, DYLD_*, PYTHONPATH, NODE_PATH, NODE_OPTIONS, HOME, SHELL, BASH_ENV（这些变量可以执行代码或加载库）

#### 危险前缀拦截

`BARE_SHELL_PREFIXES` 集合阻止生成 `bash:*`、`sudo:*`、`env:*` 等过于宽泛的规则建议：

```typescript
const BARE_SHELL_PREFIXES = new Set([
  'sh', 'bash', 'zsh', 'fish', 'csh', 'tcsh', 'ksh', 'dash',
  'cmd', 'powershell', 'pwsh',
  'env', 'xargs',
  'nice', 'stdbuf', 'nohup', 'timeout', 'time',
  'sudo', 'doas', 'pkexec',
])
```

### 3.3 AI 分类器权限

当用户配置了 Bash prompt 规则（描述性规则，非精确匹配）时，系统使用 AI 分类器来决定命令是否匹配规则描述：

```typescript
// 并行执行 deny 和 ask 分类
const [denyResult, askResult] = await Promise.all([
  classifyBashCommand(command, cwd, denyDescriptions, 'deny', signal, ...),
  classifyBashCommand(command, cwd, askDescriptions, 'ask', signal, ...),
])
```

分类器还支持 **投机性检查**：在权限对话框显示期间，后台并行运行 allow 分类器，如果高置信度通过则自动批准：

```typescript
// 启动投机性检查
startSpeculativeClassifierCheck(command, toolPermissionContext, signal, ...)

// 异步执行分类器检查，可能在用户回应前自动批准
executeAsyncClassifierCheck(pendingCheck, signal, isNonInteractiveSession, {
  shouldContinue: () => boolean,
  onAllow: (decisionReason) => void,
  onComplete: () => void,
})
```

## 4. 安全系统（bashSecurity.ts）

### 4.1 命令注入检测

安全检查系统通过多层验证确保命令安全：

#### 危险模式列表

```typescript
const COMMAND_SUBSTITUTION_PATTERNS = [
  { pattern: /<\(/, message: 'process substitution <()' },
  { pattern: />\(/, message: 'process substitution >()' },
  { pattern: /=\(/, message: 'Zsh process substitution =()' },
  { pattern: /\$\(/, message: '$() command substitution' },
  { pattern: /\$\{/, message: '${} parameter substitution' },
  { pattern: /\$\[/, message: '$[] legacy arithmetic expansion' },
  { pattern: /~\[/, message: 'Zsh-style parameter expansion' },
  // ... 更多
]
```

#### Zsh 危险命令黑名单

```typescript
const ZSH_DANGEROUS_COMMANDS = new Set([
  'zmodload',    // 模块加载（可加载 zsh/mapfile, zsh/system 等危险模块）
  'emulate',     // -c 标志是 eval 等价物
  'sysopen',     // 精细文件操作
  'sysread', 'syswrite', 'sysseek',  // 文件描述符操作
  'zpty',        // 伪终端执行
  'ztcp', 'zsocket',  // 网络连接
  'zf_rm', 'zf_mv', 'zf_ln', 'zf_chmod', ...  // 内建文件操作
])
```

#### 安全检查ID分类

```typescript
const BASH_SECURITY_CHECK_IDS = {
  INCOMPLETE_COMMANDS: 1,
  JQ_SYSTEM_FUNCTION: 2,
  JQ_FILE_ARGUMENTS: 3,
  OBFUSCATED_FLAGS: 4,
  SHELL_METACHARACTERS: 5,
  DANGEROUS_VARIABLES: 6,
  NEWLINES: 7,
  DANGEROUS_PATTERNS_COMMAND_SUBSTITUTION: 8,
  DANGEROUS_PATTERNS_INPUT_REDIRECTION: 9,
  DANGEROUS_PATTERNS_OUTPUT_REDIRECTION: 10,
  IFS_INJECTION: 11,
  GIT_COMMIT_SUBSTITUTION: 12,
  PROC_ENVIRON_ACCESS: 13,
  MALFORMED_TOKEN_INJECTION: 14,
  BACKSLASH_ESCAPED_WHITESPACE: 15,
  BRACE_EXPANSION: 16,
  CONTROL_CHARACTERS: 17,
  UNICODE_WHITESPACE: 18,
  MID_WORD_HASH: 19,
  ZSH_DANGEROUS_COMMANDS: 20,
  BACKSLASH_ESCAPED_OPERATORS: 21,
  COMMENT_QUOTE_DESYNC: 22,
  QUOTED_NEWLINE: 23,
}
```

### 4.2 引号内容提取

安全检查的基础是正确提取引号内容：

```typescript
function extractQuotedContent(command: string, isJq = false): QuoteExtraction {
  // 返回三个版本：
  // withDoubleQuotes: 剥离单引号内容，保留双引号内容
  // fullyUnquoted: 剥离所有引号内容
  // unquotedKeepQuoteChars: 剥离引号内容但保留引号字符本身
}
```

### 4.3 安全重定向剥离

```typescript
function stripSafeRedirections(content: string): string {
  return content
    .replace(/\s+2\s*>&\s*1(?=\s|$)/g, '')     // 2>&1
    .replace(/[012]?\s*>\s*\/dev\/null(?=\s|$)/g, '')  // >/dev/null
    .replace(/\s*<\s*\/dev\/null(?=\s|$)/g, '')  // </dev/null
}
```

**安全边界注意：** 所有模式末尾都有 `(?=\s|$)` 边界检查，防止 `> /dev/nullo` 被错误匹配为 `> /dev/null`。

## 5. 命令执行引擎（Shell.ts + bashProvider.ts）

### 5.1 Shell 选择

```typescript
export async function findSuitableShell(): Promise<string> {
  // 优先级：
  // 1. CLAUDE_CODE_SHELL 环境变量（显式覆盖）
  // 2. SHELL 环境变量（用户偏好，仅 bash/zsh）
  // 3. which 查找的 zsh/bash 路径
  // 4. 标准路径搜索（/bin, /usr/bin, /usr/local/bin, /opt/homebrew/bin）
}
```

**只支持 bash 和 zsh** —— 如果需要添加新 shell，必须更新 Bash 工具的解析逻辑。

### 5.2 命令构建流程（bashProvider）

`buildExecCommand()` 将用户命令包装为可安全执行的完整命令字符串：

```
source <snapshot> 2>/dev/null || true       # 1. 恢复 shell 环境快照
<sessionEnvScript>                           # 2. 加载会话环境变量
shopt -u extglob 2>/dev/null || true        # 3. 禁用扩展 glob（安全）
eval '<quotedCommand>'                       # 4. eval 执行引号化命令
pwd -P >| <cwdFilePath>                      # 5. 保存当前工作目录
```

**关键设计细节：**

- **Shell 快照**：首次运行时创建 shell 环境快照（`createAndSaveSnapshot()`），后续命令 source 快照而非使用 `-l`（login shell），避免每次加载 .bashrc/.zshrc 的开销
- **eval 包装**：使用 `eval` 是因为 source 后别名在同一命令行不展开，eval 触发二次解析使别名可用
- **扩展 glob 禁用**：`shopt -u extglob`（bash）或 `setopt NO_EXTENDED_GLOB`（zsh），防止恶意文件名通过 glob 展开执行代码
- **管道重排**：`rearrangePipeCommand()` 将 stdin 重定向移到管道第一个命令之后，避免 `/dev/null` 被 wc 等命令读取

### 5.3 进程 Spawn

```typescript
const childProcess = spawn(spawnBinary, shellArgs, {
  env: {
    ...subprocessEnv(),
    SHELL: binShell,
    GIT_EDITOR: 'true',     // 阻止 git 打开编辑器
    CLAUDECODE: '1',         // 标识 Claude Code 环境
    ...envOverrides,
  },
  cwd,
  stdio: usePipeMode
    ? ['pipe', 'pipe', 'pipe']           // 管道模式
    : ['pipe', outputHandle?.fd, outputHandle?.fd],  // 文件模式（stdout+stderr 合并）
  detached: provider.detached,  // bash 分离，powershell 不分离
  windowsHide: true,
})
```

**输出处理：**
- 文件模式下 stdout 和 stderr 合并到同一文件描述符（`O_APPEND` 保证原子写入）
- 管道模式下通过 `onStdout` 回调提供实时输出
- Windows 使用 `'w'` 模式（非 O_APPEND）因为 MSYS2 处理 `FILE_APPEND_DATA` 有兼容性问题

### 5.4 CWD 管理

命令执行后通过读取 cwd 文件来追踪工作目录变化：

```typescript
void shellCommand.result.then(async result => {
  if (shouldUseSandbox) SandboxManager.cleanupAfterCommand()

  if (result && !preventCwdChanges && !result.backgroundTaskId) {
    let newCwd = readFileSync(nativeCwdFilePath, 'utf8').trim()
    if (newCwd.normalize('NFC') !== cwd) {
      setCwd(newCwd, cwd)  // 更新全局 cwd 状态
      invalidateSessionEnvCache()
    }
  }
  unlinkSync(nativeCwdFilePath)  // 清理临时文件
})
```

- 使用 `readFileSync`/`unlinkSync`（同步）确保调用者 `await shellCommand.result` 后立即看到更新的 cwd
- NFC 规范化处理 macOS APFS 的 NFD 编码问题
- Agent 模式下（非主线程）`preventCwdChanges = true`

## 6. 沙箱系统

### 6.1 沙箱判断逻辑

```typescript
export function shouldUseSandbox(input): boolean {
  if (!SandboxManager.isSandboxingEnabled()) return false
  if (input.dangerouslyDisableSandbox && SandboxManager.areUnsandboxedCommandsAllowed())
    return false
  if (!input.command) return false
  if (containsExcludedCommand(input.command)) return false
  return true
}
```

排除命令支持三种模式：
- **精确匹配**：`"npm run lint"`
- **前缀模式**：`"npm run test:*"`
- **通配符**：`"docker *"`

### 6.2 沙箱包装

```typescript
if (shouldUseSandbox) {
  commandString = await SandboxManager.wrapWithSandbox(
    commandString, sandboxBinShell, undefined, abortSignal
  )
  await fs.mkdir(sandboxTmpDir, { mode: 0o700 })  // 安全权限
}
```

沙箱提供的限制：
- **文件系统读取**：denyOnly 模式（默认允许，指定路径拒绝）
- **文件系统写入**：allowOnly 模式（默认拒绝，指定路径允许）
- **网络**：可配置的 allowedHosts/deniedHosts
- **Unix sockets**：可配置允许列表

## 7. 只读命令自动放行

### 7.1 判定逻辑

`readOnlyValidation.ts` 定义了大量只读命令的安全标志白名单，包括：

- `cat`, `head`, `tail`, `wc`, `stat`, `file` 等基础命令
- `git diff`, `git status`, `git log` 等 git 只读操作
- `ls`, `find`, `grep`, `rg` 等搜索命令
- `docker ps`, `docker images` 等容器只读操作
- `gh pr view`, `gh issue list` 等 GitHub CLI 只读操作
- `python3 -c`, `node -e` 等脚本执行（受限标志）

每个命令配置了允许的标志白名单：

```typescript
type CommandConfig = {
  safeFlags: Record<string, FlagArgType>  // 'none' | 'number' | 'string'
  regex?: RegExp
  additionalCommandIsDangerousCallback?: (cmd, args) => boolean
  respectsDoubleDash?: boolean  // 是否尊重 -- 结束选项标记
}
```

### 7.2 安全考虑

- `fd`/`fdfind` 排除了 `-x/--exec` 和 `-l/--list-details`（这些会执行子进程）
- git 操作在裸仓库中被阻止（防止 `core.fsmonitor` 攻击）
- compound 命令中含 cd 的需要特殊处理（`compoundCommandHasCd`）

## 8. 退出码语义系统

`commandSemantics.ts` 为常见命令定义了退出码语义，避免误报错误：

| 命令 | 退出码 0 | 退出码 1 | 退出码 2+ |
|------|---------|---------|----------|
| grep/rg | 找到匹配 | 未找到匹配 | 错误 |
| find | 成功 | 部分目录不可访问 | 错误 |
| diff | 无差异 | 有差异 | 错误 |
| test/[ | 条件为真 | 条件为假 | 错误 |

## 9. 后台任务系统

### 9.1 自动后台化

- Assistant 模式下，超过 `ASSISTANT_BLOCKING_BUDGET_MS`（15秒）的阻塞命令自动转为后台
- `sleep` 命令不允许自动后台化
- 用户可通过 `Ctrl+B` 手动后台化

### 9.2 后台任务输出

```typescript
if (backgroundTaskId) {
  const outputPath = getTaskOutputPath(backgroundTaskId)
  // 输出持续写入 outputPath，用户可通过 Read 工具查看
}
```

## 10. 大输出处理

当输出超过 `maxResultSizeChars`（30K 字符）时：

1. 完整输出持久化到 `tool-results` 目录
2. 模型看到的是 `<persisted-output>` 标记 + 预览
3. UI 仍然显示完整输出

```typescript
if (persistedOutputPath) {
  const preview = generatePreview(processedStdout, PREVIEW_SIZE_BYTES)
  processedStdout = buildLargeToolResultMessage({
    filepath: persistedOutputPath,
    originalSize: persistedOutputSize ?? 0,
    preview: preview.preview,
    hasMore: preview.hasMore,
  })
}
```

## 11. Prompt 系统

### 11.1 系统提示词结构

`prompt.ts` 的 `getSimplePrompt()` 生成 Bash 工具的系统提示词，包含：

1. **工具偏好指导**：引导模型使用专用工具（GlobTool, GrepTool, FileReadTool 等）而非 bash 命令
2. **使用规则**：路径引号化、多命令并行/串行选择、避免 cd
3. **超时配置**：默认超时和最大超时说明
4. **Git 操作指南**：提交、PR 创建的完整流程
5. **沙箱说明**：文件系统/网络限制配置、TMPDIR 使用指导
6. **后台任务说明**：`run_in_background` 使用指导
7. **sleep 限制**：引导使用 Monitor 工具替代 sleep 轮询

### 11.2 沙箱提示词

当沙箱启用时，提示词包含沙箱配置的 JSON 描述：

```
## Command sandbox
By default, your command will be run in a sandbox.

Filesystem: {"read":{"denyOnly":[...]},"write":{"allowOnly":[...],"denyWithinAllow":[...]}}
Network: {"allowedHosts":[...]}
```

## 12. 安全设计要点总结

### 12.1 多层防御架构

```
Layer 1: AST 解析 (tree-sitter)
  → 结构化安全检查，识别命令替换、扩展等
Layer 2: 语义检查 (checkSemantics)
  → zsh 危险命令、eval 等语义级危险
Layer 3: 权限规则匹配
  → deny/ask/allow 三级规则系统
Layer 4: AI 分类器
  → 基于描述的智能权限决策
Layer 5: 路径约束
  → 防止越权文件操作
Layer 6: 注入检测 (bashSecurity)
  → 23 种安全检查模式
Layer 7: 只读自动放行
  → 精细的命令+标志白名单
Layer 8: 沙箱隔离
  → 文件系统/网络级隔离
```

### 12.2 关键安全不变量

1. **deny 规则永远优先**：无论其他层如何判断，deny 规则必须生效
2. **复合命令不受前缀规则保护**：`cd /path && rm -rf /` 不匹配 `cd:*` allow 规则
3. **cd + git 组合必须询问**：防止裸仓库 fsmonitor 攻击
4. **环境变量剥离不对称**：allow 规则用安全白名单，deny/ask 规则用激进剥离
5. **子命令数量有上限**：最多 50 个子命令，超过则 ask
6. **_simulatedSedEdit 不暴露给模型**：防止绕过权限写入任意文件
7. **BARE_SHELL_PREFIXES 不生成规则建议**：防止 `bash:*` 等过宽规则
8. **heredoc 命令使用前缀规则**：精确匹配对 heredoc 无效（内容每次不同）
