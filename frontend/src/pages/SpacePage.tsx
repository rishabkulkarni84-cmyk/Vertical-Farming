import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ImageOff, Plus, Sparkles, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import FarmGate, { FarmCrumb } from '../components/FarmGate'
import PlanView, { PlanLegend, type PlanItem } from '../components/PlanView'
import { Badge, Button, Callout, ConfirmDialog, Field, Input, NumberField, PageHeader, Panel, Segmented, Select, SourceBadge } from '../components/ui'
import { del, get, patch, post } from '../lib/api'
import { useAction, useDisplayUnit, useInvalidateFarm, useObstacles } from '../lib/hooks'
import { fmtLen } from '../lib/units'
import type { AiSettings, Farm, Obstacle, ObstacleKind } from '../lib/types'

const KINDS: { kind: ObstacleKind; label: string; help: string }[] = [
  { kind: 'DOOR', label: 'Door', help: 'Draw along the wall. The access depth is kept clear of racks.' },
  { kind: 'WINDOW', label: 'Window', help: 'Wall feature. Never blocks the floor; racks nearby get a warning.' },
  { kind: 'PILLAR', label: 'Pillar / column', help: 'Fixed structure that blocks the floor.' },
  { kind: 'FURNITURE', label: 'Furniture', help: 'Anything staying in the room.' },
  { kind: 'EQUIPMENT', label: 'Equipment', help: 'Boiler, AC unit, electrical panel…' },
  { kind: 'FIXED', label: 'Fixed obstacle', help: 'Any other permanent object.' },
  { kind: 'RESTRICTED', label: 'Restricted zone', help: 'Floor you want kept free (e.g. access to a panel).' },
]

function defaults(kind: ObstacleKind, L: number, W: number) {
  switch (kind) {
    case 'DOOR': return { x: Math.min(0.3, L - 0.8), y: 0, w: Math.min(0.8, L), d: 0.05, clearance_m: 0.9 }
    case 'WINDOW': return { x: L - 0.05, y: Math.max(0, W / 2 - 0.5), w: 0.05, d: Math.min(1, W), clearance_m: 0 }
    case 'PILLAR': return { x: L / 2 - 0.15, y: W / 2 - 0.15, w: 0.3, d: 0.3, clearance_m: 0 }
    default: return { x: Math.max(0, L / 2 - 0.4), y: Math.max(0, W / 2 - 0.3), w: Math.min(0.8, L), d: Math.min(0.6, W), clearance_m: 0 }
  }
}

function ImagePanel({ farm }: { farm: Farm }) {
  const { data: imgs } = useQuery({ queryKey: ['images', farm.id], queryFn: () => get<any[]>(`/farms/${farm.id}/images`) })
  const [variant, setVariant] = useState<'original' | 'edges'>('original')
  const qc = useQueryClient()
  const img = imgs?.[0]
  const { data: ai } = useQuery({ queryKey: ['ai-settings'], queryFn: () => get<AiSettings>('/ai/settings') })
  const invalidate = useInvalidateFarm()
  const detect = useAction(async (id: number) => { await post(`/images/${id}/ai-analyze`); return post<{ applied: { objects: number } }>(`/images/${id}/ai-apply`, { dimensions: false, objects: true }) }, {
    success: (r) => `AI added ${r.applied.objects} suggested object(s) — confirm or correct each one on the plan`,
    onSuccess: () => { invalidate(farm.id); qc.invalidateQueries({ queryKey: ['images', farm.id] }) },
  })
  return (
    <Panel title="Room photo" description="Visual reference while you mark the plan." actions={<Link to={`/farms/${farm.id}/setup`}><Button size="sm" variant="secondary">{img ? 'Manage photos' : 'Add photo'}</Button></Link>}>
      {!img ? (
        <div className="rounded-lg bg-sage-50 border border-dashed border-line-strong py-8 text-center text-[13px] text-muted"><ImageOff className="size-6 mx-auto mb-2 text-sage-500" />No photo yet — the plan editor works without one.</div>
      ) : (
        <div className="space-y-3">
          <Segmented label="Image view" value={variant} onChange={setVariant} options={[{ value: 'original', label: 'Photo' }, { value: 'edges', label: 'Edge & line hints' }]} />
          <img src={variant === 'edges' ? img.edges_url : img.url} alt={variant === 'edges' ? 'Detected edges and straight lines' : 'Room photo'} className="w-full rounded-md border border-line bg-ink/5 max-h-72 object-contain" />
          <div className="text-[12.5px] text-ink-soft space-y-1">
            {img.analysis?.quality_checks?.map((q: any, i: number) => <div key={i}>{q.message}</div>)}
            {img.analysis?.lines && <div>Straight-line hints: {img.analysis.lines.horizontal} horizontal, {img.analysis.lines.vertical} vertical.</div>}
          </div>
          {ai?.configured ? (
            <div className="space-y-2">
              <Button size="sm" icon={<Sparkles className="size-4" />} loading={detect.isPending} onClick={() => detect.mutate(img.id)}>Find doors, windows & furniture with AI</Button>
              {img.analysis?.ai && <p className="text-[12.5px] text-ink-soft"><SourceBadge source="MODEL" /> {img.analysis.ai.summary}</p>}
              <p className="text-[12px] text-muted">AI suggestions appear on the plan as unconfirmed (dashed) shapes. Drag them into place and press Confirm.</p>
            </div>
          ) : (
            <Callout tone="neutral" title="AI object detection is off">
              Add your API key in <Link className="underline" to="/settings">Settings → AI assistant</Link> to detect doors, windows and furniture from this photo.
              <button className="ml-1 underline" onClick={async () => { await post(`/images/${img.id}/analyze`); qc.invalidateQueries({ queryKey: ['images', farm.id] }) }}>Re-run quality check</button>
            </Callout>
          )}
        </div>
      )}
    </Panel>
  )
}

function Editor({ farm }: { farm: Farm }) {
  const unit = useDisplayUnit()
  const room = farm.room!
  const { data: server } = useObstacles(farm.id)
  const [local, setLocal] = useState<Obstacle[]>([])
  const [sel, setSel] = useState<PlanItem | null>(null)
  const [newKind, setNewKind] = useState<ObstacleKind>('DOOR')
  const [confirmDel, setConfirmDel] = useState(false)
  const invalidate = useInvalidateFarm()
  useEffect(() => { if (server) setLocal(server) }, [server])
  const selected = local.find((o) => sel?.kind === 'obstacle' && String(o.id) === sel.id)

  const add = useAction((k: ObstacleKind) => post<Obstacle>(`/farms/${farm.id}/obstacles`, { kind: k, label: KINDS.find((x) => x.kind === k)!.label.split(' /')[0], ...defaults(k, room.length_m, room.width_m) }),
    { success: 'Added — drag it into position', onSuccess: (o) => { invalidate(farm.id); setSel({ kind: 'obstacle', id: String(o.id) }) } })
  const save = useAction((o: Obstacle) => patch<Obstacle>(`/obstacles/${o.id}`, { kind: o.kind, label: o.label, x: o.x, y: o.y, w: o.w, d: o.d, clearance_m: o.clearance_m, height_m: o.height_m, confirmed: o.confirmed }),
    { onSuccess: () => invalidate(farm.id) })
  const remove = useAction((id: number) => del(`/obstacles/${id}`), { success: 'Obstacle removed', onSuccess: () => { setSel(null); setConfirmDel(false); invalidate(farm.id) } })

  const clamp = (o: Obstacle): Obstacle => ({ ...o, x: Math.min(Math.max(0, o.x), room.length_m - o.w), y: Math.min(Math.max(0, o.y), room.width_m - o.d) })
  const update = (o: Obstacle) => setLocal((ls) => ls.map((x) => (x.id === o.id ? clamp(o) : x)))

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
      <div>
        <PlanView length={room.length_m} width={room.width_m} unit={unit} obstacles={local} gridCell={room.grid_cell_m} editable="obstacles" selected={sel} onSelect={setSel} height={520}
          onMove={(it, x, y) => { const o = local.find((q) => String(q.id) === it.id); if (o) update({ ...o, x, y }) }}
          onDragEnd={(it) => { const o = local.find((q) => String(q.id) === it.id); if (o) save.mutate(o) }} />
        <PlanLegend items={['door', 'obstacle', 'restricted', 'window', 'uncertain']} />
      </div>
      <div className="space-y-4">
        <Panel title="Add to plan">
          <div className="flex gap-2">
            <Select aria-label="Obstacle type" value={newKind} onChange={(e) => setNewKind(e.target.value as ObstacleKind)}>{KINDS.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}</Select>
            <Button icon={<Plus className="size-4" />} loading={add.isPending} onClick={() => add.mutate(newKind)}>Add</Button>
          </div>
          <p className="text-[12.5px] text-muted mt-2">{KINDS.find((k) => k.kind === newKind)?.help}</p>
        </Panel>
        {selected ? (
          <Panel title={<span className="flex items-center gap-2">{selected.label || selected.kind}{!selected.confirmed && <Badge tone="warn">Unconfirmed</Badge>}</span>}
            description="Positions in metres from the top-left corner."
            actions={<Button size="sm" variant="ghost" aria-label="Delete obstacle" icon={<Trash2 className="size-4 text-crit" />} onClick={() => setConfirmDel(true)} />}>
            <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(selected, { onSuccess: () => undefined }) }}>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Type" htmlFor="ok"><Select id="ok" value={selected.kind} onChange={(e) => update({ ...selected, kind: e.target.value as ObstacleKind })}>{KINDS.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}</Select></Field>
                <Field label="Label" htmlFor="ol"><Input id="ol" value={selected.label ?? ''} maxLength={80} onChange={(e) => update({ ...selected, label: e.target.value })} /></Field>
                <NumberField label="x" unit="m" value={+selected.x.toFixed(3)} onChange={(v) => update({ ...selected, x: v ?? 0 })} />
                <NumberField label="y" unit="m" value={+selected.y.toFixed(3)} onChange={(v) => update({ ...selected, y: v ?? 0 })} />
                <NumberField label="Width (along x)" unit="m" value={+selected.w.toFixed(3)} min={0.02} onChange={(v) => update({ ...selected, w: Math.max(0.02, v ?? 0.02) })} />
                <NumberField label="Depth (along y)" unit="m" value={+selected.d.toFixed(3)} min={0.02} onChange={(v) => update({ ...selected, d: Math.max(0.02, v ?? 0.02) })} />
                {selected.kind === 'DOOR' && <div className="col-span-2"><NumberField label="Door swing / access depth" unit="m" min={0} value={selected.clearance_m} hint="Kept clear of racks; walking through it is allowed." onChange={(v) => update({ ...selected, clearance_m: Math.max(0, v ?? 0) })} /></div>}
                <div className="col-span-2"><NumberField label="Height (for 3D view)" unit="m" min={0} value={selected.height_m} hint="Optional." onChange={(v) => update({ ...selected, height_m: v && v > 0 ? v : null })} /></div>
              </div>
              <div className="text-[12.5px] text-muted">{fmtLen(selected.w, unit)} × {fmtLen(selected.d, unit)} at ({fmtLen(selected.x, unit)}, {fmtLen(selected.y, unit)})</div>
              <div className="flex gap-2">
                <Button type="submit" loading={save.isPending}>Save changes</Button>
                {!selected.confirmed && <Button type="button" variant="secondary" icon={<Check className="size-4" />} onClick={() => save.mutate({ ...selected, confirmed: true })}>Confirm</Button>}
              </div>
            </form>
          </Panel>
        ) : (
          <Panel title="Obstacles" description={`${local.length} marked. Select one on the plan or below to edit.`}>
            {local.length === 0 ? <Callout tone="warn" title="Start with the door">Without a door the engine can't check that each rack can be reached on foot.</Callout> : (
              <ul className="divide-y divide-line/70 text-[13.5px]">
                {local.map((o) => (
                  <li key={o.id}><button className="w-full flex items-center justify-between py-2 text-left hover:text-forest-700" onClick={() => setSel({ kind: 'obstacle', id: String(o.id) })}>
                    <span className="flex items-center gap-2">{o.label || o.kind}{o.source === 'MODEL' && !o.confirmed && <SourceBadge source="MODEL" />}</span><span className="text-muted text-[12.5px]">{fmtLen(o.w, unit)} × {fmtLen(o.d, unit)}</span></button></li>
                ))}
              </ul>
            )}
          </Panel>
        )}
        <Link to={`/farms/${farm.id}/layout`} className="block"><Button className="w-full" variant="subtle">Continue to layout builder</Button></Link>
      </div>
      <ConfirmDialog open={confirmDel} onClose={() => setConfirmDel(false)} danger title="Remove this obstacle?" confirmLabel="Remove" loading={remove.isPending}
        onConfirm={() => selected && remove.mutate(selected.id)} body="Saved layouts are re-validated against the updated plan." />
    </div>
  )
}

export default function SpacePage() {
  return (
    <FarmGate>{(farm) => (
      <>
        <PageHeader crumb={<FarmCrumb farm={farm} page="Photo & obstacles" />} title="Photo & obstacles"
          description="Mark everything that takes floor space or must stay clear. You know your room better than any photo analysis — every shape here is yours to place and correct." />
        <div className="space-y-6">
          <Editor farm={farm} />
          <ImagePanel farm={farm} />
        </div>
      </>
    )}</FarmGate>
  )
}
