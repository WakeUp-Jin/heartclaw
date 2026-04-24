import { useRef, useEffect, useCallback } from 'react'

type Props = {
  content: string
  onChange: (value: string) => void
  readOnly?: boolean
}

export default function CodeEditor({ content, onChange, readOnly }: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const lineNumbersRef = useRef<HTMLDivElement>(null)

  const lines = content.split('\n')

  const syncScroll = useCallback(() => {
    if (textareaRef.current && lineNumbersRef.current) {
      lineNumbersRef.current.scrollTop = textareaRef.current.scrollTop
    }
  }, [])

  useEffect(() => {
    const el = textareaRef.current
    if (el) {
      el.addEventListener('scroll', syncScroll)
      return () => el.removeEventListener('scroll', syncScroll)
    }
  }, [syncScroll])

  return (
    <div className="code-editor">
      <div className="code-line-numbers" ref={lineNumbersRef}>
        {lines.map((_, i) => (
          <div key={i}>{i + 1}</div>
        ))}
      </div>
      <textarea
        ref={textareaRef}
        className="code-textarea"
        value={content}
        onChange={(e) => onChange(e.target.value)}
        readOnly={readOnly}
        spellCheck={false}
      />
    </div>
  )
}
