import { X } from 'lucide-react'

type Props = {
  text: string
  time: string
  onClose: () => void
}

export default function KairosReplyModal({ text, time, onClose }: Props) {
  return (
    <div className="kairos-modal-overlay" onClick={onClose}>
      <div className="kairos-modal" onClick={(e) => e.stopPropagation()}>
        <div className="kairos-modal-header">
          <span className="kairos-modal-title">完整回复内容</span>
          <button className="kairos-modal-close" onClick={onClose}>
            <X style={{ width: 16, height: 16 }} />
          </button>
        </div>
        <div className="kairos-modal-meta">回复时间：{time}</div>
        <div className="kairos-modal-body">
          {text.split('\n').map((line, i) => (
            <p key={i}>{line || '\u00A0'}</p>
          ))}
        </div>
        <div className="kairos-modal-footer">
          <button className="btn-secondary" onClick={onClose}>关闭</button>
        </div>
      </div>
    </div>
  )
}
