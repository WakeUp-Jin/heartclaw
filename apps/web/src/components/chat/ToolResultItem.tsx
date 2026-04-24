import { useState } from 'react'
import { ChevronRight, FileText, FilePen, TerminalSquare, Loader2, AlertCircle, Ban } from 'lucide-react'
import ToolResultBlock from './ToolResultBlock'

export type ToolResult = {
  type: 'read' | 'write' | 'command'
  label: string
  items?: string[]
  preview?: string[]
  call_id?: string
  status?: 'executing' | 'success' | 'error' | 'cancelled'
  error?: string
  duration_ms?: number
}

const iconMap = {
  read: FileText,
  write: FilePen,
  command: TerminalSquare,
}

type Props = {
  result: ToolResult
}

export default function ToolResultItem({ result }: Props) {
  const [expanded, setExpanded] = useState(false)

  if (result.status === 'executing') {
    return (
      <div className="tool-result-item tool-result-executing">
        <Loader2 className="tool-spin" />
        <span>{result.label}</span>
      </div>
    )
  }

  if (result.status === 'error') {
    return (
      <div className="tool-result-item tool-result-error">
        <AlertCircle />
        <span>{result.label}</span>
        {result.error && <span className="tool-error-text">{result.error}</span>}
      </div>
    )
  }

  if (result.status === 'cancelled') {
    return (
      <div className="tool-result-item tool-result-cancelled">
        <Ban />
        <span>{result.label}</span>
      </div>
    )
  }

  const Icon = iconMap[result.type] || TerminalSquare
  const hasPreview = result.preview && result.preview.length > 0

  if (result.type === 'read' && !hasPreview) {
    return (
      <div className="tool-result-item">
        <Icon />
        <span>{result.label}</span>
      </div>
    )
  }

  return (
    <div>
      <div
        className={`tool-result-item${hasPreview ? ' tool-result-expandable' : ''}`}
        onClick={() => hasPreview && setExpanded(!expanded)}
      >
        {hasPreview && (
          <ChevronRight
            className={`tool-result-chevron${expanded ? ' expanded' : ''}`}
          />
        )}
        <Icon />
        <span>{result.label}</span>
      </div>
      {expanded && result.preview && (
        <ToolResultBlock lines={result.preview} />
      )}
    </div>
  )
}
