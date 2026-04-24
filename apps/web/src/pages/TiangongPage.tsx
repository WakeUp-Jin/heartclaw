import { useState } from 'react'
import LogToolbar, { type LogLevel, type LogSource } from '../components/log/LogToolbar'
import LogList from '../components/log/LogList'
import { useAppStore } from '../stores/useAppStore'

export default function TiangongPage() {
  const { tiangongLogs, ruyiDebugLogs } = useAppStore().tiangong
  const [activeLevel, setActiveLevel] = useState<LogLevel>('ALL')
  const [search, setSearch] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)
  const [logSource, setLogSource] = useState<LogSource>('tiangong')

  const isDebug = logSource === 'ruyi-debug'
  const baseLogs = isDebug ? ruyiDebugLogs : tiangongLogs

  const filteredLogs = baseLogs.filter((entry) => {
    if (!isDebug && activeLevel !== 'ALL' && entry.level !== activeLevel) return false
    if (search && !entry.message.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  return (
    <div className="tiangong-page">
      <div className="tiangong-header">
        <h1>{isDebug ? '如意调试日志' : '天工'}</h1>
      </div>
      <LogToolbar
        activeLevel={activeLevel}
        onLevelChange={setActiveLevel}
        search={search}
        onSearchChange={setSearch}
        autoScroll={autoScroll}
        onAutoScrollToggle={() => setAutoScroll(!autoScroll)}
        logSource={logSource}
        onLogSourceChange={setLogSource}
      />
      <LogList
        entries={filteredLogs}
        autoScroll={autoScroll}
        onUserScroll={() => setAutoScroll(false)}
      />
    </div>
  )
}
