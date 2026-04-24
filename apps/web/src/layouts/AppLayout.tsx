import Sidebar from './Sidebar'
import TopBar from './TopBar'
import SplitContainer from './SplitContainer'
import { useWebSocket } from '../hooks/useWebSocket'

export default function AppLayout() {
  const { status } = useWebSocket()

  return (
    <div className="app-shell">
      <Sidebar />
      <TopBar connected={status === 'connected'} />
      <main className="main-content">
        <SplitContainer />
      </main>
    </div>
  )
}
