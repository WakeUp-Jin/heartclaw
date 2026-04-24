import ChatMessageList from '../components/chat/ChatMessageList'
import ChatInput from '../components/chat/ChatInput'
import { useAppStore } from '../stores/useAppStore'

export default function RuyiPage() {
  const { messages, loading, sendMessage } = useAppStore().ruyi

  return (
    <div className="ruyi-page">
      <div className="ruyi-header">
        <h1>如意</h1>
      </div>
      <ChatMessageList messages={messages} />
      <ChatInput onSend={sendMessage} disabled={loading} />
    </div>
  )
}
