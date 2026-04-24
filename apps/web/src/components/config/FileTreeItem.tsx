import { useState } from 'react'
import { ChevronRight, File, Folder, FolderOpen } from 'lucide-react'

export type TreeNode = {
  name: string
  type: 'file' | 'directory'
  path: string
  children?: TreeNode[]
}

type Props = {
  node: TreeNode
  depth: number
  selectedPath: string | null
  modifiedPaths: Set<string>
  onSelect: (path: string) => void
}

export default function FileTreeItem({
  node,
  depth,
  selectedPath,
  modifiedPaths,
  onSelect,
}: Props) {
  const [expanded, setExpanded] = useState(depth < 2)
  const isDir = node.type === 'directory'
  const isActive = node.path === selectedPath
  const isModified = modifiedPaths.has(node.path)

  function handleClick() {
    if (isDir) {
      setExpanded(!expanded)
    } else {
      onSelect(node.path)
    }
  }

  return (
    <>
      <div
        className={`file-tree-item${isActive ? ' active' : ''}${isModified ? ' modified' : ''}`}
        onClick={handleClick}
        style={{ paddingLeft: `${14 + depth * 16}px` }}
      >
        {isDir ? (
          <>
            <ChevronRight
              style={{
                width: 12,
                height: 12,
                transform: expanded ? 'rotate(90deg)' : 'none',
                transition: 'transform 150ms',
              }}
            />
            {expanded ? <FolderOpen /> : <Folder />}
          </>
        ) : (
          <>
            <span className="file-tree-indent" />
            <File />
          </>
        )}
        <span>{node.name}</span>
      </div>
      {isDir && expanded && node.children && (
        <>
          {node.children.map((child) => (
            <FileTreeItem
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedPath={selectedPath}
              modifiedPaths={modifiedPaths}
              onSelect={onSelect}
            />
          ))}
        </>
      )}
    </>
  )
}
