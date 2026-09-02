import { useMemo, useRef, useState } from 'react'
import type { KeyboardEvent, PointerEvent, WheelEvent } from 'react'
import type { Edge, FileNode } from '../types'

const VIEWBOX_WIDTH = 800
const VIEWBOX_HEIGHT = 620
const MIN_ZOOM = 0.55
const MAX_ZOOM = 4

type Viewport = { x: number; y: number; scale: number }
const INITIAL_VIEWPORT: Viewport = { x: 0, y: 0, scale: 1 }

type NodeKind = 'python' | 'javascript' | 'typescript' | 'other'

const NODE_LABELS: Record<NodeKind, string> = {
  python: 'Python',
  javascript: 'JavaScript',
  typescript: 'TypeScript',
  other: 'Other',
}

function nodeKind(language: string): NodeKind {
  if (language === 'python' || language === 'javascript' || language === 'typescript') return language
  return 'other'
}

type Props = {
  files: FileNode[]
  edges: Edge[]
  selected: string | null
  onSelect: (path: string) => void
}

export function DependencyGraph({ files, edges, selected, onSelect }: Props) {
  const svgRef = useRef<SVGSVGElement>(null)
  const dragRef = useRef<{ pointerId: number; x: number; y: number } | null>(null)
  const [viewport, setViewport] = useState<Viewport>(INITIAL_VIEWPORT)
  const [panning, setPanning] = useState(false)
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
  const legend = (Object.keys(NODE_LABELS) as NodeKind[])
    .map((kind) => ({ kind, label: NODE_LABELS[kind], count: visible.filter((file) => nodeKind(file.language) === kind).length }))
    .filter((item) => item.count > 0)
  const cycleCount = visible.filter((file) => file.metrics.cycle_participation > 0).length

  const zoomAt = (factor: number, anchorX = VIEWBOX_WIDTH / 2, anchorY = VIEWBOX_HEIGHT / 2) => {
    setViewport((current) => {
      const scale = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, current.scale * factor))
      if (scale === current.scale) return current
      const worldX = (anchorX - current.x) / current.scale
      const worldY = (anchorY - current.y) / current.scale
      return {
        x: anchorX - worldX * scale,
        y: anchorY - worldY * scale,
        scale,
      }
    })
  }

  const handleWheel = (event: WheelEvent<SVGSVGElement>) => {
    event.preventDefault()
    const bounds = svgRef.current?.getBoundingClientRect()
    if (!bounds) return
    const ratioX = VIEWBOX_WIDTH / bounds.width
    const ratioY = VIEWBOX_HEIGHT / bounds.height
    if (event.ctrlKey) {
      const anchorX = (event.clientX - bounds.left) * ratioX
      const anchorY = (event.clientY - bounds.top) * ratioY
      zoomAt(Math.exp(-event.deltaY * 0.012), anchorX, anchorY)
      return
    }
    setViewport((current) => ({
      ...current,
      x: current.x - event.deltaX * ratioX,
      y: current.y - event.deltaY * ratioY,
    }))
  }

  const handlePointerDown = (event: PointerEvent<SVGSVGElement>) => {
    if ((event.target as Element).closest('.graph-node')) return
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY }
    setPanning(true)
  }

  const handlePointerMove = (event: PointerEvent<SVGSVGElement>) => {
    const drag = dragRef.current
    const bounds = svgRef.current?.getBoundingClientRect()
    if (!drag || drag.pointerId !== event.pointerId || !bounds) return
    const deltaX = (event.clientX - drag.x) * (VIEWBOX_WIDTH / bounds.width)
    const deltaY = (event.clientY - drag.y) * (VIEWBOX_HEIGHT / bounds.height)
    dragRef.current = { ...drag, x: event.clientX, y: event.clientY }
    setViewport((current) => ({ ...current, x: current.x + deltaX, y: current.y + deltaY }))
  }

  const endPan = (event: PointerEvent<SVGSVGElement>) => {
    if (dragRef.current?.pointerId !== event.pointerId) return
    dragRef.current = null
    setPanning(false)
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  }

  if (!visible.length) return <div className="empty-state">No source files were discovered.</div>
  return (
    <div className="graph-wrap" role="group" aria-label={`Dependency graph with ${visible.length} files`}>
      <div className="graph-toolbar">
        <div className="graph-legend" aria-label="Graph color index">
          <span className="graph-legend-title">Color index</span>
          {legend.map((item) => (
            <span className="graph-legend-item" key={item.kind}>
              <span className={`graph-swatch ${item.kind}`} aria-hidden="true" />
              {item.label}
              <strong>{item.count}</strong>
            </span>
          ))}
          {cycleCount > 0 && (
            <span className="graph-legend-item">
              <span className="graph-swatch cycle" aria-hidden="true" />
              In cycle
              <strong>{cycleCount}</strong>
            </span>
          )}
          <span className="graph-legend-item">
            <span className="graph-swatch selected" aria-hidden="true" />
            Selected
          </span>
        </div>
        <div className="graph-navigation">
          <span className="graph-gesture-hint">Pinch to zoom · scroll or drag to pan</span>
          <div className="graph-zoom-controls" aria-label="Graph zoom controls">
            <button type="button" onClick={() => zoomAt(0.8)} aria-label="Zoom out">−</button>
            <output aria-live="polite" aria-label="Current zoom">{Math.round(viewport.scale * 100)}%</output>
            <button type="button" onClick={() => zoomAt(1.25)} aria-label="Zoom in">+</button>
            <button type="button" className="reset" onClick={() => setViewport(INITIAL_VIEWPORT)} disabled={viewport.x === 0 && viewport.y === 0 && viewport.scale === 1}>Reset</button>
          </div>
        </div>
      </div>
      <svg
        ref={svgRef}
        className={`graph-canvas${panning ? ' panning' : ''}`}
        viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
        onWheel={handleWheel}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={endPan}
        onPointerCancel={endPan}
        aria-label="Interactive dependency map. Pinch to zoom and use two-finger scrolling or drag to pan."
      >
        <defs>
          <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" /></marker>
          <marker id="arrow-active" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" /></marker>
        </defs>
        <g transform={`translate(${viewport.x} ${viewport.y}) scale(${viewport.scale})`}>
          <g className="edges">
            {visibleEdges.map((edge) => {
              const source = positions.get(edge.source)!
              const target = positions.get(edge.target)!
              const active = selected === edge.source || selected === edge.target
              return <line key={`${edge.source}:${edge.line}:${edge.target}`} x1={source.x} y1={source.y} x2={target.x} y2={target.y} className={active ? 'active' : ''} markerEnd={active ? 'url(#arrow-active)' : 'url(#arrow)'} />
            })}
          </g>
          <g>
            {visible.map((file) => {
              const point = positions.get(file.path)!
              const active = selected === file.path
              const risky = file.metrics.cycle_participation > 0
              const kind = nodeKind(file.language)
              const selectFromKeyboard = (event: KeyboardEvent<SVGGElement>) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  onSelect(file.path)
                }
              }
              return (
                <g key={file.path} className="graph-node" onClick={() => onSelect(file.path)} role="button" tabIndex={0} onKeyDown={selectFromKeyboard} aria-label={`${file.path}, ${NODE_LABELS[kind]}${risky ? ', participates in a cycle' : ''}`}>
                  <circle cx={point.x} cy={point.y} r={active ? 9 : 6} className={`${kind} ${active ? 'active' : ''} ${risky ? 'risky' : ''}`} />
                  <text x={point.x + 10} y={point.y + 4}>{file.path.split('/').pop()}</text>
                </g>
              )
            })}
          </g>
        </g>
      </svg>
      {files.length > visible.length && <p className="graph-note">Showing the 80 most relevant files. Use the Files table for the complete repository.</p>}
    </div>
  )
}
