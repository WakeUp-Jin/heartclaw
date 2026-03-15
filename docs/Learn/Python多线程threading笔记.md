# Python 多线程 threading 笔记

## 线程是什么

同一个程序里同时运行的多条执行路径，各自独立跑，不互相等待。

```python
import threading
import time

def task():
    print("子线程：开始")
    time.sleep(2)
    print("子线程：结束")

t = threading.Thread(target=task)
t.start()
print("主线程：继续执行，不等子线程")
```

输出顺序：
```
主线程：继续执行，不等子线程
子线程：开始
（等2秒）
子线程：结束
```

---

## 关键规律

- 多个线程同时启动 → 总时间 = 最慢那个线程的时间（不是相加）
- 主线程不会自动等子线程 → 需要手动用 `join()` 等待

```python
t1 = threading.Thread(target=task, args=("线程A", 3))
t2 = threading.Thread(target=task, args=("线程B", 1))

t1.start()
t2.start()

t1.join()   # 主线程等 t1 结束
t2.join()   # 主线程等 t2 结束

# 总耗时约 3 秒，不是 4 秒
```

---

## 三个常用工具

### 1. `Thread` — 创建和启动线程

```python
t = threading.Thread(
    target=函数名,        # 线程要执行的函数（传函数本身，不加括号）
    args=(参数1, 参数2),  # 传给函数的参数，元组形式
    name="线程名字",      # 给线程起名，调试时好认
    daemon=True           # 守护线程：主程序退出时自动销毁
)
t.start()        # 启动线程
t.join()         # 主线程等它结束
t.is_alive()     # 判断线程是否还在运行
```

### 2. `Event` — 线程间的信号通知

用于一个线程通知另一个线程"某件事已经发生了"。

```python
event = threading.Event()  # 初始：灭

# 子线程里
event.set()        # 发信号（灯亮）→ 所有在 wait() 的线程立刻唤醒

# 主线程里
event.wait()       # 等信号，一直等到灯亮
event.wait(2.0)    # 等信号，最多等 2 秒，返回 True（收到）或 False（超时）
event.is_set()     # 判断灯现在是亮还是灭
event.clear()      # 清除信号（灯灭）
```

完整示例：

```python
import threading
import time

event = threading.Event()

def worker():
    print("子线程：准备中...")
    time.sleep(2)
    event.set()              # 准备好了，发信号
    print("子线程：继续干活")

t = threading.Thread(target=worker)
t.start()

print("主线程：等待子线程准备好...")
received = event.wait(5.0)  # 最多等 5 秒

if received:
    print("主线程：收到信号，继续执行")
else:
    print("主线程：超时了，没收到信号")
```

### 3. 竞态条件（Race Condition）

多线程最危险的地方：两个线程同时操作同一数据，结果不可预测。

```
线程A：set()
线程B：clear()
主线程：wait()  ← 可能等到，也可能等不到，取决于执行顺序
```

解决办法：在安全的时机操作，确保只有一个线程在跑时才修改共享数据。

---

## 对应 channel.py 中的实际用法

```python
# __init__ 里初始化信号灯
self._ws_started = threading.Event()

# connect() 开头，线程还没启动时清空（安全时机）
self._ws_started.clear()

# ws 线程内部，事件循环准备好后发信号
self._ws_started.set()

# 主线程等待 ws 线程准备好，最多等 2 秒
await asyncio.to_thread(self._ws_started.wait, 2.0)

# disconnect() 结尾，线程已结束后清空（安全时机）
self._ws_started.clear()
```

---

## 小结

| 工具 | 用途 |
|---|---|
| `Thread` | 创建和启动线程 |
| `join()` | 主线程等待子线程结束 |
| `Event` | 线程间信号通知 |
| `daemon=True` | 主程序退出时自动销毁线程 |
| 竞态条件 | 多线程同时操作同一数据时的风险 |
