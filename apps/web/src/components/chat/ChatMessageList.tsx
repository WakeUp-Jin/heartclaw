import { useEffect, useRef } from 'react'
import ChatMessage, { type ChatMsg } from './ChatMessage'

type Props = {
  messages: ChatMsg[]
}

export default function ChatMessageList({ messages }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <div className="chat-messages">
      {messages.map((msg) => (
        <ChatMessage key={msg.id} message={msg} />
      ))}
      <div ref={bottomRef} />
    </div>
  )
}
