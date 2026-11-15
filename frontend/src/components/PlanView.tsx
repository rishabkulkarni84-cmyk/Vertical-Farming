import clsx from 'clsx'
import { Maximize2, Minus, Plus } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as RPE } from 'react'
import { fmtLen } from '../lib/units'
import type { Obstacle, Rack, Unit } from '../lib/types'

export type Rect = { x: number; y: number; w: number; d: number }
export type PlanItem = { kind: 'obstacle' | 'rack'; id: string }

/** Mirrors backend geometry.door_access_zone so the editor previews what the server enforces. */
export function doorZone(o: Rect & { clearance_m: number }, L: number, W: number): Rect {
  const cx = o.x + o.w / 2, cy = o.y + o.d / 2
  const dist = { N: cy, S: W - cy, W: cx, E: L - cx }
  const wall = (Object.keys(dist) as (keyof typeof dist)[]).reduce((a, b) => (dist[a] <= dist[b] ? a : b))
  const c = o.clearance_m
  let z: Rect
  if (wall === 'N') z = { x: o.x, y: o.y, w: o.w, d: o.d + c }
  else if (wall === 'S') z = { x: o.x, y: o.y - c, w: o.w, d: o.d + c }
  else if (wall === 'W') z = { x: o.x, y: o.y, w: o.w + c, d: o.d }
  else z = { x: o.x - c, y: o.y, w: o.w + c, d: o.d }
  const x = Math.max(0, z.x), y = Math.max(0, z.y)
  return { x, y, w: Math.min(L, z.x + z.w) - x, d: Math.min(W, z.y + z.d) - y }
}

const OBS_LABEL: Record<string, string> = { DOOR: 'Door', WINDOW: 'Window', PILLAR: 'Pillar', FURNITURE: 'Furniture', EQUIPMENT: 'Equipment', FIXED: 'Fixed', RESTRICTED: 'Restricted' }

interface Props {
  length: number
  width: number
  unit: Unit
  obstacles?: Obstacle[]
  racks?: Rack[]
  aisles?: Rect[]
  gridCell?: number | null
  cellStates?: string[][] | null
  invalidRacks?: Set<string>
  selected?: PlanItem | null
  onSelect?: (item: PlanItem | null) => void
  editable?: 'obstacles' | 'racks' | null
  onMove?: (item: PlanItem, x: number, y: number) => void
  onDragEnd?: (item: PlanItem) => void
  height?: number
  showLayers?: Partial<Record<'grid' | 'zones' | 'aisles' | 'dims' | 'labels', boolean>>
}

const CELL_FILL: Record<string, string> = { OBSTACLE: '#3d4f45', DOOR_CLEARANCE: '#e6b860', WALKWAY: '#bfcfc3', RACK: '#285e47', RESTRICTED: '#a63d2a', UNCERTAIN: '#8a7ab0' }

export default function PlanView({ length: L, width: W, unit, obstacles = [], racks = [], aisles = [], gridCell, cellStates, invalidRacks, selected, onSelect,
  editable, onMove, onDragEnd, height = 460, showLayers = {} }: Props) {
  const layers = { grid: true, zones: true, aisles: true, dims: true, labels: true, ...showLayers }
  const pad = Math.max(L, W) * 0.12
  const fit = useMemo(() => ({ x: -pad, y: -pad, w: L + pad * 2, h: W + pad * 2 }), [L, W, pad])
  const [vb, setVb] = useState(fit)
  useEffect(() => setVb(fit), [fit])
  const svg = useRef<SVGSVGElement>(null)
  const drag = useRef<{ item?: PlanItem; dx: number; dy: number; pan?: { x: number; y: number; vb: typeof vb }; moved: boolean } | null>(null)
  const [panning, setPanning] = useState(false)
  const fs = Math.max(L, W) / 42

  const toWorld = useCallback((cx: number, cy: number) => {
    const s = svg.current
    if (!s) return { x: 0, y: 0 }
    const p = s.createSVGPoint()
    p.x = cx
    p.y = cy
    const r = p.matrixTransform(s.getScreenCTM()!.inverse())
    return { x: r.x, y: r.y }
  }, [])

  const zoom = (f: number, cx?: number, cy?: number) => {
    setVb((v) => {
      const nw = Math.min(fit.w * 3, Math.max(fit.w / 8, v.w * f))
      const k = nw / v.w
      const ax = cx ?? v.x + v.w / 2, ay = cy ?? v.y + v.h / 2
      return { x: ax - (ax - v.x) * k, y: ay - (ay - v.y) * k, w: nw, h: v.h * k }
    })
  }

  const zoomRef = useRef(zoom)
  useEffect(() => { zoomRef.current = zoom })
  useEffect(() => {
    const s = svg.current
    if (!s) return
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey && !e.shiftKey) return // plain scroll scrolls the page
      e.preventDefault()
      const w = toWorld(e.clientX, e.clientY)
      zoomRef.current(e.deltaY > 0 ? 1.12 : 1 / 1.12, w.x, w.y)
    }
    s.addEventListener('wheel', onWheel, { passive: false })
    return () => s.removeEventListener('wheel', onWheel)
  }, [toWorld])

  const startItem = (e: RPE, item: PlanItem, r: Rect) => {
    e.stopPropagation()
    onSelect?.(item)
    if (editable !== item.kind + 's' || !onMove) return
    const w = toWorld(e.clientX, e.clientY)
    ;(e.target as Element).setPointerCapture?.(e.pointerId)
    drag.current = { item, dx: w.x - r.x, dy: w.y - r.y, moved: false }
  }
  const startPan = (e: RPE) => {
    onSelect?.(null)
    drag.current = { dx: 0, dy: 0, pan: { x: e.clientX, y: e.clientY, vb }, moved: false }
    setPanning(true)
    ;(e.currentTarget as Element).setPointerCapture?.(e.pointerId)
  }
  const move = (e: RPE) => {
    const d = drag.current
    if (!d) return
    if (d.pan) {
      const s = svg.current!.getBoundingClientRect()
      const k = d.pan.vb.w / s.width
      setVb({ ...d.pan.vb, x: d.pan.vb.x - (e.clientX - d.pan.x) * k, y: d.pan.vb.y - (e.clientY - d.pan.y) * k })
      return
    }
    if (!d.item) return
    const w = toWorld(e.clientX, e.clientY)
    const snap = (v: number) => Math.round(v / 0.05) * 0.05
    d.moved = true
    onMove?.(d.item, Math.max(0, snap(w.x - d.dx)), Math.max(0, snap(w.y - d.dy)))
  }
  const end = () => {
    const d = drag.current
    drag.current = null
    setPanning(false)
    if (d?.item && d.moved) onDragEnd?.(d.item)
  }

  const dimLine = (x1: number, y1: number, x2: number, y2: number, text: string, vertical = false) => {
    const t = fs * 0.35
    return (
      <g className="text-ink-soft" stroke="currentColor" fill="currentColor">
        <line x1={x1} y1={y1} x2={x2} y2={y2} vectorEffect="non-scaling-stroke" strokeWidth={1} />
        {vertical ? <>
          <line x1={x1 - t} y1={y1} x2={x1 + t} y2={y1} vectorEffect="non-scaling-stroke" />
          <line x1={x2 - t} y1={y2} x2={x2 + t} y2={y2} vectorEffect="non-scaling-stroke" />
        </> : <>
          <line x1={x1} y1={y1 - t} x2={x1} y2={y1 + t} vectorEffect="non-scaling-stroke" />
          <line x1={x2} y1={y2 - t} x2={x2} y2={y2 + t} vectorEffect="non-scaling-stroke" />
        </>}
        <text stroke="none" fontSize={fs * 0.95} fontWeight={600} textAnchor="middle" dominantBaseline="central" className="font-sans"
          transform={vertical ? `translate(${x1 - fs * 0.9} ${(y1 + y2) / 2}) rotate(-90)` : `translate(${(x1 + x2) / 2} ${y1 - fs * 0.85})`}>{text}</text>
      </g>
    )
  }

  const isSel = (k: PlanItem['kind'], id: string) => selected?.kind === k && selected.id === id

  return (
    <div className="relative rounded-[10px] border border-line overflow-hidden plan-sheet select-none" style={{ height }}>
      <svg ref={svg} role="img" aria-label={`Top-down plan of a ${fmtLen(L, unit)} by ${fmtLen(W, unit)} room with ${racks.length} racks and ${obstacles.length} obstacles`}
        viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`} className={clsx('w-full h-full touch-none', panning ? 'cursor-grabbing' : 'cursor-grab')}
        onPointerDown={startPan} onPointerMove={move} onPointerUp={end} onPointerCancel={end}>
        <defs>
          <pattern id="hatch" patternUnits="userSpaceOnUse" width={fs * 0.6} height={fs * 0.6} patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2={fs * 0.6} stroke="#3d4f45" strokeWidth={fs * 0.12} />
          </pattern>
          <pattern id="hatch-crit" patternUnits="userSpaceOnUse" width={fs * 0.5} height={fs * 0.5} patternTransform="rotate(-45)">
            <line x1="0" y1="0" x2="0" y2={fs * 0.5} stroke="#a63d2a" strokeWidth={fs * 0.14} />
          </pattern>
        </defs>

        {/* floor */}
        <rect x={0} y={0} width={L} height={W} fill="#ffffff" />

        {/* grid cell states (optional overlay) */}
        {cellStates && gridCell && cellStates.map((row, r) => row.map((s, c) => s !== 'FREE' && (
          <rect key={`${r}-${c}`} x={c * gridCell} y={r * gridCell} width={gridCell} height={gridCell} fill={CELL_FILL[s]} opacity={s === 'RACK' ? 0.35 : 0.28} />
        )))}

        {layers.grid && gridCell && gridCell > 0 && (
          <g stroke="#c4cfc6" strokeWidth={0.6} vectorEffect="non-scaling-stroke">
            {Array.from({ length: Math.floor(L / gridCell + 1e-9) + 1 }, (_, i) => <line key={`v${i}`} x1={i * gridCell} y1={0} x2={i * gridCell} y2={W} vectorEffect="non-scaling-stroke" />)}
            {Array.from({ length: Math.floor(W / gridCell + 1e-9) + 1 }, (_, i) => <line key={`h${i}`} x1={0} y1={i * gridCell} x2={L} y2={i * gridCell} vectorEffect="non-scaling-stroke" />)}
          </g>
        )}

        {/* walkways */}
        {layers.aisles && aisles.map((a, i) => (
          <rect key={i} x={a.x} y={a.y} width={a.w} height={a.d} fill="#dce5dd" fillOpacity={0.55} stroke="#8da594" strokeDasharray="4 3" vectorEffect="non-scaling-stroke" />
        ))}

        {/* obstacles */}
        {obstacles.map((o) => {
          const id = String(o.id)
          const sel = isSel('obstacle', id)
          const common = { onPointerDown: (e: RPE) => startItem(e, { kind: 'obstacle', id }, o), style: { cursor: editable === 'obstacles' ? 'move' : 'pointer' } }
          if (o.kind === 'DOOR') {
            const z = doorZone(o, L, W)
            const r = Math.min(o.w, o.clearance_m || o.w)
            const horiz = o.w >= o.d
            return (
              <g key={id} {...common} aria-label={o.label ?? 'Door'}>
                {layers.zones && <rect x={z.x} y={z.y} width={z.w} height={z.d} fill="#e6b860" fillOpacity={0.22} stroke="#a86b12" strokeDasharray="5 3" vectorEffect="non-scaling-stroke" />}
                <rect x={o.x} y={o.y} width={o.w} height={o.d} fill="#fff" stroke="#a86b12" strokeWidth={sel ? 3 : 2} vectorEffect="non-scaling-stroke" />
                {horiz
                  ? <path d={`M ${o.x} ${z.y === o.y ? o.y + o.d : o.y} q 0 ${(z.y === o.y ? 1 : -1) * r} ${r} ${(z.y === o.y ? 1 : -1) * r}`} fill="none" stroke="#a86b12" strokeWidth={1} vectorEffect="non-scaling-stroke" />
                  : <path d={`M ${z.x === o.x ? o.x + o.w : o.x} ${o.y} q ${(z.x === o.x ? 1 : -1) * r} 0 ${(z.x === o.x ? 1 : -1) * r} ${r}`} fill="none" stroke="#a86b12" strokeWidth={1} vectorEffect="non-scaling-stroke" />}
                {layers.labels && <text x={z.x + z.w / 2} y={z.y + z.d / 2} fontSize={fs * 0.85} textAnchor="middle" dominantBaseline="central" fill="#7a4f0e" className="font-sans pointer-events-none">{o.label || 'Door'} access</text>}
              </g>
            )
          }
          if (o.kind === 'WINDOW') {
            return (
              <g key={id} {...common}>
                <rect x={o.x} y={o.y} width={o.w} height={o.d} fill="#e4eef6" stroke="#2f5f86" strokeWidth={sel ? 3 : 1.5} vectorEffect="non-scaling-stroke" />
                {layers.labels && <text x={o.x + o.w / 2 + (o.x > L / 2 ? -fs : fs)} y={o.y + o.d / 2} fontSize={fs * 0.8} textAnchor="middle" dominantBaseline="central" fill="#2f5f86" className="font-sans pointer-events-none"
                  transform={o.d > o.w ? `rotate(-90 ${o.x + o.w / 2 + (o.x > L / 2 ? -fs : fs)} ${o.y + o.d / 2})` : undefined}>{o.label || 'Window'}</text>}
              </g>
            )
          }
          const restricted = o.kind === 'RESTRICTED'
          return (
            <g key={id} {...common}>
              <rect x={o.x} y={o.y} width={o.w} height={o.d} fill={restricted ? 'url(#hatch-crit)' : 'url(#hatch)'} fillOpacity={o.confirmed ? 0.9 : 0.4}
                stroke={sel ? '#13221b' : restricted ? '#a63d2a' : '#3d4f45'} strokeWidth={sel ? 2.5 : 1.25} strokeDasharray={o.confirmed ? undefined : '3 2'} vectorEffect="non-scaling-stroke" />
              {layers.labels && Math.min(o.w, o.d) > fs * 0.9 && (
                <text x={o.x + o.w / 2} y={o.y + o.d / 2} fontSize={fs * 0.8} textAnchor="middle" dominantBaseline="central" className="font-sans pointer-events-none" fill="#13221b"
                  paintOrder="stroke" stroke="#fff" strokeWidth={fs * 0.25}>{o.label || OBS_LABEL[o.kind]}</text>
              )}
            </g>
          )
        })}

        {/* racks */}
        {racks.map((r) => {
          const bad = invalidRacks?.has(r.label)
          const sel = isSel('rack', r.label)
          return (
            <g key={r.label} onPointerDown={(e) => startItem(e, { kind: 'rack', id: r.label }, r)} style={{ cursor: editable === 'racks' ? 'move' : 'pointer' }}
              role="button" aria-label={`Rack ${r.label}${bad ? ', invalid' : ''}`}>
              <rect x={r.x} y={r.y} width={r.w} height={r.d} rx={0.02} fill={bad ? '#f8e5e0' : '#285e47'} stroke={bad ? '#a63d2a' : sel ? '#13221b' : '#163a2b'} strokeWidth={sel ? 3 : 1.5} vectorEffect="non-scaling-stroke" />
              {bad && <rect x={r.x} y={r.y} width={r.w} height={r.d} fill="url(#hatch-crit)" opacity={0.5} pointerEvents="none" />}
              {/* shelf slats */}
              {!bad && Array.from({ length: 3 }, (_, i) => r.w >= r.d
                ? <line key={i} x1={r.x + (r.w * (i + 1)) / 4} y1={r.y} x2={r.x + (r.w * (i + 1)) / 4} y2={r.y + r.d} stroke="#34735a" vectorEffect="non-scaling-stroke" pointerEvents="none" />
                : <line key={i} x1={r.x} y1={r.y + (r.d * (i + 1)) / 4} x2={r.x + r.w} y2={r.y + (r.d * (i + 1)) / 4} stroke="#34735a" vectorEffect="non-scaling-stroke" pointerEvents="none" />)}
              {layers.labels && <text x={r.x + r.w / 2} y={r.y + r.d / 2} fontSize={fs * 0.95} fontWeight={700} textAnchor="middle" dominantBaseline="central" fill={bad ? '#a63d2a' : '#fff'}
                paintOrder="stroke" stroke={bad ? '#fff' : '#285e47'} strokeWidth={fs * 0.3} className="font-sans pointer-events-none">{bad ? `${r.label} ✕` : r.label}</text>}
            </g>
          )
        })}

        {/* walls */}
        <rect x={0} y={0} width={L} height={W} fill="none" stroke="#13221b" strokeWidth={3} vectorEffect="non-scaling-stroke" pointerEvents="none" />

        {layers.dims && <>
          {dimLine(0, -pad * 0.45, L, -pad * 0.45, fmtLen(L, unit))}
          {dimLine(-pad * 0.45, 0, -pad * 0.45, W, fmtLen(W, unit), true)}
          <g fill="#66766c" fontSize={fs * 0.7} className="font-sans">
            <circle cx={0} cy={0} r={fs * 0.18} fill="#13221b" />
            <text x={fs * 0.3} y={W + fs * 1.1}>origin (0,0) top-left · +x along length · +y along width</text>
          </g>
        </>}
      </svg>

      <div className="absolute top-3 right-3 flex flex-col rounded-md border border-line bg-surface shadow-sm overflow-hidden">
        <button onClick={() => zoom(1 / 1.25)} className="p-2 hover:bg-sage-50" aria-label="Zoom in"><Plus className="size-4" /></button>
        <button onClick={() => zoom(1.25)} className="p-2 hover:bg-sage-50 border-y border-line" aria-label="Zoom out"><Minus className="size-4" /></button>
        <button onClick={() => setVb(fit)} className="p-2 hover:bg-sage-50" aria-label="Fit plan to view"><Maximize2 className="size-4" /></button>
      </div>
      <div className="absolute bottom-2 right-3 text-[11px] text-muted bg-surface/80 rounded px-1.5">Drag to pan · Ctrl/⌘ + scroll to zoom</div>
    </div>
  )
}

export function PlanLegend({ items }: { items: ('rack' | 'invalid' | 'walkway' | 'door' | 'obstacle' | 'restricted' | 'window' | 'uncertain')[] }) {
  const map = {
    rack: { sw: <span className="size-3 rounded-[2px] bg-forest-700 inline-block" />, label: 'Rack footprint' },
    invalid: { sw: <span className="size-3 rounded-[2px] bg-crit-soft border border-crit inline-block" />, label: 'Invalid rack (✕)' },
    walkway: { sw: <span className="size-3 rounded-[2px] bg-sage-200 border border-dashed border-sage-500 inline-block" />, label: 'Walkway / access aisle' },
    door: { sw: <span className="size-3 rounded-[2px] bg-[#e6b860]/40 border border-dashed border-warn inline-block" />, label: 'Door access zone' },
    obstacle: { sw: <span className="size-3 rounded-[2px] inline-block border border-ink-soft" style={{ background: 'repeating-linear-gradient(45deg,#3d4f45 0 1.5px,transparent 1.5px 4px)' }} />, label: 'Blocked (obstacle)' },
    restricted: { sw: <span className="size-3 rounded-[2px] inline-block border border-crit" style={{ background: 'repeating-linear-gradient(-45deg,#a63d2a 0 1.5px,transparent 1.5px 4px)' }} />, label: 'Restricted zone' },
    window: { sw: <span className="size-3 rounded-[2px] bg-info-soft border border-info inline-block" />, label: 'Window (warning only)' },
    uncertain: { sw: <span className="size-3 rounded-[2px] border border-dashed border-ink-soft inline-block" />, label: 'Unconfirmed obstacle' },
  }
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-[12.5px] text-ink-soft mt-3" aria-label="Plan legend">
      {items.map((k) => <li key={k} className="flex items-center gap-1.5">{map[k].sw}{map[k].label}</li>)}
    </ul>
  )
}
