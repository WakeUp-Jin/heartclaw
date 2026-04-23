# Bash 工具的开发

> 本文档整理自 Claude Code 源码中 `tools/BashTool/prompt.ts` 与 `BashTool.tsx` 的提示词与参数设计。

---

## 1. 工具概述

**BashTool** 用于执行给定的 bash 命令并返回其输出。

**核心约束**：
- 工作目录（Working Directory）在会话之间是**持久化**的；
- 但 shell 状态（环境变量、alias、函数定义等）**不会持久化**；
- 每次执行的子进程环境都初始化自用户的 profile（bash 或 zsh）。

---

## 2. 输入参数（Input Schema）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `command` | `string` | 是 | 要执行的 shell 命令 |
| `description` | `string` | 否 | 对命令行为的清晰、简洁描述，使用主动语态 |
| `timeout` | `number` | 否 | 超时时间（毫秒），默认 30 分钟，最大可配置 |
| `run_in_background` | `boolean` | 否 | 设为 `true` 则在后台运行命令，稍后通过通知获取结果 |
| `dangerouslyDisableSandbox` | `boolean` | 否 | **危险参数**：设为 `true` 可无沙箱执行（需用户批准） |

> 注：`description` 的撰写要求见下文第 4 节。

### 内部隐藏字段

| 字段 | 说明 |
|------|------|
| `_simulatedSedEdit` | 内部专用，用于 sed 编辑预览后直接写入文件。**永远不会暴露给模型**，以防绕过权限与沙箱检查。 |

---

## 3. 输出参数（Output Schema）

| 字段 | 类型 | 说明 |
|------|------|------|
| `stdout` | `string` | 标准输出内容 |
| `stderr` | `string` | 标准错误输出内容 |
| `interrupted` | `boolean` | 命令是否被中断 |
| `isImage` | `boolean?` | stdout 是否包含图片数据 |
| `backgroundTaskId` | `string?` | 后台任务 ID |
| `backgroundedByUser` | `boolean?` | 用户是否手动按 Ctrl+B 后台化 |
| `assistantAutoBackgrounded` | `boolean?` | Assistant 模式是否因超时而自动后台化 |
| `dangerouslyDisableSandbox` | `boolean?` | 标记本次执行是否绕过了沙箱 |
| `returnCodeInterpretation` | `string?` | 对非零退出码的语义解释（如 `git diff` 返回 1 不是错误） |
| `noOutputExpected` | `boolean?` | 该命令成功时是否本来就应该没有输出 |
| `structuredContent` | `any[]?` | 结构化内容块 |
| `persistedOutputPath` | `string?` | 输出过大时的磁盘持久化路径 |
| `persistedOutputSize` | `number?` | 持久化输出的总字节数 |
| `rawOutputPath` | `string?` | MCP 大输出用的原始文件路径 |

---

## 4. `description` 撰写规范

描述必须**清晰、简洁、主动语态**。禁止出现 "complex" 或 "risk" 等词汇。

### 简单命令（5-10 个词）

| 命令 | 描述示例 |
|------|----------|
| `ls` | "List files in current directory" |
| `git status` | "Show working tree status" |
| `npm install` | "Install package dependencies" |

### 复杂命令（需额外上下文）

| 命令 | 描述示例 |
|------|----------|
| `find . -name "*.tmp" -exec rm {} \;` | "Find and delete all .tmp files recursively" |
| `git reset --hard origin/main` | "Discard all local changes and match remote main" |
| `curl -s url \| jq '.data[]'` | "Fetch JSON from URL and extract data array elements" |

---

## 5. 核心使用原则（Tool Preference）

模型被明确引导：虽然 Bash 工具也能做类似的事，但**优先使用专用工具**，因为这能提供更好的用户体验并方便审查。

| 场景 | 推荐工具 | 禁止/不建议的 bash 命令 |
|------|----------|------------------------|
| 搜索文件 | `Glob` | `find`、`ls` |
| 搜索内容 | `Grep` | `grep`、`rg` |
| 读取文件 | `Read`（`FileReadTool`） | `cat`、`head`、`tail` |
| 编辑文件 | `Edit`（`FileEditTool`） | `sed`、`awk` |
| 写入文件 | `Write`（`FileWriteTool`） | `echo >`、`cat <<EOF` |
| 通信/输出文本 | 直接输出文本 | `echo`、`printf` |

> 例外：当用户明确要求，或已确认专用工具无法完成时，才允许使用 bash。

---

## 6. 多条命令的执行策略

当需要执行多个命令时，遵循以下策略：

1. **能并行的独立命令**  
   在一个 message 中发起**多个** `Bash` tool call。  
   例：`git status` 和 `git diff` 可以同时发。

2. **必须顺序执行的依赖命令**  
   使用单个 `Bash` call，并用 `&&` 连接。  
   例：`npm install && npm run build`

3. **顺序执行但不在意前面是否失败**  
   使用 `;` 连接。  
   例：`cmd1 ; cmd2`

4. **禁止用换行分隔命令**  
   换行只允许出现在引号字符串内部。

---

## 7. 后台运行（`run_in_background`）

- 仅在不急需结果时使用；
- 设置后无需在命令末尾加 `&`；
- 命令完成时会收到通知；
- 如果启用了 `Monitor Tool`，可用 `Monitor` 工具流式监听后台进程输出。

---

## 8. Sleep 与轮询

- **不要**在可立即执行的命令之间加 `sleep`；
- 长等待任务应使用 `run_in_background`；
- **不要**在失败循环里用 `sleep` 重试命令，应诊断根本原因；
- 若必须轮询外部进程，优先使用检查命令（如 `gh run view`）而非先 `sleep`；
- 若必须 `sleep`，保持时长很短（1-5 秒）；
- 当 `MONITOR_TOOL` 开启时，首命令为 `sleep N`（N ≥ 2）会被输入校验拦截。

---

## 9. Git 操作指南

### 9.1 通用原则

- 优先创建**新 commit**，而不是 amend 现有 commit；
- 执行破坏性操作（如 `git reset --hard`、`push --force`、`git checkout --`）前，先考虑是否有更安全的替代方案；
- **永远不要**跳过 hooks（`--no-verify`）或绕过签名（`--no-gpg-sign`、`-c commit.gpgsign=false`），除非用户明确要求；
- 如果 hook 失败，调查并修复根本原因。

### 9.2 提交 Commit 的标准流程

1. **并行获取信息**：
   - `git status`（查看未跟踪文件，**不要使用 `-uall`**）
   - `git diff`（查看 staged/unstaged 变更）
   - `git log`（了解最近的 commit message 风格）

2. **分析并撰写 commit message**：
   - 准确反映变更性质（"add" = 新功能，"update" = 增强，"fix" = bug 修复等）；
   - 不要提交明显包含 secret 的文件；
   - 用 1-2 句话聚焦 "why" 而非 "what"。

3. **并行执行**：
   - `git add <specific-files>`（优先按文件名添加，不要用 `-A` 或 `.`）；
   - `git commit`（使用 heredoc 传 message，保证格式正确）；
   - `git status`（在 commit 完成后顺序执行，验证成功）。

4. **如果 pre-commit hook 失败**：修复问题后创建**新的 commit**，不要 `--amend`。

#### Commit message 的 heredoc 示例

```bash
git commit -m "$(cat <<'EOF'
   Commit message here.

   Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
   EOF
   )"
```

### 9.3 创建 Pull Request 的流程

1. **并行了解分支状态**：
   - `git status`
   - `git diff`
   - 检查当前分支是否跟踪远程分支
   - `git log` 与 `git diff [base-branch]...HEAD` 了解完整 commit 历史

2. **分析并起草 PR**：
   - 标题控制在 70 字符以内；
   - 详情放在 description/body 中。

3. **并行执行**：
   - 如有需要，创建新分支；
   - 如有需要，用 `-u` flag push 到远程；
   - 使用 `gh pr create` 创建 PR，body 用 heredoc 传入。

#### `gh pr create` 示例

```bash
gh pr create --title "the pr title" --body "$(cat <<'EOF'
## Summary
<1-3 bullet points>

## Test plan
[Bulleted markdown checklist of TODOs for testing the pull request...]

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## 10. 沙箱说明（Sandbox）

默认情况下，命令会在沙箱中执行。沙箱控制命令可以访问/修改的目录和网络主机。

### 10.1 文件系统

- **读取**：有 `denyOnly` 列表，可能包含 `allowWithinDeny` 例外；
- **写入**：有 `allowOnly` 白名单，及 `denyWithinAllow` 子限制；
- 临时文件必须使用 `$TMPDIR` 环境变量，**不要直接写 `/tmp`**。

### 10.2 网络

- 可能有 `allowedHosts` 白名单与 `deniedHosts` 黑名单；
- 可能允许/禁止 Unix socket 连接。

### 10.3 绕过沙箱（`dangerouslyDisableSandbox`）

仅当以下情况时才考虑设置：

1. 用户**明确要求**绕过沙箱；
2. 某个命令刚刚失败，且有明确证据表明是沙箱限制导致的（如 "Operation not permitted"、访问拒绝、非白名单主机网络连接失败、Unix socket 错误等）。

如果确认是沙箱导致的问题：
- **立即**用 `dangerouslyDisableSandbox: true` 重试（无需再次询问用户）；
- 简要解释是哪个沙箱限制导致了失败；
- 提醒用户可用 `/sandbox` 命令管理限制。

> 注意：即使刚刚绕过过一次沙箱，后续命令仍应默认在沙箱内运行。

---

## 11. 其他常见操作

- **查看 PR 评论**：`gh api repos/foo/bar/pulls/123/comments`

---

## 12. 安全检查架构

> 本节基于 `bashToolHasPermission` 的实际源码调用链整理，描述 Bash 工具从接收到命令到最终执行的完整安全防线。

Bash 工具的安全设计采用**多层防御纵深（Defense in Depth）**策略：没有任何单层检查是绝对可靠的，因此通过多道独立的闸门叠加，即使某一层被绕过，后续层级仍可进行拦截。

整个安全检查流程可分为 **10 个大节点**，每个大节点下包含若干按执行顺序排列的小节点。

---

### 12.1 节点 1：解析与语义检查层

**目标**：先把命令"读懂"，识别出无法静态分析的结构和已知危险语义。

#### 12.1.1 AST 解析
- `parseCommandRaw(input.command)` 调用 tree-sitter 解析命令
- 产出 `astRoot`（抽象语法树根节点）

#### 12.1.2 安全结果分流
- `parseForSecurityFromAst()` 判定三种结果：
  - `too-complex`：含 `$()`、控制流、解析器差异等复杂结构
  - `simple`：干净的 `SimpleCommand[]`
  - `parse-unavailable`：tree-sitter 未加载或不可用

#### 12.1.3 Too-Complex 路径
- 先执行 `checkEarlyExitDeny`（exact + prefix deny 规则）
- 无 deny 规则匹配 → 直接返回 **ask**

#### 12.1.4 Simple 路径的语义检查
- `checkSemantics(astResult.commands)` 检查以下内容：
  - `eval`、`.` / `source`、`exec` 等动态执行
  - zsh 危险命令（`zmodload`、`emulate` 等）
  - 危险重定向（如 `/proc` 访问）
- 语义不通过 → 先执行 `checkSemanticsDeny`（不降级为 ask）
- 无 deny 规则匹配 → 返回 **ask**

#### 12.1.5 Legacy 预检查（AST 不可用时）
- `tryParseShellCommand()` 使用 `shell-quote` 做语法预检
- 解析失败 → 返回 **ask**

---

### 12.2 节点 2：快速通道层（Fast-Path Auto-Allow）

**目标**：在已启用沙箱的场景下，对无显式拒绝规则的命令快速放行。

#### 12.2.1 条件判断
- 沙箱启用（`SandboxManager.isSandboxingEnabled()`）
- 自动允许开启（`isAutoAllowBashIfSandboxedEnabled`）
- 当前命令应使用沙箱（`shouldUseSandbox(input)`）

#### 12.2.2 显式规则检查
- 检查 exact / prefix deny 规则
- 检查 exact / prefix ask 规则
- 对复合命令拆分后逐子命令检查 deny/ask

#### 12.2.3 结果
- 有显式 deny → **deny**
- 有显式 ask → **ask**
- 无任何显式规则 → **allow**（依赖沙箱隔离作为安全保障）

---

### 12.3 节点 3：精确规则匹配层

**目标**：用户设置的精确匹配规则拥有最高优先级。

- **Exact Deny**：`bashToolCheckExactMatchPermission()` 先查 exact deny，命中 → **deny**
- **Exact Ask**：再查 exact ask，命中 → **ask**
- **Exact Allow**：再查 exact allow，命中 → 记录 allow，继续后续检查

---

### 12.4 节点 4：AI Prompt 分类层

**目标**：基于用户 Prompt 中的自然语言描述（Haiku 分类器），对命令做语义分类。

#### 12.4.1 条件判断
- 分类器功能开启
- 非 `auto` 模式
- 用户 Prompt 中存在 deny/ask 描述

#### 12.4.2 并行分类
- `classifyBashCommand(..., 'deny')`
- `classifyBashCommand(..., 'ask')`

#### 12.4.3 结果判定
- **deny** 高置信度匹配 → **deny**
- **ask** 高置信度匹配 → **ask**
- **allow** 高置信度 → 不直接放行，继续后续检查（Allow 分类器在节点 9 生效）

---

### 12.5 节点 5：结构操作符检查层

**目标**：处理管道 `|`、重定向 `>`、`>>`、复合结构 `()` `{}` 等，防止分段绕过。

#### 12.5.1 Unsafe Compound 检查
- `ParsedCommand.getTreeSitterAnalysis()` 检测 subshell `()` 和 command group `{}`
- 存在 → **ask**

#### 12.5.2 管道分段检查
- `parsed.getPipeSegments()` 拆分管道
- 每段剥离输出重定向后，**递归调用 `bashToolHasPermission`**
- 任一段 deny → 整体 **deny**
- 任一段 ask → 整体 **ask**

#### 12.5.3 跨段 cd+git 检查
- 检测不同管道段中分别存在 `cd` 和 `git`
- 命中 → **ask**（防止 bare repo `core.fsmonitor` RCE 攻击）

#### 12.5.4 Allow 后的补查（原始命令）
- 若管道整体被判定 allow，回头对**原始未拆分命令**补做：
  - `bashCommandIsSafeAsync`（检查重定向目标中是否有反引号等危险模式）
  - `checkPathConstraints`（检查被剥离的输出重定向路径）

---

### 12.6 节点 6：Legacy 误解析防护层

**目标**：tree-sitter 不可用时，用正则安全网拦截已知的命令注入和 splitCommand 误解析。

#### 12.6.1 触发条件
- `astSubcommands === null`（无 AST）
- `CLAUDE_CODE_DISABLE_COMMAND_INJECTION_CHECK` 未开启

#### 12.6.2 原始命令安全检查
- `bashCommandIsSafeAsync(input.command)` 跑 20+ 正则校验器

#### 12.6.3 Safe Heredoc 例外
- 若是 `$(cat <<'EOF'...EOF)` 安全 heredoc 触发的 misparsing
- 剥掉 safe heredoc 后重检

#### 12.6.4 结果
- 仍存在误解析/注入风险 → 先查 exact allow 规则，无则返回 **ask**

---

### 12.7 节点 7：子命令拆分与复合命令预检层

**目标**：把复合命令拆成原子子命令，并在逐条检查前拦截已知的组合风险。

#### 12.7.1 子命令拆分
- 优先使用 AST 提取的 `astSubcommands`
- fallback 到 `splitCommand_DEPRECATED(input.command)`
- 过滤掉 `cd ${cwd}` 这种模型常见前缀

#### 12.7.2 子命令数量上限
- `MAX_SUBCOMMANDS_FOR_SECURITY_CHECK = 50`
- 超过 → **ask**（防止 ReDoS / CPU 饥饿）

#### 12.7.3 多 cd 检查
- 子命令中出现多次 `cd` → **ask**

#### 12.7.4 cd+git 复合检查
- 复合命令中同时存在 `cd` 和 `git` → **ask**

---

### 12.8 节点 8：逐子命令细查层

**目标**：对每个原子子命令做完整的权限判定。

对每个子命令调用 `bashToolCheckPermission()`，内部检查顺序如下：

1. **Exact Match**（再次确认精确规则）
2. **Prefix / Wildcard Deny Rules**：命中 → **deny**
3. **Prefix / Wildcard Ask Rules**：命中 → **ask**
4. **路径约束检查**（`checkPathConstraints`）：
   - 提取命令参数中的路径
   - 检查绝对路径是否越界
   - 检查 `cd` 后的相对路径绕过
   - 检查危险删除路径（`rm -rf /` 等）
   - 检查 `.claude/` 等敏感目录写入
5. **Sed 约束检查**（`checkSedConstraints`）：拦截未在白名单中的危险 sed 操作
6. **模式校验**（`checkPermissionMode`）：根据当前权限模式做模式级判定
7. **只读判定**（`checkReadOnlyConstraints`）：若子命令是只读操作 → **allow**

---

### 12.9 节点 9：原始命令补查与结果汇总层

**目标**：补查被拆分过程剥掉的重定向，汇总所有子命令结果。

#### 12.9.1 原始命令重定向补查
- 对**原始完整命令**调用 `checkPathConstraints`
- 专门检查 `splitCommand` 剥掉的 `>`、`>>` 等输出重定向目标
- 若越界 → **ask** / **deny**

#### 12.9.2 子命令结果聚合
- 任一子命令 deny → 整体 **deny**
- 单一子命令 ask，其余 allow → 返回该 ask（short-circuit）
- 多个子命令 ask/passthrough → 合并所有 suggestions，统一 **ask**

#### 12.9.3 最终 Allow 判定
- 所有子命令 allow + 无 legacy 注入风险 → **allow**

#### 12.9.4 Pending Classifier 附加
- 若最终需要 ask，附加 `pendingClassifierCheck`
- 后台运行 allow 分类器，高置信度时可**自动批准**（无需用户点击）

---

### 12.10 节点 10：执行隔离层

**目标**：命令最终执行时的操作系统级隔离。

#### 12.10.1 沙箱判定
- `shouldUseSandbox(input)` 决定是否启用沙箱
- 用户可传 `dangerouslyDisableSandbox: true` 绕过（需用户批准）

#### 12.10.2 沙箱封装
- `SandboxManager.wrapWithSandbox(commandString, shell)`
- 通常使用 **bubblewrap (bwrap)** 做命名空间隔离

#### 12.10.3 文件系统隔离
- 只暴露白名单目录
- 临时目录映射到隔离的 `$TMPDIR`

#### 12.10.4 网络隔离
- 可选限制只能访问特定 host
- 可选禁止 Unix socket

#### 12.10.5 子进程创建
- `spawn()` 创建子进程
- stdout/stderr 重定向到文件 fd 或 pipe
- `tree-kill` 实现进程树终止

---

### 12.11 简化流程图

```
[1] AST解析与语义检查
    ├── too-complex → early deny → ask
    └── simple → checkSemantics → deny/ask

[2] 沙箱快速通道
    └── 无显式规则 + 启用沙箱 → allow

[3] 精确规则匹配
    └── exact deny / ask / allow

[4] AI Prompt分类器
    └── deny高置信 / ask高置信

[5] 结构操作符检查（管道|、()、{}）
    └── 分段检查 + cd+git跨段 + allow后补查

[6] Legacy注入防护
    └── regex安全网（仅AST不可用时）

[7] 子命令拆分 + 复合命令预检
    └── 上限50 + 多cd + cd+git

[8] 逐子命令细查
    └── exact → prefix deny/ask → 路径约束 → sed → 模式 → 只读

[9] 原始命令补查 + 结果汇总
    └── 重定向补查 + 聚合 + pendingClassifier自动批准

[10] 执行隔离
    └── SandboxManager / bwrap
```
