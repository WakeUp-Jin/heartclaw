import { NavLink } from 'react-router-dom'
import { MessageCircle, Terminal, FolderOpen, Settings, Zap } from 'lucide-react'

const navItems = [
  { to: '/ruyi', label: '如意', icon: MessageCircle },
  { to: '/tiangong', label: '天工', icon: Terminal },
  { to: '/juanzong', label: '卷宗', icon: FolderOpen },
]

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <Zap />
      </div>
      <nav className="sidebar-nav">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `sidebar-link${isActive ? ' active' : ''}`
            }
          >
            <item.icon />
            {item.label}
          </NavLink>
        ))}
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
