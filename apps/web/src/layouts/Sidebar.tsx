import { NavLink } from 'react-router-dom'
import { MessageCircle, Terminal, FolderOpen, Radar, Settings, Zap } from 'lucide-react'
import { useSplitView, type PageId } from '../stores/useSplitView'

const navItems: { to: string; id: PageId; label: string; icon: typeof MessageCircle }[] = [
  { to: '/ruyi', id: 'ruyi', label: '如意', icon: MessageCircle },
  { to: '/tiangong', id: 'tiangong', label: '天工', icon: Terminal },
  { to: '/juanzong', id: 'juanzong', label: '卷宗', icon: FolderOpen },
  { to: '/kairos', id: 'kairos', label: 'Kairos', icon: Radar },
]

export default function Sidebar() {
  const { rightPanel } = useSplitView()

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <Zap />
      </div>
      <nav className="sidebar-nav">
        {navItems.map((item) => {
          const isSplitActive = rightPanel === item.id
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => {
                let cls = 'sidebar-link'
                if (isActive) cls += ' active'
                if (isSplitActive) cls += ' split-active'
                return cls
              }}
            >
              <item.icon />
              {item.label}
            </NavLink>
          )
        })}
      </nav>
      <div className="sidebar-bottom">
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            `sidebar-link${isActive ? ' active' : ''}`
          }
        >
          <Settings />
          设置
        </NavLink>
      </div>
    </aside>
  )
}
