# Bash 工具返回字段说明

## 核心字段（必须实现）

| 字段 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `stdout` | string | 操作系统 | 直接捕获命令的标准输出内容。 |
| `stderr` | string | 操作系统 | 直接捕获命令的标准错误输出内容。 |
| `interrupted` | boolean | 执行层 | 命令执行过程中是否收到 SIGINT（如用户按 Ctrl+C）而被中断。 |

---

## 建议字段（推荐实现）

### 1. `returnCodeInterpretation`
- **类型**: string (可选)
- **来源**: **执行层代码判断**
- **实现方式**: 维护一个命令名到退出码语义的映射表/函数。你的代码根据命令和退出码查表，然后把解释字符串塞回返回结果。这是基于命令名的硬编码规则，不是 AI 理解的。

```javascript
function interpretReturnCode(command, returnCode) {
  if (command.startsWith('git diff') && returnCode === 1) {
    return 'EXIT_CODE_1_MEANS_DIFFERENCES_FOUND'; // 有差异，但不是错误
  }
  if (command.startsWith('grep') && returnCode === 1) {
    return 'EXIT_CODE_1_MEANS_NO_MATCH'; // 没找到匹配，但不是错误
  }
  if (command.startsWith('test') && returnCode === 1) {
    return 'EXIT_CODE_1_MEANS_CONDITION_FALSE'; // 条件为假，不是错误
  }
  if (returnCode !== 0) {
    return 'EXIT_CODE_INDICATES_ERROR';
  }
  return null;
}
```

典型规则举例：
- `git diff` 返回 `1` → `EXIT_CODE_1_MEANS_DIFFERENCES_FOUND`（有差异，非错误）
- `grep` 返回 `1` → `EXIT_CODE_1_MEANS_NO_MATCH`（无匹配，非错误）
- `test` 返回 `1` → `EXIT_CODE_1_MEANS_CONDITION_FALSE`（条件为假，非错误）
- 其他非零码 → `EXIT_CODE_INDICATES_ERROR`

- **作用**: 让模型正确理解非零退出码的含义，避免误判为报错。

### 2. `noOutputExpected`
- **类型**: boolean (可选)
- **来源**: **执行层代码判断**
- **实现方式**: 通过命令前缀白名单匹配。你的代码判断这个命令是否属于"静默成功"型命令。

```javascript
const silentCommands = ['mv', 'cp', 'touch', 'rm', 'mkdir', 'chmod', 'chown'];
function shouldExpectNoOutput(command) {
  const cmd = command.trim().split(' ')[0];
  return silentCommands.includes(cmd);
}
```

- **作用**: 告诉模型"空输出是正常的"，避免模型困惑命令是否真正执行成功。如果不告诉模型，它看到 `mv file1 file2` 成功但 `stdout` 是空的，可能会困惑"是不是没执行成功？"。有了这个标记，模型就知道"空输出是正常的"。

### 3. `dangerouslyDisableSandbox`
- **类型**: boolean (可选)
- **来源**: 原样回显模型输入参数
- **作用**: 在返回结果中标记本次执行是否绕过了沙箱，便于审计和日志记录。

---

## 高级扩展字段（按需实现）

### 4. `persistedOutputPath` + `persistedOutputSize`
- **类型**: string / number (可选)
- **来源**: **执行层代码判断**
- **实现方式**: 你的代码在捕获 stdout/stderr 时，先检查总长度是否超过一个阈值。若超过，将完整输出写入临时文件，`stdout` 中只保留前 N 个字符的摘要，并返回临时文件路径和总字节数。触发时机完全由你的代码控制，阈值可以设成 50KB、100KB 或根据上下文窗口动态调整。

```javascript
const MAX_INLINE_OUTPUT = 100 * 1024; // 比如 100KB
let stdout = ...;
let stderr = ...;
const totalSize = Buffer.byteLength(stdout) + Buffer.byteLength(stderr);

if (totalSize > MAX_INLINE_OUTPUT) {
  // 把输出写入临时文件
  const tempPath = `/tmp/claude_bash_output_${taskId}.txt`;
  fs.writeFileSync(tempPath, stdout + stderr);

  return {
    stdout: stdout.slice(0, 500), // 只返回前500字符摘要
    stderr: '',
    persistedOutputPath: tempPath,
    persistedOutputSize: totalSize
  };
}
```

- **作用**: 防止超大输出撑爆模型上下文窗口。

### 5. `rawOutputPath`
- **类型**: string (可选)
- **来源**: **执行层代码判断**
- **实现方式**: 当对接 MCP（Model Context Protocol）协议时，若输出超过 MCP 规定的 inline 上限，不能直接塞进 JSON，必须走文件路径。

```javascript
const MCP_MAX_SIZE = 100 * 1024;

if (totalSize > MCP_MAX_SIZE) {
  const rawPath = `/tmp/claude_mcp_raw_${taskId}.bin`;
  fs.writeFileSync(rawPath, rawOutput);
  return {
    rawOutputPath: rawPath
    // stdout/stderr 可能为空或只有摘要
  };
}
```

- **作用**: 满足 MCP 大输出必须走文件路径的协议要求。
- **与 `persistedOutputPath` 的区别**: `rawOutputPath` 面向 MCP 消费器，格式可能为原始二进制；`persistedOutputPath` 面向 Claude 读取文本摘要。

### 6. `backgroundTaskId`
- **类型**: string (可选)
- **来源**: 任务调度系统
- **作用**: 当 `run_in_background: true` 时返回任务 ID，后续通过 `TaskOutput` / `TaskList` / `TaskStop` 管理。【暂不实现，依赖底层任务模块支持】

### 7. `isImage`
- **类型**: boolean (可选)
- **来源**: 执行层对 stdout 内容做 MIME 类型或魔数检测
- **作用**: 标记 stdout 是否包含图片二进制数据，客户端可据此做特殊渲染。

### 8. `backgroundedByUser` / `assistantAutoBackgrounded`
- **类型**: boolean (可选)
- **来源**: 交互层状态记录
- **作用**: 区分任务后台化是由用户手动触发（如 Ctrl+B）还是 Assistant 模式下超时自动触发。

---

## 字段来源总结

| 字段 | 值从哪来 | 判断主体 |
|------|---------|---------|
| `stdout` / `stderr` | 直接捕获命令输出 | 操作系统 |
| `interrupted` | 捕获 SIGINT 信号 | 执行层 |
| `returnCodeInterpretation` | 查规则表/函数 | **你的代码** |
| `noOutputExpected` | 匹配命令白名单 | **你的代码** |
| `persistedOutputPath` / `persistedOutputSize` | 超阈值后写临时文件 | **你的代码** |
| `rawOutputPath` | MCP 协议超限时写文件 | **你的代码** |
| `dangerouslyDisableSandbox` | 原样回显输入参数 | 输入参数 |

> **核心原则**: 模型只负责"读懂"这些字段，但所有字段的填充逻辑都由执行层代码负责生成。
