import { FormEvent, useState } from 'react'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

type ChatState = {
  status: 'idle' | 'loading' | 'success' | 'error'
  reply: string
}

const serviceCards = [
  {
    label: '如意 API',
    title: '对话与工具编排入口',
    body: 'FastAPI 承载飞书、HTTP Chat、上下文、记忆、工具调度和 KAIROS 队列。',
  },
  {
    label: '天工 Worker',
    title: '独立锻造执行器',
    body: '轮询共享目录里的锻造令，调度 Codex、Kimi 或 OpenCode 完成工具锻造。',
  },
  {
    label: '文件通信',
    title: '简单直接的异步协议',
    body: '如意写入 pending，天工移动到 processing 和 done，不引入额外消息队列。',
  },
]

const flowSteps = [
  '~/.heartclaw/tiangong/orders/pending/',
  '~/.heartclaw/tiangong/orders/processing/',
  '~/.heartclaw/tiangong/orders/done/',
]

function App() {
  const [message, setMessage] = useState('你好，介绍一下 HeartClaw 现在的服务结构')
  const [chat, setChat] = useState<ChatState>({ status: 'idle', reply: '' })

  async function submitChat(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const text = message.trim()
    if (!text) {
      return
    }

    setChat({ status: 'loading', reply: '' })
    try {
      const response = await fetch(`${apiBaseUrl}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          chat_id: 'web-console',
          open_id: 'web-console',
        }),
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const data = (await response.json()) as { reply?: string }
      setChat({ status: 'success', reply: data.reply || '后端没有返回 reply 字段。' })
    } catch (error) {
      const detail = error instanceof Error ? error.message : '未知错误'
      setChat({
        status: 'error',
        reply: `请求失败：${detail}。请确认如意 API 已在 ${apiBaseUrl} 启动。`,
      })
    }
  }

  return (
    <main className="shell">
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">HeartClaw Monorepo Console</p>
          <h1>如意负责对话，天工负责锻造，Web 负责看得见。</h1>
          <p className="hero-text">
            这是第一阶段的轻量控制台首页：说明服务边界、展示文件通信流程，并预留一个
            API Chat 调试入口。
          </p>
          <div className="hero-actions">
            <a href={`${apiBaseUrl}/health`} target="_blank" rel="noreferrer">
              检查 API 健康状态
            </a>
            <span>API Base: {apiBaseUrl}</span>
          </div>
        </div>
        <div className="signal-card" aria-label="service topology">
          <span>ruyi-api</span>
          <strong>orders/*.md</strong>
          <span>tiangong-worker</span>
        </div>
      </section>

      <section className="cards" aria-label="service cards">
        {serviceCards.map((card) => (
          <article className="card" key={card.label}>
            <span>{card.label}</span>
            <h2>{card.title}</h2>
            <p>{card.body}</p>
          </article>
        ))}
      </section>

      <section className="workspace">
        <div className="panel">
          <p className="eyebrow">Forge Order Flow</p>
          <h2>锻造令仍然通过文件流转</h2>
          <div className="flow">
            {flowSteps.map((step, index) => (
              <div className="flow-step" key={step}>
                <span>{String(index + 1).padStart(2, '0')}</span>
                <code>{step}</code>
              </div>
            ))}
          </div>
        </div>

        <form className="panel chat-panel" onSubmit={submitChat}>
          <p className="eyebrow">API Chat Debug</p>
          <h2>从 Web 调用如意</h2>
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            rows={5}
            aria-label="chat message"
          />
          <button type="submit" disabled={chat.status === 'loading'}>
            {chat.status === 'loading' ? '发送中...' : '发送到 /api/chat'}
          </button>
          {chat.reply && (
            <output className={`reply reply-${chat.status}`}>
              {chat.reply}
            </output>
          )}
        </form>
      </section>
    </main>
  )
}

export default App
