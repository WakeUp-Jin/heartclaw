import ToolResultItem, { type ToolResult } from './ToolResultItem'

export type ChatMsg = {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  toolResults?: ToolResult[]
}

type Props = {
  message: ChatMsg
}

export default function ChatMessage({ message }: Props) {
  const isUser = message.role === 'user'

  return (
    <div className={`chat-msg ${isUser ? 'chat-msg-user' : 'chat-msg-assistant'}`}>
      <div>
        <div className="chat-timestamp">{message.timestamp}</div>
        <div className="chat-bubble">{message.content}</div>
        {!isUser && message.toolResults && message.toolResults.length > 0 && (
          <div className="tool-results">
            {message.toolResults.map((tr, i) => (
              <ToolResultItem key={i} result={tr} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
