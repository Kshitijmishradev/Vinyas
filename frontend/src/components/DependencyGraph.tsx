import { useMemo } from 'react'
import type { Edge, FileNode } from '../types'

type Props = {
  files: FileNode[]
  edges: Edge[]
  selected: string | null
  onSelect: (path: string) => void
}

export function DependencyGraph({ files, edges, selected, onSelect }: Props) {
  const visible = files.slice(0, 80)
  const positions = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>()
    visible.forEach((file, index) => {
      const angle = (Math.PI * 2 * index) / Math.max(visible.length, 1)
      const ring = 190 + (index % 3) * 54
      map.set(file.path, { x: 400 + Math.cos(angle) * ring, y: 310 + Math.sin(angle) * ring })
    })
    return map
  }, [visible])
  const visibleEdges = edges.filter((edge) => positions.has(edge.source) && positions.has(edge.target)).slice(0, 240)

  if (!visible.length) return <div className="empty-state">No source files were discovered.</div>
  return (
    <div className="graph-wrap" role="img" aria-label={`Dependency graph with ${visible.length} files`}>
      <svg viewBox="0 0 800 620">
        <defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" /></marker></defs>
        <g className="edges">
          {visibleEdges.map((edge) => {
            const source = positions.get(edge.source)!
            const target = positions.get(edge.target)!
            const active = selected === edge.source || selected === edge.target
            return <line key={`${edge.source}:${edge.line}:${edge.target}`} x1={source.x} y1={source.y} x2={target.x} y2={target.y} className={active ? 'active' : ''} markerEnd="url(#arrow)" />
          })}
        </g>
        <g>
          {visible.map((file) => {
            const point = positions.get(file.path)!
            const active = selected === file.path
            const risky = file.metrics.cycle_participation > 0
            return (
              <g key={file.path} className="graph-node" onClick={() => onSelect(file.path)} role="button" tabIndex={0} onKeyDown={(event) => event.key === 'Enter' && onSelect(file.path)}>
                <circle cx={point.x} cy={point.y} r={active ? 9 : 6} className={`${active ? 'active' : ''} ${risky ? 'risky' : ''}`} />
                <text x={point.x + 10} y={point.y + 4}>{file.path.split('/').pop()}</text>
              </g>
            )
          })}
        </g>
      </svg>
      {files.length > visible.length && <p className="graph-note">Showing the 80 most relevant files. Use the Files table for the complete repository.</p>}
    </div>
  )
}
