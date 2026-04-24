import { useState } from 'react'
import { ChevronRight, FileText, FilePen, TerminalSquare } from 'lucide-react'
import ToolResultBlock from './ToolResultBlock'

export type ToolResult = {
  type: 'read' | 'write' | 'command'
  label: string
  items?: string[]
  preview?: string[]
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
  const Icon = iconMap[result.type]
  const hasPreview = result.preview && result.preview.length > 0

  if (result.type === 'read') {
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
