export type LogItem = {
  id: string
  timestamp: string
  level: 'INFO' | 'WARN' | 'ERROR'
  message: string
}

type Props = {
  entry: LogItem
}

const levelClass: Record<string, string> = {
  INFO: 'log-entry-info',
  WARN: 'log-entry-warn',
  ERROR: 'log-entry-error',
}

export default function LogEntry({ entry }: Props) {
  return (
    <div className={`log-entry ${levelClass[entry.level] || ''}`}>
      <span className="log-timestamp">{entry.timestamp}</span>
      <span className="log-level">{entry.level}</span>
      <span className="log-message">{entry.message}</span>
    </div>
  )
}
