import { Search, CheckSquare, Pause } from 'lucide-react'

type LogLevel = 'ALL' | 'INFO' | 'WARN' | 'ERROR'

type Props = {
  activeLevel: LogLevel
  onLevelChange: (level: LogLevel) => void
  search: string
  onSearchChange: (value: string) => void
  autoScroll: boolean
  onAutoScrollToggle: () => void
}

const levels: LogLevel[] = ['ALL', 'INFO', 'WARN', 'ERROR']

export default function LogToolbar({
  activeLevel,
  onLevelChange,
  search,
  onSearchChange,
  autoScroll,
  onAutoScrollToggle,
}: Props) {
  return (
    <div className="log-toolbar">
      <div className="log-filter-tabs">
        {levels.map((level) => (
          <button
            key={level}
            className={`log-filter-tab${activeLevel === level ? ' active' : ''}`}
            onClick={() => onLevelChange(level)}
          >
            {level === 'ALL' ? '全部' : level}
          </button>
        ))}
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
