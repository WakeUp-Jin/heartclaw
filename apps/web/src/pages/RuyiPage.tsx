import { useState, useEffect, useCallback, useRef } from 'react'
import ChatMessageList from '../components/chat/ChatMessageList'
import ChatInput from '../components/chat/ChatInput'
import { useWebSocket, type WsMessage, type ChatTool } from '../hooks/useWebSocket'
import type { ChatMsg } from '../components/chat/ChatMessage'
import type { ToolResult } from '../components/chat/ToolResultItem'

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL as string) || ''

let msgCounter = 0
function nextId() {
  return `msg-${++msgCounter}-${Date.now()}`
}

function formatTime() {
  return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function toolFromWs(data: ChatTool): ToolResult {
  return {
    type: data.tool_type,
    label: data.label,
    items: data.items,
    preview: data.preview,
  }
}

export default function RuyiPage() {
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [loading, setLoading] = useState(false)
  const { subscribe } = useWebSocket()
  const streamingMsgRef = useRef<string | null>(null)

  const handleWsMessage = useCallback((msg: WsMessage) => {
    if (msg.type === 'chat_chunk') {
      const { content, done } = msg.data
      if (done) {
        streamingMsgRef.current = null
        return
      }

      setMessages((prev) => {
        if (streamingMsgRef.current) {
          return prev.map((m) =>
            m.id === streamingMsgRef.current
              ? { ...m, content: m.content + content }
              : m
          )
        }
        const id = nextId()
        streamingMsgRef.current = id
        return [
          ...prev,
          { id, role: 'assistant', content, timestamp: formatTime() },
        ]
      })
    } else if (msg.type === 'chat_tool') {
      const tool = toolFromWs(msg.data)
      setMessages((prev) => {
        if (!streamingMsgRef.current) {
          const id = nextId()
          streamingMsgRef.current = id
          return [
            ...prev,
            { id, role: 'assistant', content: '', timestamp: formatTime(), toolResults: [tool] },
          ]
        }
        return prev.map((m) =>
          m.id === streamingMsgRef.current
            ? { ...m, toolResults: [...(m.toolResults || []), tool] }
            : m
        )
      })
    }
  }, [])

  useEffect(() => {
    return subscribe(handleWsMessage)
  }, [subscribe, handleWsMessage])

  async function handleSend(text: string) {
    const userMsg: ChatMsg = {
      id: nextId(),
      role: 'user',
      content: text,
      timestamp: formatTime(),
    }
    setMessages((prev) => [...prev, userMsg])
    setLoading(true)
    streamingMsgRef.current = null

    try {
      const resp = await fetch(`${apiBaseUrl}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, chat_id: 'web-console', open_id: 'web-console' }),
      })

      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)

      const data = (await resp.json()) as { reply?: string }

      if (!streamingMsgRef.current && data.reply) {
        setMessages((prev) => [
          ...prev,
          { id: nextId(), role: 'assistant', content: data.reply!, timestamp: formatTime() },
        ])
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : '未知错误'
      setMessages((prev) => [
        ...prev,
        {
          id: nextId(),
          role: 'assistant',
          content: `请求失败：${detail}。请确认如意 API 已启动。`,
          timestamp: formatTime(),
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="ruyi-page">
      <div className="ruyi-header">
        <h1>如意</h1>
      </div>
      <ChatMessageList messages={messages} />
      <ChatInput onSend={handleSend} disabled={loading} />
    </div>
  )
}
