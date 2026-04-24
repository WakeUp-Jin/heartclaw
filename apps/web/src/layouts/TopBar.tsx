import { Columns2 } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { useSplitView } from '../stores/useSplitView'

type Props = {
  connected: boolean
}

export default function TopBar({ connected }: Props) {
  const { rightPanel, toggleSplit } = useSplitView()
  const location = useLocation()
  const currentRoute = location.pathname.split('/')[1] || ''
  const isSplit = rightPanel !== null

  return (
    <header className="topbar">
      <div className="topbar-left">
        <span className="topbar-title">HeartClaw Console</span>
        <button
          className={`topbar-split-btn${isSplit ? ' topbar-split-btn-active' : ''}`}
          onClick={() => toggleSplit(currentRoute)}
          title={isSplit ? '关闭分屏' : '开启分屏'}
        >
          <Columns2 size={16} />
        </button>
        {isSplit && <span className="topbar-split-hint">分屏模式已开启</span>}
      </div>
      <div className="topbar-status">
        <span className={`topbar-dot${connected ? '' : ' disconnected'}`} />
        {connected ? 'connected' : 'disconnected'}
      </div>
    </header>
  )
}
