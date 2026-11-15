import { useQuery } from '@tanstack/react-query'
import { lazy, Suspense, useState } from 'react'
import FarmGate, { FarmCrumb } from '../components/FarmGate'
import PlanView, { PlanLegend } from '../components/PlanView'
import type { Geometry, Layers } from '../components/Scene3D'
import { Badge, Callout, ErrorState, KV, PageHeader, Panel, Segmented, Spinner } from '../components/ui'
import { get } from '../lib/api'
import { useDisplayUnit } from '../lib/hooks'
import { fmtLen, fmtNum } from '../lib/units'
import type { Farm, Obstacle } from '../lib/types'

const Scene3D = lazy(() => import('../components/Scene3D'))

function supportsWebGL() {
  try {
    const c = document.createElement('canvas')
    return !!(c.getContext('webgl2') || c.getContext('webgl'))
  } catch { return false }
}

function View({ farm }: { farm: Farm }) {
  const unit = useDisplayUnit()
  const [mode, setMode] = useState<'2d' | '3d'>('3d')
  const [layers, setLayers] = useState<Layers>({ walls: true, plants: true, lights: true, obstacles: true, aisles: true, dims: true })
  const [l2, setL2] = useState({ grid: true, zones: true, aisles: true, dims: true, labels: true })
  const { data: geo, isLoading, error, refetch } = useQuery({ queryKey: ['geometry', farm.active_design_id], queryFn: () => get<Geometry & { obstacles: (Obstacle & { render_height: number })[] }>(`/designs/${farm.active_design_id}/geometry`) })
  const webgl = supportsWebGL()
  if (isLoading) return <Spinner label="Loading geometry" />
  if (error || !geo) return <ErrorState error={error} retry={refetch} />
  const toggles = mode === '3d'
    ? (Object.keys(layers) as (keyof Layers)[]).map((k) => ({ k, on: layers[k], set: () => setLayers({ ...layers, [k]: !layers[k] }) }))
    : (Object.keys(l2) as (keyof typeof l2)[]).map((k) => ({ k, on: l2[k], set: () => setL2({ ...l2, [k]: !l2[k] }) }))
  const names: Record<string, string> = { walls: 'Walls', plants: 'Plants', lights: 'Lights', obstacles: 'Obstacles', aisles: 'Walkways & door zone', dims: 'Dimensions', grid: 'Grid', zones: 'Door zones', labels: 'Labels' }
  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_300px]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-3 mb-3">
          <Segmented label="View" value={mode} onChange={setMode} options={[{ value: '2d', label: '2D plan' }, { value: '3d', label: '3D model' }]} />
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Visible layers">
            {toggles.map((t) => (
              <button key={t.k} aria-pressed={t.on} onClick={t.set} className={`h-8 px-2.5 rounded-md border text-[12.5px] ${t.on ? 'bg-sage-100 border-sage-300 text-forest-800 font-medium' : 'border-line text-muted line-through'}`}>{names[t.k]}</button>
            ))}
          </div>
        </div>
        {mode === '2d' ? (
          <>
            <PlanView length={geo.room.length} width={geo.room.width} unit={unit} obstacles={geo.obstacles} racks={geo.racks.map((r) => ({ ...r, rotation: r.w >= r.d ? 0 : 90 }))}
              aisles={geo.aisles} gridCell={farm.room!.grid_cell_m} height={560} showLayers={l2} />
            <PlanLegend items={['rack', 'walkway', 'door', 'obstacle', 'restricted', 'window']} />
          </>
        ) : !webgl ? (
          <Callout tone="warn" title="3D needs WebGL">Your browser or device has WebGL turned off. The 2D plan shows the same stored geometry.</Callout>
        ) : (
          <div className="h-[560px] rounded-[10px] border border-line overflow-hidden bg-[#eef2ee]">
            <Suspense fallback={<Spinner label="Building 3D model" />}><Scene3D geo={geo} layers={layers} unit={unit} /></Suspense>
          </div>
        )}
        {mode === '3d' && <p className="text-[12.5px] text-muted mt-2">Drag to orbit · right-drag or two fingers to pan · scroll to zoom.</p>}
      </div>
      <div className="space-y-4">
        <Panel title="Planning model" description={geo.model_note}>
          <KV items={[
            ['Room', `${fmtLen(geo.room.length, unit)} × ${fmtLen(geo.room.width, unit)} × ${fmtLen(geo.room.height, unit)}`],
            ['Racks', geo.racks.length],
            ['Levels per rack', geo.racks[0]?.levels.length ?? '—'],
            ['Rack height', geo.racks[0] ? fmtLen(geo.racks[0].height, unit) : '—'],
            ['Plants per level', fmtNum(geo.planting.plants_per_level)],
            ['Crop', geo.planting.crop ?? 'Not chosen'],
            ['Layout', geo.validation.valid ? <Badge tone="good">Valid</Badge> : <Badge tone="crit">Has violations</Badge>],
          ]} />
        </Panel>
        {!geo.planting.plants_per_level && <Callout tone="info">Plant placeholders appear once a crop (or plant spacing) is set for the design.</Callout>}
        <Callout tone="neutral" title="Not a digital twin">This model is generated from your saved coordinates. It is not linked to live equipment or sensors.</Callout>
      </div>
    </div>
  )
}

export default function ViewPage() {
  return (
    <FarmGate needDesign>{(farm) => (
      <>
        <PageHeader crumb={<FarmCrumb farm={farm} page="2D / 3D view" />} title="2D / 3D view" description="Both views are drawn from the same saved design, so a change in the layout builder appears here immediately." />
        <View farm={farm} />
      </>
    )}</FarmGate>
  )
}
