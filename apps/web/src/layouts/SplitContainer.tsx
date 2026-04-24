import { Outlet, useLocation } from 'react-router-dom'
import { X } from 'lucide-react'
import { useSplitView, ALL_PAGES, type PageId } from '../stores/useSplitView'
import PageRenderer from './PageRenderer'

export default function SplitContainer() {
  const { rightPanel, splitRatio, setRightPanel } = useSplitView()
  const location = useLocation()
  const activeRoute = location.pathname.split('/')[1] || ''
  const isSplit = rightPanel !== null

  const availableTabs = ALL_PAGES.filter((p) => p.id !== activeRoute)

  return (
    <div className="split-container">
      <div
        className="split-left"
        style={isSplit ? { flex: `0 0 ${splitRatio * 100}%` } : undefined}
      >
        <Outlet />
      </div>

      {isSplit && <div className="split-divider" />}

      {isSplit && (
        <div className="split-right">
          <div className="split-right-header">
            <div className="split-tab-bar">
              {availableTabs.map((tab) => (
                <button
                  key={tab.id}
                  className={`split-tab${rightPanel === tab.id ? ' split-tab-active' : ''}`}
                  onClick={() => setRightPanel(tab.id as PageId)}
                >
                  {tab.label}
                </button>
              ))}
            </div>
            <button
              className="split-close-btn"
              onClick={() => setRightPanel(null)}
              title="关闭分屏"
            >
              <X size={14} />
            </button>
          </div>
          <div className="split-right-content">
            <PageRenderer pageId={rightPanel!} />
          </div>
        </div>
      )}
    </div>
  )
}
