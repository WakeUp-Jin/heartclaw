import { Moon, Wrench, MessageSquare, Search, Clock } from 'lucide-react'
import type { KairosStats } from '../../stores/useAppStore'

type Props = {
  stats: KairosStats
}

const statusColorClass: Record<string, string> = {
  '巡检中': 'kairos-stat-running',
  '睡眠中': 'kairos-stat-sleep',
  '被打断': 'kairos-stat-interrupted',
  '空闲': 'kairos-stat-idle',
}

export default function KairosStatusPanel({ stats }: Props) {
  return (
    <div className="kairos-status-panel">
      <div className="kairos-stat-grid">
        <div className={`kairos-stat-card ${statusColorClass[stats.currentStatus] ?? 'kairos-stat-idle'}`}>
          <div className="kairos-stat-label">
            <Moon style={{ width: 14, height: 14 }} />
            当前状态
          </div>
          <div className="kairos-stat-value kairos-stat-value-lg">{stats.currentStatus}</div>
          {stats.currentStatus === '睡眠中' && (
            <div className="kairos-stat-hint">可被新消息打断</div>
          )}
        </div>
        <div className="kairos-stat-card">
          <div className="kairos-stat-label">
            <Wrench style={{ width: 14, height: 14 }} />
            工具调用次数
          </div>
          <div className="kairos-stat-value">{stats.toolCallCount}</div>
          <div className="kairos-stat-hint">本轮</div>
        </div>
        <div className="kairos-stat-card">
          <div className="kairos-stat-label">
            <MessageSquare style={{ width: 14, height: 14 }} />
            最近回复
          </div>
          <div className="kairos-stat-value">{stats.lastReplyTime}</div>
        </div>
        <div className="kairos-stat-card">
          <div className="kairos-stat-label">
            <Search style={{ width: 14, height: 14 }} />
            今日巡检
          </div>
          <div className="kairos-stat-value">{stats.todayTickCount} <small>次</small></div>
        </div>
        <div className="kairos-stat-card">
          <div className="kairos-stat-label">
            <Clock style={{ width: 14, height: 14 }} />
            Sleep 剩余
          </div>
          <div className="kairos-stat-value">{stats.sleepRemaining}</div>
        </div>
      </div>
    </div>
  )
}
