import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import ToolResultItem, { type ToolResult } from './ToolResultItem'

export type TextBlock = { kind: 'text'; text: string }
export type ToolBlock = { kind: 'tool'; tool: ToolResult }
export type MsgBlock = TextBlock | ToolBlock

export type ChatMsg = {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  toolResults?: ToolResult[]
  blocks?: MsgBlock[]
}

type Props = {
  message: ChatMsg
}

export default function ChatMessage({ message }: Props) {
  const isUser = message.role === 'user'
  const blocks = message.blocks

  if (isUser) {
    return (
      <div className="chat-msg chat-msg-user">
        <div>
          <div className="chat-timestamp">{message.timestamp}</div>
          {message.content && (
            <div className="chat-bubble">{message.content}</div>
          )}
        </div>
      </div>
    )
  }

  if (blocks && blocks.length > 0) {
    return (
      <div className="chat-msg chat-msg-assistant">
        <div>
          <div className="chat-timestamp">{message.timestamp}</div>
          {blocks.map((block, i) => {
            if (block.kind === 'text') {
              return (
                <div key={`text-${i}`} className="chat-bubble">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {block.text}
                  </ReactMarkdown>
                </div>
              )
            }
            return (
              <div key={block.tool.call_id || `tool-${i}`} className="tool-results">
                <ToolResultItem result={block.tool} />
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  const hasTools = message.toolResults && message.toolResults.length > 0
  return (
    <div className="chat-msg chat-msg-assistant">
      <div>
        <div className="chat-timestamp">{message.timestamp}</div>
        {hasTools && (
          <div className="tool-results">
            {message.toolResults!.map((tr, i) => (
              <ToolResultItem key={tr.call_id || i} result={tr} />
            ))}
          </div>
        )}
        {message.content && (
          <div className="chat-bubble">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  )
}
