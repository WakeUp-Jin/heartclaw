# Python 异步编程 asyncio 笔记

## 为什么需要异步

普通的顺序执行，等待时什么都做不了：

```python
import time

def 烧水():
    time.sleep(5)   # 卡住5秒，什么都做不了

def 切菜():
    time.sleep(3)

烧水()   # 等5秒
切菜()   # 再等3秒，总共8秒
```

异步的核心思想：

> **等待的时候不要傻等，把控制权交出去，让别的任务先跑。**

---

## 基础语法

```python
import asyncio

async def 烧水():           # async def 定义异步函数（协程）
    await asyncio.sleep(5)  # await 等待，期间交出控制权

asyncio.run(main())         # 启动事件循环，运行入口函数
```

| 语法 | 含义 |
|---|---|
| `async def` | 定义异步函数（协程函数） |
| `await` | 等待并交出控制权 |
| `asyncio.run()` | 启动事件循环 |

---

## await 的两层含义

**含义1：等这个函数执行完，再执行下一行**

```python
await 烧水()    # 烧水没结束，下面的代码不会执行
await 切菜()    # 烧水结束后才开始切菜
```

**含义2：遇到真正的等待操作时，交出控制权**

```python
await asyncio.sleep(5)  # 登记定时器，暂停当前协程，交出控制权
await 网络请求()         # 发出请求，暂停当前协程，交出控制权
await 读文件()           # 发起IO，暂停当前协程，交出控制权
```

**关键区别：**

```python
await 烧水()
# 只是"进入烧水函数等它跑完"
# 控制权由烧水()内部的 await 决定要不要交出去

await asyncio.sleep(5)
# 这才是真正触发"交出控制权"的动作
```

> `await 函数()` = 进入函数等它跑完，控制权由函数内部的 `await` 决定何时交出。

---

## 事件循环是什么

事件循环本质是一个不停转的循环：

```python
# 伪代码
while True:
    到期的定时器 = 检查哪些定时器到时间了()
    for 任务 in 到期的定时器:
        唤醒任务，继续执行

    就绪的任务 = 检查哪些IO完成了()
    for 任务 in 就绪的任务:
        唤醒任务，继续执行
```

`await asyncio.sleep(5)` 的实际过程：

```
1. 向事件循环登记："5秒后叫醒我"
2. 当前协程暂停，把控制权还给事件循环
3. 事件循环去跑别的任务
4. 5秒到了，事件循环唤醒协程
5. 从 await 那行继续执行
```

**计时不是线程在傻等，是事件循环管理定时器。**

---

## time.sleep vs asyncio.sleep

```python
import time
time.sleep(5)
# 真的把线程卡住5秒，期间事件循环无法运行，其他任务全部阻塞

import asyncio
await asyncio.sleep(5)
# 只暂停当前协程，事件循环继续跑，其他任务正常执行
```

---

## 顺序执行 vs 并发执行

**顺序执行：总时间 = 相加**

```python
async def main():
    await A()   # 等A跑完（5秒）
    await B()   # 再等B跑完（3秒）
    # 总共 8 秒
```

**并发执行：总时间 = 最慢的那个**

```python
async def main():
    await asyncio.gather(A(), B())
    # A和B同时跑，总共 5 秒
```

---

## asyncio.gather()

同时启动多个协程，等全部完成：

```python
result_a, result_b = await asyncio.gather(A(), B())
```

**重要特性：返回结果顺序和传入顺序一致，不管谁先完成。**

```python
async def A():
    await asyncio.sleep(5)   # 慢，5秒
    return "A 的结果"

async def B():
    await asyncio.sleep(1)   # 快，1秒
    return "B 的结果"

async def main():
    result_a, result_b = await asyncio.gather(A(), B())
    print(result_a)   # "A 的结果"（虽然A慢，但A先输出）
    print(result_b)   # "B 的结果"
    # 总耗时：5秒
```

---

## 和 Node.js 的对比

Python asyncio 和 Node.js async/await 核心机制相同：

| | Node.js | Python asyncio |
|---|---|---|
| 异步函数 | `async function` | `async def` |
| 等待 | `await` | `await` |
| 并发 | `Promise.all([...])` | `asyncio.gather(...)` |
| 事件循环 | 内置自动启动 | 需要 `asyncio.run()` |
| 宏任务/微任务 | 有，影响执行优先级 | 无此概念 |

---

## 对应 channel.py 中的实际用法

```python
# connect() 是异步函数，必须用 await 调用
async def connect(self) -> None:

# 把阻塞函数放到线程里跑，不阻塞事件循环
await asyncio.to_thread(self._ws_started.wait, 2.0)

# 把另一个线程的任务安全地提交到当前事件循环
asyncio.run_coroutine_threadsafe(
    self._process_message(parsed),
    self._event_loop
)
```

---

## 小结

| 概念 | 说明 |
|---|---|
| `async def` | 定义协程函数 |
| `await` | 等待完成，遇到IO时交出控制权 |
| 事件循环 | 调度所有协程的"大管家" |
| `asyncio.sleep()` | 真正触发交出控制权的操作 |
| `asyncio.gather()` | 并发运行多个协程，结果按传入顺序返回 |
| `asyncio.run()` | 启动事件循环的入口 |
