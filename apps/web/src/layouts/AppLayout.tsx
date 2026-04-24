import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import TopBar from './TopBar'
import StatusBar from './StatusBar'
import { useWebSocket } from '../hooks/useWebSocket'

export default function AppLayout() {
  const { status, ruyiStatus, tiangongStatus } = useWebSocket()

  return (
    <div className="app-shell">
      <Sidebar />
      <TopBar connected={status === 'connected'} />
      <main className="main-content">
        <Outlet />
      </main>
      <StatusBar
        wsStatus={status}
        ruyiStatus={ruyiStatus}
        tiangongStatus={tiangongStatus}
      />
    </div>
  )
}
