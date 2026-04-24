import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { WebSocketProvider } from './hooks/useWebSocket'
import AppLayout from './layouts/AppLayout'
import RuyiPage from './pages/RuyiPage'
import TiangongPage from './pages/TiangongPage'
import JuanzongPage from './pages/JuanzongPage'

export default function App() {
  return (
    <BrowserRouter>
      <WebSocketProvider>
        <Routes>
          <Route element={<AppLayout />}>
            <Route index element={<Navigate to="/ruyi" replace />} />
            <Route path="ruyi" element={<RuyiPage />} />
            <Route path="tiangong" element={<TiangongPage />} />
            <Route path="juanzong" element={<JuanzongPage />} />
          </Route>
        </Routes>
      </WebSocketProvider>
    </BrowserRouter>
  )
}
