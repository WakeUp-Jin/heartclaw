import { Search, CheckSquare, Pause, Bug } from 'lucide-react'

export type LogLevel = 'ALL' | 'INFO' | 'WARN' | 'ERROR'
export type LogSource = 'tiangong' | 'ruyi-debug'

type Props = {
  activeLevel: LogLevel
  onLevelChange: (level: LogLevel) => void
  search: string
  onSearchChange: (value: string) => void
  autoScroll: boolean
  onAutoScrollToggle: () => void
  logSource: LogSource
  onLogSourceChange: (source: LogSource) => void
}

const levels: LogLevel[] = ['ALL', 'INFO', 'WARN', 'ERROR']

export default function LogToolbar({
  activeLevel,
  onLevelChange,
  search,
  onSearchChange,
  autoScroll,
  onAutoScrollToggle,
  logSource,
  onLogSourceChange,
}: Props) {
  const isDebug = logSource === 'ruyi-debug'

  return (
    <div className="log-toolbar">
      <div className="log-filter-tabs">
        {!isDebug && levels.map((level) => (
          <button
            key={level}
            className={`log-filter-tab${activeLevel === level ? ' active' : ''}`}
            onClick={() => onLevelChange(level)}
          >
            {level === 'ALL' ? '全部' : level}
          </button>
        ))}

        <span className="log-filter-divider" />
        <button
          className={`log-filter-tab log-debug-btn${isDebug ? ' active' : ''}`}
          onClick={() => onLogSourceChange(isDebug ? 'tiangong' : 'ruyi-debug')}
        >
          <Bug size={14} />
          如意调试
        </button>
      </div>

      <div className="log-search-wrapper">
        <Search />
        <input
          className="log-search"
          type="text"
          placeholder="搜索日志内容..."
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
        />
      </div>

      <div className="log-controls">
        <button
          className={`log-control-btn${autoScroll ? ' active' : ''}`}
          onClick={onAutoScrollToggle}
        >
          {autoScroll ? <CheckSquare /> : <Pause />}
          {autoScroll ? '自动滚动' : '暂停'}
        </button>
      </div>
    </div>
  )
}
