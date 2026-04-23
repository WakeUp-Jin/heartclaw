# 工具写入时加载 Skill

## 设计意图

在大型项目（如微服务 monorepo）中，不同模块往往有各自的编码规范、接口约定和工具链配置。

如果只在启动时扫描根目录的 skill，子模块的规范就会被遗漏。因此，在**每次文件写入/修改时**，从目标文件所在目录**向上遍历**，动态发现并加载沿途的 skill 目录。

---

## 向上查找几级？

查找范围：**从文件所在目录开始，逐层向上 parent，直到当前工作目录（cwd），但不包括 cwd 本身。**

```
cwd = /project
file  = /project/services/order/src/handler.ts

扫描路径（从深到浅）：
  /project/services/order/src    -> 检查 .claude/skills
  /project/services/order        -> 检查 .claude/skills
  /project/services              -> 检查 .claude/skills
  /project                       -> 停止（cwd 已在启动时加载）
```

也就是说：**cwd 以下的所有层级都扫，cwd 本身不重复扫。**

---

## 为什么对微服务特别有效

微服务常见目录结构：

```
project/
├── .claude/skills/                  <- 根目录：通用规范（启动时加载）
│   └── coding-style.md
├── services/
│   ├── order-service/
│   │   ├── .claude/skills/          <- 订单服务专属规范
│   │   │   └── order-rules.md       <- "订单金额必须用 Decimal"
│   │   └── src/
│   │       └── createOrder.ts       <- 你在这里写入
│   └── pay-service/
│       ├── .claude/skills/          <- 支付服务专属规范
│       │   └── pay-rules.md         <- "支付必须走幂等接口"
│       └── src/
└── shared/
```

当你在 `order-service` 下写代码时，系统会自动加载 `order-rules.md`，模型就知道"订单金额必须用 Decimal"这个约束。

如果没有这个机制，模型只能看到根目录的通用规范，子服务的特殊约定会被忽略。

---

## 简单实现

```typescript
import { dirname, join, sep as pathSep } from 'path'

/**
 * 从文件路径向上扫描 skill 目录
 * @param filePath  目标文件绝对路径
 * @param cwd       当前工作目录（上限，不包含）
 * @returns         新发现的 skill 目录列表（从深到浅排序）
 */
export async function discoverSkillDirsForPaths(
  filePaths: string[],
  cwd: string,
): Promise<string[]> {
  const newDirs: string[] = []
  const resolvedCwd = cwd.endsWith(pathSep) ? cwd.slice(0, -1) : cwd

  for (const filePath of filePaths) {
    let currentDir = dirname(filePath)

    // 向上爬，直到碰到 cwd（不包括 cwd 本身）
    while (currentDir.startsWith(resolvedCwd + pathSep)) {
      const skillDir = join(currentDir, '.claude', 'skills')

      // 用 Set 去重，避免重复 stat
      if (!checkedDirs.has(skillDir)) {
        checkedDirs.add(skillDir)
        try {
          await fs.stat(skillDir)
          // 可选：gitignore 过滤
          if (await isPathGitignored(currentDir, resolvedCwd)) {
            continue
          }
          newDirs.push(skillDir)
        } catch {
          // 目录不存在，跳过
        }
      }

      const parent = dirname(currentDir)
      if (parent === currentDir) break // 已到根目录
      currentDir = parent
    }
  }

  // 深的优先（离文件最近的 skill 优先级更高）
  return newDirs.sort(
    (a, b) => b.split(pathSep).length - a.split(pathSep).length,
  )
}

// 已检查过的目录缓存（模块级，避免重复扫描）
const checkedDirs = new Set<string>()

/**
 * 在工具 call() 中使用
 */
async function call({ file_path }: Input, context: ToolUseContext) {
  const fullFilePath = expandPath(file_path)
  const cwd = getCwd()

  // 1. 发现 skill 目录
  const newSkillDirs = await discoverSkillDirsForPaths([fullFilePath], cwd)

  if (newSkillDirs.length > 0) {
    // 2. 记录到 context（UI 可以展示"发现了 X 个 skill"）
    for (const dir of newSkillDirs) {
      context.dynamicSkillDirTriggers?.add(dir)
    }
    // 3. 加载 skill 文件（fire-and-forget，不阻塞主操作）
    addSkillDirectories(newSkillDirs).catch(() => {})
  }

  // 4. 激活条件式 skill（比如匹配 *.test.ts 就自动激活测试规范）
  activateConditionalSkillsForPaths([fullFilePath], cwd)

  // ... 继续执行写入逻辑
}
```

---

## 关键点

| 要点 | 说明 |
|---|---|
| **查找范围** | 文件所在目录 → 逐级 parent → cwd（不包含 cwd） |
| **去重** | 模块级 `Set` 缓存，同一会话内同一目录只扫一次 |
| **优先级** | 离文件越近的 skill 优先级越高（深的排在前面） |
| **非阻塞** | `addSkillDirectories().catch(() => {})`，加载失败不影响写入 |
| **gitignore 过滤** | 避免加载 `node_modules` 等被忽略目录下的 skill |
| **条件激活** | 支持路径匹配规则（如 `*.test.ts`），命中即自动激活 |

---

## 什么时候不需要

- 小型单模块项目（只有一个根目录 skill）
- 没有 `.claude/skills/` 目录的项目

这两种情况下，这段代码每次调用都会空转（遍历一遍发现没有），但开销极小（只有几次 `stat` 调用），可以保留作为可扩展点。
