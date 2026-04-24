type Props = {
  connected: boolean
}

export default function TopBar({ connected }: Props) {
  return (
    <header className="topbar">
      <span className="topbar-title">HeartClaw Console</span>
      <div className="topbar-status">
        <span className={`topbar-dot${connected ? '' : ' disconnected'}`} />
        {connected ? 'connected' : 'disconnected'}
      </div>
    </header>
  )
}
