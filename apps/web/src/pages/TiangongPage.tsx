import { useState, useEffect, useCallback } from 'react'
import LogToolbar from '../components/log/LogToolbar'
import LogList from '../components/log/LogList'
import { useWebSocket, type WsMessage } from '../hooks/useWebSocket'
import type { LogItem } from '../components/log/LogEntry'

type LogLevel = 'ALL' | 'INFO' | 'WARN' | 'ERROR'

let logCounter = 0

export default function TiangongPage() {
  const [logs, setLogs] = useState<LogItem[]>([])
  const [activeLevel, setActiveLevel] = useState<LogLevel>('ALL')
  const [search, setSearch] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)
  const { subscribe } = useWebSocket()

  const handleWsMessage = useCallback((msg: WsMessage) => {
    if (msg.type === 'log') {
      const entry: LogItem = {
        id: `log-${++logCounter}`,
        timestamp: msg.data.timestamp,
        level: msg.data.level,
        message: msg.data.message,
      }
      setLogs((prev) => {
        const next = [...prev, entry]
        if (next.length > 2000) return next.slice(-1500)
        return next
      })
    }
  }, [])

  useEffect(() => {
    return subscribe(handleWsMessage)
  }, [subscribe, handleWsMessage])

  const filteredLogs = logs.filter((entry) => {
    if (activeLevel !== 'ALL' && entry.level !== activeLevel) return false
    if (search && !entry.message.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  return (
    <div className="tiangong-page">
      <div className="tiangong-header">
        <h1>天工</h1>
      </div>
      <LogToolbar
        activeLevel={activeLevel}
        onLevelChange={setActiveLevel}
        search={search}
        onSearchChange={setSearch}
        autoScroll={autoScroll}
        onAutoScrollToggle={() => setAutoScroll(!autoScroll)}
      />
      <LogList
        entries={filteredLogs}
        autoScroll={autoScroll}
        onUserScroll={() => setAutoScroll(false)}
      />
    </div>
  )
}
