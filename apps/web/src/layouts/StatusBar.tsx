type Props = {
  wsStatus: string
  ruyiStatus: string
  tiangongStatus: string
}

export default function StatusBar({ wsStatus, ruyiStatus, tiangongStatus }: Props) {
  return (
    <footer className="statusbar">
      <span className="statusbar-item">ws: {wsStatus}</span>
      <span className="statusbar-sep">|</span>
      <span className="statusbar-item">如意: {ruyiStatus}</span>
      <span className="statusbar-sep">|</span>
      <span className="statusbar-item">天工: {tiangongStatus}</span>
    </footer>
  )
}
