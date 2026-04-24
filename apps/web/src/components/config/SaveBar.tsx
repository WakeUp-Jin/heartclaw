type Props = {
  modified: boolean
  saving: boolean
  onSave: () => void
  onDiscard: () => void
}

export default function SaveBar({ modified, saving, onSave, onDiscard }: Props) {
  return (
    <div className="save-bar">
      <div className="save-bar-status">
        {modified && <span className="modified-dot" />}
        <span>{saving ? '保存中...' : modified ? '已修改' : '未修改'}</span>
      </div>
      <div className="save-bar-actions">
        <button
          className="btn-primary"
          onClick={onSave}
          disabled={!modified || saving}
        >
          保存
        </button>
        <button
          className="btn-secondary"
          onClick={onDiscard}
          disabled={!modified || saving}
        >
          放弃更改
        </button>
      </div>
    </div>
  )
}
