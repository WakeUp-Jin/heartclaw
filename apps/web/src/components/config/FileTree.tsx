import { RefreshCw } from 'lucide-react'
import FileTreeItem, { type TreeNode } from './FileTreeItem'

type Props = {
  tree: TreeNode | null
  selectedPath: string | null
  modifiedPaths: Set<string>
  onSelect: (path: string) => void
  onRefresh: () => void
  loading: boolean
}

export default function FileTree({
  tree,
  selectedPath,
  modifiedPaths,
  onSelect,
  onRefresh,
  loading,
}: Props) {
  return (
    <div className="file-tree-panel">
      <div className="file-tree-header">
        <span>文件</span>
        <div className="file-tree-header-actions">
          <button onClick={onRefresh} disabled={loading} title="刷新">
            <RefreshCw style={loading ? { animation: 'spin 1s linear infinite' } : undefined} />
          </button>
        </div>
      </div>
      <div className="file-tree-content">
        {tree ? (
          tree.children?.map((child) => (
            <FileTreeItem
              key={child.path}
              node={child}
              depth={0}
              selectedPath={selectedPath}
              modifiedPaths={modifiedPaths}
              onSelect={onSelect}
            />
          ))
        ) : (
          <div style={{ padding: '16px', color: 'var(--text-muted)', fontSize: 13 }}>
            {loading ? '加载中...' : '无法加载文件树'}
          </div>
        )}
      </div>
    </div>
  )
}
