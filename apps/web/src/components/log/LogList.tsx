import { useEffect, useRef, useCallback } from 'react'
import { ArrowDown } from 'lucide-react'
import LogEntryComponent, { type LogItem } from './LogEntry'

type Props = {
  entries: LogItem[]
  autoScroll: boolean
  onUserScroll: () => void
}

export default function LogList({ entries, autoScroll, onUserScroll }: Props) {
  const panelRef = useRef<HTMLDivElement>(null)
  const isAtBottomRef = useRef(true)

  const scrollToBottom = useCallback(() => {
    const el = panelRef.current
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  }, [])

  useEffect(() => {
    if (autoScroll) {
      scrollToBottom()
    }
  }, [entries, autoScroll, scrollToBottom])

  function handleScroll() {
    const el = panelRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    isAtBottomRef.current = atBottom
    if (!atBottom && autoScroll) {
      onUserScroll()
    }
  }

  return (
    <div className="log-panel" ref={panelRef} onScroll={handleScroll}>
      {entries.map((entry) => (
        <LogEntryComponent key={entry.id} entry={entry} />
      ))}
      {entries.length > 0 && (
        <div className="log-entry log-entry-info">
          <span className="log-timestamp" />
          <span className="log-level">INFO</span>
          <span className="log-message">
            <span className="log-cursor" />
          </span>
        </div>
      )}
      {!autoScroll && (
        <button className="log-scroll-btn" onClick={scrollToBottom}>
          <ArrowDown />
          回到底部
        </button>
      )}
    </div>
  )
}
