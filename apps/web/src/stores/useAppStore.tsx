import { useState, useEffect, useCallback, useRef, createContext, useContext } from 'react'
import { useWebSocket, type WsMessage, type ChatTool, type ToolStatus } from '../hooks/useWebSocket'
import type { ChatMsg, MsgBlock } from '../components/chat/ChatMessage'
import type { ToolResult } from '../components/chat/ToolResultItem'
import type { LogItem } from '../components/log/LogEntry'

// ── Kairos types (previously in KairosPage) ────────────────────

export type KairosEventType = '巡检' | '工具调用' | '回复' | '睡眠' | '中断'
export type KairosEventStatus = '已完成' | '执行中' | '成功' | '睡眠中' | '被打断' | '失败'

export type KairosEventItem = {
  id: string
  time: string
  type: KairosEventType
  status: KairosEventStatus
  summary: string
  duration?: string
  replyText?: string
}

export type KairosStats = {
  currentStatus: string
  toolCallCount: number
  lastReplyTime: string
  todayTickCount: number
  sleepRemaining: string
}

// ── Context shape ──────────────────────────────────────────────

type RuyiState = {
  messages: ChatMsg[]
  loading: boolean
  sendMessage: (text: string) => Promise<void>
}

type TiangongState = {
  tiangongLogs: LogItem[]
  ruyiDebugLogs: LogItem[]
}

type KairosState = {
  events: KairosEventItem[]
  stats: KairosStats
}

type AppStoreValue = {
  ruyi: RuyiState
  tiangong: TiangongState
  kairos: KairosState
}

const AppStoreContext = createContext<AppStoreValue>(null!)

// ── Helpers (moved from pages) ─────────────────────────────────

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL as string) || ''

let msgCounter = 0
function nextMsgId() {
  return `msg-${++msgCounter}-${Date.now()}`
}

function formatTime() {
  return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function toolFromWs(data: ChatTool): ToolResult {
  return { type: data.tool_type, label: data.label, items: data.items, preview: data.preview }
}

function toolTypeFromName(name: string): 'read' | 'write' | 'command' {
  const readTools = ['ReadFile', 'Grep', 'Glob', 'ListFiles', 'read_memory', 'CronList']
  if (readTools.includes(name)) return 'read'
  const commandTools = ['Bash', 'Sleep']
  if (commandTools.includes(name)) return 'command'
  return 'write'
}

function toolResultFromStatus(data: ToolStatus, existingLabel?: string): ToolResult {
  const type = toolTypeFromName(data.tool_name)
  if (data.status === 'executing') {
    return { type, label: `${data.tool_name}  ${data.args_summary}`, call_id: data.call_id, status: 'executing' }
  }
  const label = data.status === 'success'
    ? existingLabel ?? `${data.tool_name}  ${data.args_summary ?? ''}`
    : existingLabel ?? `${data.tool_name}  失败`
  return {
    type, label, call_id: data.call_id,
    status: data.status as ToolResult['status'],
    error: data.error, duration_ms: data.duration_ms,
    preview: data.result_preview ? [data.result_preview] : undefined,
  }
}

let logCounter = 0
let eventCounter = 0
function nextEventId() { return `ke-${++eventCounter}-${Date.now()}` }

function formatTimeShort(ts: string): string {
  if (!ts) return '--'
  const parts = ts.split(' ')
  const timePart = parts.length > 1 ? parts[1] : parts[0]
  return timePart.substring(0, 8)
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms.toFixed(0)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

// ── Provider ───────────────────────────────────────────────────

export function AppStoreProvider({ children }: { children: React.ReactNode }) {
  const { subscribe } = useWebSocket()

  // ── Ruyi state ──
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [loading, setLoading] = useState(false)
  const streamingMsgRef = useRef<string | null>(null)

  // ── Tiangong state ──
  const [tiangongLogs, setTiangongLogs] = useState<LogItem[]>([])
  const [ruyiDebugLogs, setRuyiDebugLogs] = useState<LogItem[]>([])

  // ── Kairos state ──
  const [kairosEvents, setKairosEvents] = useState<KairosEventItem[]>([])
  const [kairosStats, setKairosStats] = useState<KairosStats>({
    currentStatus: '空闲', toolCallCount: 0,
    lastReplyTime: '--', todayTickCount: 0, sleepRemaining: '--',
  })
  const currentTickIdRef = useRef<string | null>(null)
  const sleepTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const sleepEndRef = useRef<number | null>(null)

  // ── Kairos sleep countdown ──
  const updateSleepCountdown = useCallback(() => {
    if (sleepEndRef.current === null) return
    const remaining = Math.max(0, sleepEndRef.current - Date.now())
    if (remaining <= 0) {
      setKairosStats((s) => ({ ...s, sleepRemaining: '--' }))
      if (sleepTimerRef.current) { clearInterval(sleepTimerRef.current); sleepTimerRef.current = null }
      sleepEndRef.current = null
      return
    }
    const mins = Math.floor(remaining / 60000)
    const secs = Math.floor((remaining % 60000) / 1000)
    setKairosStats((s) => ({
      ...s, sleepRemaining: `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`,
    }))
  }, [])

  // ── Ruyi helpers ──
  const ensureAssistantMsg = useCallback((): string => {
    const existing = streamingMsgRef.current
    if (existing) return existing
    const id = nextMsgId()
    streamingMsgRef.current = id
    setMessages((prev) => [
      ...prev,
      { id, role: 'assistant', content: '', timestamp: formatTime(), blocks: [] },
    ])
    return id
  }, [])

  function appendBlock(m: ChatMsg, block: MsgBlock): ChatMsg {
    return { ...m, blocks: [...(m.blocks || []), block] }
  }

  function appendTextToLastBlock(m: ChatMsg, text: string): ChatMsg {
    const blocks = m.blocks || []
    const last = blocks[blocks.length - 1]
    if (last && last.kind === 'text') {
      const updated = [...blocks]
      updated[blocks.length - 1] = { kind: 'text', text: last.text + text }
      return { ...m, content: m.content + text, blocks: updated }
    }
    return { ...m, content: m.content + text, blocks: [...blocks, { kind: 'text', text }] }
  }

  function updateToolInBlocks(m: ChatMsg, callId: string, updater: (t: ToolResult) => ToolResult): ChatMsg {
    const blocks = m.blocks || []
    let found = false
    const newBlocks = blocks.map((b) => {
      if (b.kind === 'tool' && b.tool.call_id === callId) {
        found = true
        return { kind: 'tool' as const, tool: updater(b.tool) }
      }
      return b
    })
    if (!found) return m
    return { ...m, blocks: newBlocks }
  }

  // ── Unified WS handler ──
  const handleWsMessage = useCallback((msg: WsMessage) => {
    // === Ruyi messages ===
    if (msg.type === 'chat_chunk') {
      const { content, done } = msg.data
      if (done) { streamingMsgRef.current = null; return }
      setMessages((prev) => {
        if (streamingMsgRef.current) {
          return prev.map((m) =>
            m.id === streamingMsgRef.current ? appendTextToLastBlock(m, content) : m
          )
        }
        const id = nextMsgId()
        streamingMsgRef.current = id
        return [...prev, {
          id, role: 'assistant', content, timestamp: formatTime(),
          blocks: [{ kind: 'text', text: content }],
        }]
      })
    } else if (msg.type === 'chat_tool') {
      const tool = toolFromWs(msg.data)
      const toolBlock: MsgBlock = { kind: 'tool', tool }
      setMessages((prev) => {
        if (!streamingMsgRef.current) {
          const id = nextMsgId()
          streamingMsgRef.current = id
          return [...prev, {
            id, role: 'assistant', content: '', timestamp: formatTime(),
            blocks: [toolBlock],
          }]
        }
        return prev.map((m) =>
          m.id === streamingMsgRef.current ? appendBlock(m, toolBlock) : m
        )
      })
    } else if (msg.type === 'tool_status') {
      const data = msg.data

      if (data.source === 'ruyi') {
        if (data.status === 'executing') {
          const msgId = ensureAssistantMsg()
          const tool = toolResultFromStatus(data)
          const toolBlock: MsgBlock = { kind: 'tool', tool }
          setMessages((prev) =>
            prev.map((m) => {
              if (m.id !== msgId) return m
              let updated = m
              if (data.content) {
                updated = appendBlock(updated, { kind: 'text', text: data.content })
                updated = { ...updated, content: updated.content ? updated.content + data.content : data.content }
              }
              updated = appendBlock(updated, toolBlock)
              return updated
            })
          )
        } else {
          setMessages((prev) =>
            prev.map((m) =>
              updateToolInBlocks(m, data.call_id, (existing) =>
                toolResultFromStatus(data, existing.label)
              )
            )
          )
        }
      }

      if (data.source === 'kairos') {
        if (data.status === 'executing') {
          const id = `tool-${data.call_id}`
          const time = formatTimeShort(new Date().toISOString().replace('T', ' ').substring(0, 23))
          setKairosEvents((prev) => [{
            id, time, type: '工具调用', status: '执行中',
            summary: `${data.tool_name}  ${data.args_summary}`,
          }, ...prev])
          setKairosStats((s) => ({ ...s, toolCallCount: s.toolCallCount + 1 }))
        } else {
          const id = `tool-${data.call_id}`
          const status: KairosEventStatus = data.status === 'success' ? '成功' : '失败'
          const durationStr = data.duration_ms ? formatDuration(data.duration_ms) : undefined
          setKairosEvents((prev) => prev.map((e) =>
            e.id === id ? { ...e, status, duration: durationStr ?? e.duration } : e
          ))
        }
      }
    }

    // === Container logs (tiangong / ruyi files) ===
    if (msg.type === 'container_log') {
      const { source, timestamp, level, message } = msg.data
      const entry: LogItem = {
        id: `log-${++logCounter}`,
        timestamp,
        level: level as LogItem['level'],
        message,
      }
      const setter = source === 'tiangong' ? setTiangongLogs : setRuyiDebugLogs
      setter((prev) => {
        const next = [...prev, entry]
        if (next.length > 2000) return next.slice(-1500)
        return next
      })
    }

    // === Kairos lifecycle ===
    if (msg.type === 'kairos_event') {
      const { event, timestamp, detail } = msg.data
      const time = formatTimeShort(timestamp)

      if (event === 'tick_start') {
        const id = nextEventId()
        currentTickIdRef.current = id
        setKairosEvents((prev) => [{ id, time, type: '巡检', status: '执行中', summary: '启动本轮巡检流程' }, ...prev])
        setKairosStats((s) => ({ ...s, currentStatus: '巡检中', todayTickCount: s.todayTickCount + 1 }))
      } else if (event === 'tick_done') {
        const tickId = currentTickIdRef.current
        if (tickId) {
          setKairosEvents((prev) => prev.map((e) =>
            e.id === tickId ? { ...e, status: '已完成' as const, summary: '本轮巡检结束，准备进入睡眠' } : e
          ))
        }
        currentTickIdRef.current = null
        setKairosStats((s) => ({ ...s, currentStatus: '空闲' }))
      } else if (event === 'sleep_start') {
        const sleepSeconds = (detail.sleep_seconds as number) || 300
        const id = nextEventId()
        setKairosEvents((prev) => [{
          id, time, type: '睡眠', status: '睡眠中',
          summary: `等待 ${sleepSeconds}s，可被新消息打断`, duration: `${sleepSeconds}s`,
        }, ...prev])
        setKairosStats((s) => ({ ...s, currentStatus: '睡眠中' }))
        sleepEndRef.current = Date.now() + sleepSeconds * 1000
        if (sleepTimerRef.current) clearInterval(sleepTimerRef.current)
        sleepTimerRef.current = setInterval(updateSleepCountdown, 1000)
        updateSleepCountdown()
      } else if (event === 'sleep_done') {
        setKairosEvents((prev) => {
          const idx = prev.findIndex((e) => e.type === '睡眠' && e.status === '睡眠中')
          if (idx === -1) return prev
          const updated = [...prev]
          updated[idx] = { ...updated[idx], status: '已完成', summary: '睡眠结束' }
          return updated
        })
        sleepEndRef.current = null
        if (sleepTimerRef.current) { clearInterval(sleepTimerRef.current); sleepTimerRef.current = null }
        setKairosStats((s) => ({ ...s, currentStatus: '空闲', sleepRemaining: '--' }))
      } else if (event === 'sleep_interrupted') {
        setKairosEvents((prev) => {
          const idx = prev.findIndex((e) => e.type === '睡眠' && e.status === '睡眠中')
          if (idx === -1) {
            return [{ id: nextEventId(), time, type: '中断', status: '被打断', summary: '新消息到达，睡眠被打断' }, ...prev]
          }
          const updated = [...prev]
          updated[idx] = { ...updated[idx], status: '被打断', summary: '新消息到达，睡眠被打断' }
          return [{ id: nextEventId(), time, type: '中断', status: '被打断', summary: '新消息到达，睡眠被打断' }, ...updated]
        })
        sleepEndRef.current = null
        if (sleepTimerRef.current) { clearInterval(sleepTimerRef.current); sleepTimerRef.current = null }
        setKairosStats((s) => ({ ...s, currentStatus: '被打断', sleepRemaining: '--' }))
      }
    }

    // === Kairos reply ===
    if (msg.type === 'kairos_reply') {
      const { text, timestamp } = msg.data
      const time = formatTimeShort(timestamp)
      const summaryText = text.length > 40 ? text.substring(0, 40) + '...' : text
      setKairosEvents((prev) => [{
        id: nextEventId(), time, type: '回复', status: '已完成',
        summary: summaryText, replyText: text,
      }, ...prev])
      setKairosStats((s) => ({ ...s, lastReplyTime: time.substring(0, 5) }))
    }
  }, [ensureAssistantMsg, updateSleepCountdown])

  useEffect(() => {
    return subscribe(handleWsMessage)
  }, [subscribe, handleWsMessage])

  useEffect(() => {
    return () => { if (sleepTimerRef.current) clearInterval(sleepTimerRef.current) }
  }, [])

  // ── Load recent log history on mount ──
  useEffect(() => {
    async function loadHistory(source: 'tiangong' | 'ruyi') {
      try {
        const resp = await fetch(`${apiBaseUrl}/api/logs/recent?source=${source}&lines=200`)
        if (!resp.ok) return
        const data = (await resp.json()) as Array<{ timestamp: string; level: string; message: string }>
        const items: LogItem[] = data.map((d) => ({
          id: `log-${++logCounter}`,
          timestamp: d.timestamp,
          level: d.level as LogItem['level'],
          message: d.message,
        }))
        if (source === 'tiangong') setTiangongLogs(items)
        else setRuyiDebugLogs(items)
      } catch { /* API may not be available yet */ }
    }
    loadHistory('tiangong')
    loadHistory('ruyi')
  }, [])

  // ── Ruyi send action ──
  const sendMessage = useCallback(async (text: string) => {
    const userMsg: ChatMsg = { id: nextMsgId(), role: 'user', content: text, timestamp: formatTime() }
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
          {
            id: nextMsgId(), role: 'assistant', content: data.reply!, timestamp: formatTime(),
            blocks: [{ kind: 'text', text: data.reply! }],
          },
        ])
      } else if (streamingMsgRef.current && data.reply) {
        const finalMsgId = streamingMsgRef.current
        setMessages((prev) =>
          prev.map((m) =>
            m.id === finalMsgId ? appendTextToLastBlock(m, data.reply!) : m
          )
        )
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : '未知错误'
      const errText = `请求失败：${detail}。请确认如意 API 已启动。`
      setMessages((prev) => [
        ...prev,
        {
          id: nextMsgId(), role: 'assistant', content: errText, timestamp: formatTime(),
          blocks: [{ kind: 'text', text: errText }],
        },
      ])
    } finally {
      setLoading(false)
      streamingMsgRef.current = null
    }
  }, [])

  const value: AppStoreValue = {
    ruyi: { messages, loading, sendMessage },
    tiangong: { tiangongLogs, ruyiDebugLogs },
    kairos: { events: kairosEvents, stats: kairosStats },
  }

  return (
    <AppStoreContext.Provider value={value}>
      {children}
    </AppStoreContext.Provider>
  )
}

export function useAppStore() {
  return useContext(AppStoreContext)
}
