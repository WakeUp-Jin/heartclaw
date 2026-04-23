# TOCTOU 防护

## 1. 概述

TOCTOU（Time-Of-Check to Time-Of-Use）指的是"检查时间到使用时间"之间的时间窗口。在 Claude Code 中，当模型先 `Read` 一个文件、经过若干轮推理后再发起 `Edit` 或 `Write` 时，文件可能已被外部进程（如用户的 IDE、linter、git 操作或其他工具）修改。如果此时直接基于过期的快照执行写入，会导致**静默覆盖**——外部修改被无感知地丢失。

本防护机制通过**两道防线**确保模型始终基于最新的文件状态执行修改。

---

## 2. 核心数据结构：readFileState

`readFileState` 是一个会话级的 `FileStateCache`（基于 LRU），记录每次 `Read` 操作后文件的状态快照。

```ts
type FileState = {
  content: string              // 读取时的文件内容（已做 CRLF 归一化）
  timestamp: number           // 读取时的文件修改时间（mtime，Math.floor 后的毫秒值）
  offset: number | undefined  // 读取起始行（仅 Read 工具设置）
  limit: number | undefined   // 读取行数（仅 Read 工具设置）
  isPartialView?: boolean     // 是否为部分视图（如被截断的自动注入内容）
}
```

**路径归一化**：缓存 key 经过 `path.normalize` 处理，保证 `/foo/../bar` 与 `/bar` 命中同一缓存项。

---

## 3. 第一道防线：validateInput

`validateInput` 是定义在工具属性上的钩子方法，由统一的 `toolExecution.ts` 框架在 `call` 之前调用。

### 3.1 调用链

```
toolExecution.ts
  → tool.validateInput?.(parsedInput.data, toolUseContext)
    → 若 result === false：直接返回错误给模型，不执行 call
    → 若 result === true：继续执行 checkPermissions → call
```

### 3.2 检查逻辑（FileEditTool & FileWriteTool 完全一致）

| 步骤 | 检查项 | 逻辑 | 失败时的返回值 |
|------|--------|------|----------------|
| 1 | **是否已读取** | `readFileState.get(fullFilePath)` 是否存在 | `result: false, errorCode: 6(Edit) / 2(Write)` |
| 2 | **是否为部分视图** | `readTimestamp.isPartialView === true` | 同上 |
| 3 | **mtime 是否过期** | `getFileModificationTime(fullPath) > readTimestamp.timestamp` | `result: false, errorCode: 7(Edit) / 3(Write)` |

### 3.3 错误码与返回给模型的消息

#### FileEditTool

| errorCode | 触发条件 | 返回给模型的消息 |
|-----------|----------|------------------|
| 6 | 文件未读取或部分视图 | `File has not been read yet. Read it first before writing to it.` |
| 7 | mtime 过期 | `File has been modified since read, either by the user or by a linter. Read it again before attempting to write it.` |

#### FileWriteTool

| errorCode | 触发条件 | 返回给模型的消息 |
|-----------|----------|------------------|
| 2 | 文件未读取或部分视图 | `File has not been read yet. Read it first before writing to it.` |
| 3 | mtime 过期 | `File has been modified since read, either by the user or by a linter. Read it again before attempting to write it.` |

> **注意**：这些返回值通过 `tool_result` 消息块直接回传给模型。模型收到后会理解为自己需要重新 `Read` 文件，然后再次发起修改。

---

## 4. 第二道防线：call 阶段

`validateInput` 和 `call` 之间存在异步间隙（模型推理、用户交互、其他工具执行），因此 `call` 阶段必须**重新读盘、再次确认**。

### 4.1 检查逻辑

```ts
// 1. 重新读取当前磁盘内容（同步读，保证原子性）
const { content: originalFileContents } = readFileForEdit(absoluteFilePath)

// 2. 再次获取当前 mtime
const lastWriteTime = getFileModificationTime(absoluteFilePath)
const lastRead = readFileState.get(absoluteFilePath)

// 3. mtime 比较
if (!lastRead || lastWriteTime > lastRead.timestamp) {
  // 4. Windows 假阳性处理：完整读取时对比内容
  const isFullRead = lastRead && lastRead.offset === undefined && lastRead.limit === undefined
  const contentUnchanged = isFullRead && originalFileContents === lastRead.content

  if (!contentUnchanged) {
    // 5. 确实被修改了，抛异常硬终止
    throw new Error('File has been unexpectedly modified. Please read the file again.')
  }
}
```

### 4.2 与 validateInput 的差异

| | validateInput | call |
|---|---|---|
| 读取方式 | 异步 `fs.readFileBytes` | 同步 `readFileSyncWithMetadata` |
| 返回方式 | `return { result: false, ... }` | `throw new Error(...)` |
| 内容比对 | 仅 mtime | mtime + 内容双重校验（防 Windows 误报） |
| 是否更新 readFileState | 否 | 是（写入成功后） |

> `call` 阶段的异常同样会封装为 `tool_result` 回传给模型。

---

## 5. 为什么用 `>` 而不是 `==`

```ts
lastWriteTime > readTimestamp.timestamp
```

`>` 表达的是"**当前状态比记录的更新吗？**"这一语义：

- **true** → 文件在 Read 之后被修改过 → 阻断
- **false** → mtime 未变，安全通过

若用 `==`，逻辑将完全颠倒：只在 mtime 完全相等时才阻断，这是错误的。

### mtime 精度处理

`getFileModificationTime` 使用 `Math.floor(fs.statSync(path).mtimeMs)`，抹平亚毫秒级精度抖动，减少 IDE 文件监视器等导致的误报。

---

## 6. 写入后的缓存更新

写入成功后，两个工具都会更新 `readFileState`，使后续修改以此新状态为基准：

```ts
readFileState.set(absoluteFilePath, {
  content: updatedFile,
  timestamp: getFileModificationTime(absoluteFilePath),
  offset: undefined,
  limit: undefined,
})
```

`offset` 和 `limit` 设为 `undefined`，表示这是完整文件视图（非部分读取），可用于后续的完整内容比对。

---

## 7. Read 工具的去重检查

`Read` 工具自身也利用 `readFileState` 做**重复读取去重**：

```ts
const existingState = readFileState.get(fullFilePath)
if (existingState && !existingState.isPartialView && existingState.offset !== undefined) {
  const rangeMatch = existingState.offset === offset && existingState.limit === limit
  if (rangeMatch) {
    const mtimeMs = await getFileModificationTimeAsync(fullFilePath)
    if (mtimeMs === existingState.timestamp) {
      return { type: 'file_unchanged', file: { filePath } }
    }
  }
}
```

若同一文件同一范围在短时间内被再次读取，且 mtime 未变，则直接返回 `file_unchanged`，节省 token 和 I/O。

---

## 8. 完整流程图

```
模型发起 Edit/Write
        │
        ▼
┌─────────────────┐
│  validateInput  │
│  1. readFileState 是否存在？    ──否──→ 返回 errorCode 6/2
│  2. 是否部分视图？              ──是──→ 返回 errorCode 6/2
│  3. mtime > readTimestamp？     ──是──→ 返回 errorCode 7/3
└────────┬────────┘
         │ 全通过
         ▼
┌─────────────────┐
│  checkPermissions│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│      call       │
│  1. 重新读盘    │
│  2. mtime > readTimestamp？     ──是──→ 内容比对
│  3. 内容确实变了？              ──是──→ throw Error
│  4. 执行写入    │
│  5. 更新 readFileState          ──新快照──→
└─────────────────┘
```

---

## 9. 关键设计原则

1. **任何修改前必须有 Read**：`readFileState` 的缺失直接拒绝，杜绝盲写。
2. **mtime 为主，内容比对兜底**：mtime 比较 O(1) 高效；Windows 场景下用内容比对消除假阳性。
3. **双重检查**：`validateInput` 提前拦截，`call` 再次确认，堵住异步间隙。
4. **错误消息直接回传模型**：返回值设计为大模型可理解的行动指令（"Read it again"），引导模型自动修复。
