type Props = {
  reply: { text: string; time: string } | null
  hint: string | null
  onViewFull: () => void
}

export default function KairosReplyPreview({ reply, hint, onViewFull }: Props) {
  return (
    <div className="kairos-reply-preview">
      <div className="kairos-reply-preview-title">回复内容预览</div>
      {hint && !reply ? (
        <div className="kairos-reply-hint">{hint}</div>
      ) : reply ? (
        <>
          <div className="kairos-reply-text">
            {reply.text.length > 200 ? reply.text.substring(0, 200) + '...' : reply.text}
          </div>
          <button className="kairos-reply-view-btn" onClick={onViewFull}>
            查看完整回复
          </button>
        </>
      ) : (
        <div className="kairos-reply-hint">暂无回复内容</div>
      )}
    </div>
  )
}
