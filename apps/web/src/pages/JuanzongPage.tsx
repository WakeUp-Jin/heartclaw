import { useState, useEffect, useCallback } from 'react'
import { File, X } from 'lucide-react'
import FileTree from '../components/config/FileTree'
import CodeEditor from '../components/config/CodeEditor'
import SaveBar from '../components/config/SaveBar'
import type { TreeNode } from '../components/config/FileTreeItem'

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL as string) || ''

export default function JuanzongPage() {
  const [tree, setTree] = useState<TreeNode | null>(null)
  const [treeLoading, setTreeLoading] = useState(false)
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [originalContent, setOriginalContent] = useState('')
  const [content, setContent] = useState('')
  const [saving, setSaving] = useState(false)
  const [modifiedPaths, setModifiedPaths] = useState<Set<string>>(new Set())

  const modified = content !== originalContent

  const loadTree = useCallback(async () => {
    setTreeLoading(true)
    try {
      const resp = await fetch(`${apiBaseUrl}/api/juanzong/tree`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      setTree(data as TreeNode)
    } catch {
      setTree(null)
    } finally {
      setTreeLoading(false)
    }
  }, [])

  useEffect(() => {
    loadTree()
  }, [loadTree])

  async function loadFile(path: string) {
    try {
      const resp = await fetch(`${apiBaseUrl}/api/juanzong/file?path=${encodeURIComponent(path)}`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = (await resp.json()) as { content: string }
      setOriginalContent(data.content)
      setContent(data.content)
      setSelectedPath(path)
    } catch {
      setOriginalContent('')
      setContent('')
    }
  }

  function handleSelect(path: string) {
    loadFile(path)
  }

  async function handleSave() {
    if (!selectedPath || !modified) return
    setSaving(true)
    try {
      const resp = await fetch(`${apiBaseUrl}/api/juanzong/file`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: selectedPath, content }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      setOriginalContent(content)
      setModifiedPaths((prev) => {
        const next = new Set(prev)
        next.delete(selectedPath!)
        return next
      })
    } finally {
      setSaving(false)
    }
  }

  function handleDiscard() {
    setContent(originalContent)
    if (selectedPath) {
      setModifiedPaths((prev) => {
        const next = new Set(prev)
        next.delete(selectedPath!)
        return next
      })
    }
  }

  function handleContentChange(value: string) {
    setContent(value)
    if (selectedPath) {
      setModifiedPaths((prev) => {
        const next = new Set(prev)
        if (value !== originalContent) {
          next.add(selectedPath!)
        } else {
          next.delete(selectedPath!)
        }
        return next
      })
    }
  }

  const fileName = selectedPath?.split('/').pop()

  return (
    <div className="juanzong-page">
      <div className="juanzong-header">
        <h1>卷宗</h1>
        <p>配置与策略管理，集中维护 HeartClaw 的运行规则与行为。</p>
      </div>
      <div className="juanzong-body">
        <FileTree
          tree={tree}
          selectedPath={selectedPath}
          modifiedPaths={modifiedPaths}
          onSelect={handleSelect}
          onRefresh={loadTree}
          loading={treeLoading}
        />
        <div className="editor-panel">
          {selectedPath ? (
            <>
              <div className="editor-tabs">
                <div className="editor-tab active">
                  <File style={{ width: 13, height: 13 }} />
                  {fileName}
                  <button
                    className="editor-tab-close"
                    onClick={() => {
                      setSelectedPath(null)
                      setContent('')
                      setOriginalContent('')
                    }}
                  >
                    <X style={{ width: 12, height: 12 }} />
                  </button>
                </div>
              </div>
              <div className="editor-area">
                <CodeEditor
                  content={content}
                  onChange={handleContentChange}
                />
              </div>
              <SaveBar
                modified={modified}
                saving={saving}
                onSave={handleSave}
                onDiscard={handleDiscard}
              />
            </>
          ) : (
            <div className="editor-placeholder">
              选择一个文件开始编辑
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
