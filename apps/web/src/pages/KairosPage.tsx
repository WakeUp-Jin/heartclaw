import { useState } from 'react'
import KairosEventList from '../components/kairos/KairosEventList'
import KairosStatusPanel from '../components/kairos/KairosStatusPanel'
import KairosReplyPreview from '../components/kairos/KairosReplyPreview'
import KairosReplyModal from '../components/kairos/KairosReplyModal'
import { useAppStore } from '../stores/useAppStore'

export default function KairosPage() {
  const { events, stats } = useAppStore().kairos
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [modalReply, setModalReply] = useState<{ text: string; time: string } | null>(null)
  const [page, setPage] = useState(1)
  const pageSize = 10

  const totalEvents = events.length
  const totalPages = Math.max(1, Math.ceil(totalEvents / pageSize))
  const pagedEvents = events.slice((page - 1) * pageSize, page * pageSize)

  const selectedEvent = selectedId ? events.find((e) => e.id === selectedId) ?? null : null
  const latestReply = events.find((e) => e.type === '回复' && e.replyText)

  const replyForPreview = selectedEvent?.type === '回复' && selectedEvent.replyText
    ? { text: selectedEvent.replyText, time: selectedEvent.time }
    : latestReply
      ? { text: latestReply.replyText!, time: latestReply.time }
      : null

  function handleViewFullReply() {
    if (replyForPreview) {
      setModalReply(replyForPreview)
    }
  }

  const selectedHint = selectedEvent && selectedEvent.type !== '回复'
    ? selectedEvent.type === '工具调用'
      ? '当前选中项为工具调用，暂无回复正文'
      : selectedEvent.type === '睡眠'
        ? '当前选中项为睡眠事件，Kairos 已进入可中断 sleep'
        : selectedEvent.type === '巡检'
          ? '当前选中项为巡检事件'
          : selectedEvent.type === '中断'
            ? '当前选中项为中断事件，睡眠已被新消息打断'
            : null
    : null

  return (
    <div className="kairos-page">
      <div className="kairos-header">
        <h1>Kairos</h1>
        <p>自主巡检与调度智能体 — 查看自治运行状态与事件流。</p>
      </div>
      <div className="kairos-body">
        <div className="kairos-left">
          <KairosEventList
            events={pagedEvents}
            selectedId={selectedId}
            onSelect={setSelectedId}
            total={totalEvents}
            page={page}
            pageSize={pageSize}
            totalPages={totalPages}
            onPageChange={setPage}
          />
        </div>
        <div className="kairos-right">
          <KairosStatusPanel stats={stats} />
          <KairosReplyPreview
            reply={replyForPreview}
            hint={selectedHint}
            onViewFull={handleViewFullReply}
          />
        </div>
      </div>
      {modalReply && (
        <KairosReplyModal
          text={modalReply.text}
          time={modalReply.time}
          onClose={() => setModalReply(null)}
        />
      )}
    </div>
  )
}
