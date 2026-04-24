import { useEffect, useRef, useState, useCallback, createContext, useContext } from 'react'

export type WsStatus = 'connecting' | 'connected' | 'disconnected'

export type ChatChunk = {
  chat_id: string
  content: string
  done: boolean
}

export type ChatTool = {
  tool_name: string
  tool_type: 'read' | 'write' | 'command'
  label: string
  items?: string[]
  preview?: string[]
}

export type LogEntry = {
  timestamp: string
  level: 'INFO' | 'WARN' | 'ERROR'
  source?: string
  message: string
}

export type StatusUpdate = {
  ruyi: string
  tiangong: string
}

export type ToolStatus = {
  source: 'ruyi' | 'kairos'
  call_id: string
  tool_name: string
  status: 'executing' | 'success' | 'error' | 'cancelled'
  args_summary: string
  content?: string
  result_preview?: string
  error?: string
  duration_ms?: number
}

export type KairosEvent = {
  event: string
  timestamp: string
  detail: Record<string, unknown>
}

export type KairosReply = {
  text: string
  timestamp: string
}

export type ContainerLog = {
  source: 'tiangong' | 'ruyi'
  timestamp: string
  level: string
  message: string
}

export type WsMessage =
  | { type: 'chat_chunk'; data: ChatChunk }
  | { type: 'chat_tool'; data: ChatTool }
  | { type: 'tool_status'; data: ToolStatus }
  | { type: 'kairos_event'; data: KairosEvent }
  | { type: 'kairos_reply'; data: KairosReply }
  | { type: 'log'; data: LogEntry }
  | { type: 'container_log'; data: ContainerLog }
  | { type: 'status'; data: StatusUpdate }

type Subscriber = (msg: WsMessage) => void

type WsContextValue = {
  status: WsStatus
  ruyiStatus: string
  tiangongStatus: string
  subscribe: (fn: Subscriber) => () => void
  send: (msg: unknown) => void
}

const WsContext = createContext<WsContextValue>({
  status: 'disconnected',
  ruyiStatus: 'idle',
  tiangongStatus: '空间',
  subscribe: () => () => {},
  send: () => {},
})

function getWsUrl(): string {
  const apiBase = import.meta.env.VITE_API_BASE_URL as string
  if (apiBase) {
    return apiBase.replace(/^http/, 'ws') + '/ws'
  }
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/ws`
}

export function WebSocketProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<WsStatus>('disconnected')
  const [ruyiStatus, setRuyiStatus] = useState('idle')
  const [tiangongStatus, setTiangongStatus] = useState('空间')
  const wsRef = useRef<WebSocket | null>(null)
  const subscribersRef = useRef<Set<Subscriber>>(new Set())
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectDelayRef = useRef(1000)

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    setStatus('connecting')
    const ws = new WebSocket(getWsUrl())

    ws.onopen = () => {
      setStatus('connected')
      reconnectDelayRef.current = 1000
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as WsMessage
        if (msg.type === 'status') {
          setRuyiStatus(msg.data.ruyi)
          setTiangongStatus(msg.data.tiangong)
        }
        subscribersRef.current.forEach((fn) => fn(msg))
      } catch {
        // ignore malformed messages
      }
    }

    ws.onclose = () => {
      setStatus('disconnected')
      wsRef.current = null
      const delay = reconnectDelayRef.current
      reconnectDelayRef.current = Math.min(delay * 2, 30000)
      reconnectTimerRef.current = setTimeout(connect, delay)
    }

    ws.onerror = () => {
      ws.close()
    }

    wsRef.current = ws
  }, [])

  useEffect(() => {
    connect()
    return () => {
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current)
      }
      wsRef.current?.close()
    }
  }, [connect])

  const subscribe = useCallback((fn: Subscriber) => {
    subscribersRef.current.add(fn)
    return () => {
      subscribersRef.current.delete(fn)
    }
  }, [])

  const send = useCallback((msg: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  return (
    <WsContext.Provider value={{ status, ruyiStatus, tiangongStatus, subscribe, send }}>
      {children}
    </WsContext.Provider>
  )
}

export function useWebSocket() {
  return useContext(WsContext)
}
