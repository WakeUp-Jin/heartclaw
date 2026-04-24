type Props = {
  lines: string[]
}

export default function ToolResultBlock({ lines }: Props) {
  return (
    <pre className="tool-result-preview">
      {lines.map((line, i) => (
        <div key={i}>{line}</div>
      ))}
    </pre>
  )
}
