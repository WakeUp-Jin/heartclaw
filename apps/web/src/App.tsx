import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { WebSocketProvider } from './hooks/useWebSocket'
import { AppStoreProvider } from './stores/useAppStore'
import { SplitViewProvider } from './stores/useSplitView'
import AppLayout from './layouts/AppLayout'
import RuyiPage from './pages/RuyiPage'
import TiangongPage from './pages/TiangongPage'
import JuanzongPage from './pages/JuanzongPage'
import KairosPage from './pages/KairosPage'

export default function App() {
  return (
    <BrowserRouter>
      <WebSocketProvider>
        <AppStoreProvider>
          <SplitViewProvider>
            <Routes>
              <Route element={<AppLayout />}>
                <Route index element={<Navigate to="/ruyi" replace />} />
                <Route path="ruyi" element={<RuyiPage />} />
                <Route path="tiangong" element={<TiangongPage />} />
                <Route path="juanzong" element={<JuanzongPage />} />
                <Route path="kairos" element={<KairosPage />} />
              </Route>
            </Routes>
          </SplitViewProvider>
        </AppStoreProvider>
      </WebSocketProvider>
    </BrowserRouter>
  )
}
