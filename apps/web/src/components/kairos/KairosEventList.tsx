import { Search, CheckCircle, Play, Wrench, MessageSquare, Moon, Zap, ChevronLeft, ChevronRight } from 'lucide-react'
import type { KairosEventItem, KairosEventType, KairosEventStatus } from '../../stores/useAppStore'

type Props = {
  events: KairosEventItem[]
  selectedId: string | null
  onSelect: (id: string) => void
  total: number
  page: number
  pageSize: number
  totalPages: number
  onPageChange: (page: number) => void
}

const typeIcons: Record<KairosEventType, typeof Search> = {
  '巡检': Search,
  '工具调用': Wrench,
  '回复': MessageSquare,
  '睡眠': Moon,
  '中断': Zap,
}

const statusClass: Record<KairosEventStatus, string> = {
  '已完成': 'kairos-status-done',
  '执行中': 'kairos-status-running',
  '成功': 'kairos-status-success',
  '睡眠中': 'kairos-status-sleep',
  '被打断': 'kairos-status-interrupted',
  '失败': 'kairos-status-error',
}

function PageButton({ n, active, onClick }: { n: number; active: boolean; onClick: () => void }) {
  return (
    <button
      className={`kairos-page-btn${active ? ' active' : ''}`}
      onClick={onClick}
    >
      {n}
    </button>
  )
}

function buildPageNumbers(current: number, total: number): (number | '...')[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
  const pages: (number | '...')[] = [1]
  const start = Math.max(2, current - 1)
  const end = Math.min(total - 1, current + 1)
  if (start > 2) pages.push('...')
  for (let i = start; i <= end; i++) pages.push(i)
  if (end < total - 1) pages.push('...')
  pages.push(total)
  return pages
}

export default function KairosEventList({
  events, selectedId, onSelect,
  total, page, pageSize, totalPages, onPageChange,
}: Props) {
  return (
    <div className="kairos-event-panel">
      <div className="kairos-event-header">
        <span className="kairos-event-title">运行事件</span>
      </div>
      <div className="kairos-event-table">
        <div className="kairos-event-thead">
          <span className="kairos-col-time">时间</span>
          <span className="kairos-col-type">类型</span>
          <span className="kairos-col-status">状态</span>
          <span className="kairos-col-summary">摘要</span>
          <span className="kairos-col-duration">耗时</span>
        </div>
        <div className="kairos-event-tbody">
          {events.length === 0 ? (
            <div className="kairos-event-empty">暂无事件，等待 Kairos 启动巡检...</div>
          ) : (
            events.map((evt) => {
              const Icon = typeIcons[evt.type]
              return (
                <div
                  key={evt.id}
                  className={`kairos-event-row${selectedId === evt.id ? ' selected' : ''}`}
                  onClick={() => onSelect(evt.id)}
                >
                  <span className="kairos-col-time">{evt.time}</span>
                  <span className="kairos-col-type">
                    <Icon style={{ width: 14, height: 14 }} />
                    {evt.type}
                  </span>
                  <span className="kairos-col-status">
                    <span className={`kairos-status-tag ${statusClass[evt.status]}`}>
                      {evt.status}
                    </span>
                  </span>
                  <span className="kairos-col-summary" title={evt.summary}>{evt.summary}</span>
                  <span className="kairos-col-duration">{evt.duration ?? '--'}</span>
                </div>
              )
            })
          )}
        </div>
      </div>
      <div className="kairos-pagination">
        <span className="kairos-pagination-total">共 {total} 条</span>
        <div className="kairos-pagination-nav">
          <button
            className="kairos-page-arrow"
            disabled={page <= 1}
            onClick={() => onPageChange(page - 1)}
          >
            <ChevronLeft style={{ width: 14, height: 14 }} />
          </button>
          {buildPageNumbers(page, totalPages).map((n, i) =>
            n === '...'
              ? <span key={`dots-${i}`} className="kairos-page-dots">...</span>
              : <PageButton key={n} n={n} active={n === page} onClick={() => onPageChange(n)} />
          )}
          <button
            className="kairos-page-arrow"
            disabled={page >= totalPages}
            onClick={() => onPageChange(page + 1)}
          >
            <ChevronRight style={{ width: 14, height: 14 }} />
          </button>
        </div>
        <span className="kairos-pagination-size">{pageSize} 条/页</span>
      </div>
    </div>
  )
}
