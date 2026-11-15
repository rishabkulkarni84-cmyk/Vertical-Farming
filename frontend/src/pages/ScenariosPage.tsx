import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { AlertTriangle, GitCompareArrows, Trash2 } from 'lucide-react'
import { useState } from 'react'
import FarmGate, { FarmCrumb } from '../components/FarmGate'
import PlanView from '../components/PlanView'
import { LenField } from '../components/RackConfigForm'
import { Badge, Button, Callout, ConfirmDialog, Empty, Field, Input, PageHeader, Panel, Select } from '../components/ui'
import { del, get, post } from '../lib/api'
import { useAction, useDesign, useDisplayUnit, useInvalidateFarm, useObstacles } from '../lib/hooks'
import { FARMING_TYPES, fmtMoney, fmtNum } from '../lib/units'
import type { Crop, Farm, Scenario, ScenarioResult, ScenarioSummary } from '../lib/types'

type Changes = Partial<{ rack_count: number; rack_length_m: number; rack_depth_m: number; rack_height_m: number; levels: number; walkway_m: number; plant_spacing_m: number; crop_slug: string; budget: number; farming_type: string; orientation: string }>

const ROWS: { k: keyof ScenarioSummary; label: string; fmt: (v: any, c: string) => string; better: 'up' | 'down' | null }[] = [
  { k: 'rack_count', label: 'Racks', fmt: (v) => fmtNum(v), better: 'up' },
  { k: 'plant_capacity', label: 'Plant sites', fmt: (v) => fmtNum(v), better: 'up' },
  { k: 'utilization_pct', label: 'Floor utilisation', fmt: (v) => `${v}%`, better: 'up' },
  { k: 'setup_cost', label: 'Setup cost', fmt: (v, c) => fmtMoney(v, c), better: 'down' },
  { k: 'monthly_cost', label: 'Running cost / month', fmt: (v, c) => fmtMoney(v, c), better: 'down' },
  { k: 'energy_kwh_month', label: 'Energy / month', fmt: (v) => `${fmtNum(v)} kWh`, better: 'down' },
  { k: 'water_l_month', label: 'Water / month', fmt: (v) => `${fmtNum(v)} L`, better: null },
  { k: 'crop_score', label: 'Crop suitability', fmt: (v) => (v === null ? '—' : `${Math.round(v)}/100`), better: 'up' },
  { k: 'monthly_margin', label: 'Est. margin / month', fmt: (v, c) => (v === null ? 'not estimated' : fmtMoney(v, c)), better: 'up' },
]

function Compare({ res, currency }: { res: ScenarioResult; currency: string }) {
  if (!res.feasible) return (
    <Callout tone="crit" title="This scenario doesn't fit">
      <ul className="list-disc pl-4">{[...(res.errors ?? []), ...(res.diagnosis ?? []).map((d) => `${d.reason} ${d.suggestion}`)].map((x, i) => <li key={i}>{x}</li>)}</ul>
    </Callout>
  )
  const b = res.before, a = res.after!
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13.5px]">
        <thead><tr className="text-left text-[12.5px] text-muted border-b border-line"><th className="py-2 font-medium">Measure</th><th className="py-2 font-medium text-right">Current design</th><th className="py-2 font-medium text-right">Scenario</th><th className="py-2 font-medium text-right">Change</th></tr></thead>
        <tbody>
          {ROWS.map((r) => {
            const bv = b?.[r.k] as number | null, av = a[r.k] as number | null
            const d = typeof bv === 'number' && typeof av === 'number' ? av - bv : null
            const good = d === null || d === 0 || !r.better ? null : (d > 0) === (r.better === 'up')
            return (
              <tr key={r.k} className="border-b border-line/60">
                <td className="py-2 text-ink-soft">{r.label}</td>
                <td className="py-2 text-right tabular-nums">{b ? r.fmt(bv, currency) : '—'}</td>
                <td className="py-2 text-right font-semibold tabular-nums">{r.fmt(av, currency)}</td>
                <td className={clsx('py-2 text-right tabular-nums', good === true && 'text-grow', good === false && 'text-crit')}>
                  {d === null || d === 0 ? '—' : `${d > 0 ? '▲ +' : '▼ '}${r.k.includes('cost') || r.k === 'monthly_margin' ? fmtMoney(d, currency) : fmtNum(d, r.k === 'utilization_pct' ? 1 : 0)}`}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {res.notes?.map((n, i) => <p key={i} className="text-[12.5px] text-warn mt-2">{n}</p>)}
      {a.over_budget && <p className="text-[12.5px] text-warn mt-2">Scenario setup cost exceeds the budget.</p>}
    </div>
  )
}

function Scenarios({ farm }: { farm: Farm }) {
  const unit = useDisplayUnit()
  const { data: base } = useDesign(farm.active_design_id)
  const { data: obstacles } = useObstacles(farm.id)
  const { data: list } = useQuery({ queryKey: ['scenarios', farm.id], queryFn: () => get<Scenario[]>(`/farms/${farm.id}/scenarios`) })
  const { data: crops } = useQuery({ queryKey: ['crops'], queryFn: () => get<{ crops: Crop[] }>('/crops') })
  const [name, setName] = useState('')
  const [ch, setCh] = useState<Changes>({})
  const [preview, setPreview] = useState<ScenarioResult | null>(null)
  const [sel, setSel] = useState<number | null>(null)
  const [applying, setApplying] = useState<Scenario | null>(null)
  const invalidate = useInvalidateFarm()
  const cfg = base?.rack_config
  const clean = () => Object.fromEntries(Object.entries(ch).filter(([, v]) => v !== undefined && v !== null && v !== '' && !Number.isNaN(v as number)))
  const run = useAction(() => post<ScenarioResult>(`/farms/${farm.id}/scenarios/preview`, { name: name || 'Preview', changes: clean() }), { onSuccess: setPreview })
  const save = useAction(() => post<Scenario>(`/farms/${farm.id}/scenarios`, { name: name.trim() || `Scenario ${(list?.length ?? 0) + 1}`, changes: clean() }),
    { success: 'Scenario saved', invalidate: [['scenarios', farm.id]], onSuccess: (s) => { setSel(s.id); setPreview(null) } })
  const apply = useAction((id: number) => post(`/scenarios/${id}/apply`), { success: 'Applied as a new active design — the original design is kept', invalidate: [['scenarios', farm.id]], onSuccess: () => { setApplying(null); invalidate(farm.id) } })
  const remove = useAction((id: number) => del(`/scenarios/${id}`), { success: 'Scenario deleted', invalidate: [['scenarios', farm.id]], onSuccess: () => setSel(null) })
  const shown = sel ? list?.find((s) => s.id === sel) : null
  const res = preview ?? shown?.result ?? null

  return (
    <div className="grid gap-6 xl:grid-cols-[340px_1fr]">
      <div className="space-y-4">
        <Panel title="Change something" description="Leave a field blank to keep the current value. Your saved design is never overwritten.">
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); run.mutate(undefined) }}>
            <Field label="Scenario name" htmlFor="sn"><Input id="sn" value={name} maxLength={120} placeholder="e.g. Five levels, narrower aisle" onChange={(e) => setName(e.target.value)} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Rack count" htmlFor="rc" hint={base ? `now ${base.rack_count}` : undefined}><Input id="rc" type="number" min={1} value={ch.rack_count ?? ''} onChange={(e) => setCh({ ...ch, rack_count: e.target.value ? Number(e.target.value) : undefined })} /></Field>
              <Field label="Levels" htmlFor="lv" hint={cfg ? `now ${cfg.levels}` : undefined}><Input id="lv" type="number" min={1} max={12} value={ch.levels ?? ''} onChange={(e) => setCh({ ...ch, levels: e.target.value ? Number(e.target.value) : undefined })} /></Field>
              <LenField label="Rack length" unit={unit} nullable m={ch.rack_length_m ?? null} onChange={(v) => setCh({ ...ch, rack_length_m: v ?? undefined })} />
              <LenField label="Rack depth" unit={unit} nullable m={ch.rack_depth_m ?? null} onChange={(v) => setCh({ ...ch, rack_depth_m: v ?? undefined })} />
              <LenField label="Rack height" unit={unit} nullable m={ch.rack_height_m ?? null} onChange={(v) => setCh({ ...ch, rack_height_m: v ?? undefined })} />
              <LenField label="Walkway" unit={unit} nullable m={ch.walkway_m ?? null} onChange={(v) => setCh({ ...ch, walkway_m: v ?? undefined })} />
              <LenField label="Plant spacing" unit={unit} nullable m={ch.plant_spacing_m ?? null} onChange={(v) => setCh({ ...ch, plant_spacing_m: v ?? undefined })} />
              <Field label="Budget" htmlFor="bg"><Input id="bg" type="number" min={0} suffix={farm.currency} value={ch.budget ?? ''} onChange={(e) => setCh({ ...ch, budget: e.target.value ? Number(e.target.value) : undefined })} /></Field>
            </div>
            <Field label="Crop" htmlFor="cr"><Select id="cr" value={ch.crop_slug ?? ''} onChange={(e) => setCh({ ...ch, crop_slug: e.target.value || undefined })}><option value="">Keep current</option>{crops?.crops.map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}</Select></Field>
            <Field label="Growing method" htmlFor="fm"><Select id="fm" value={ch.farming_type ?? ''} onChange={(e) => setCh({ ...ch, farming_type: e.target.value || undefined })}><option value="">Keep current</option>{Object.entries(FARMING_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
            <div className="flex gap-2 pt-1">
              <Button type="submit" loading={run.isPending} disabled={!Object.keys(clean()).length}>Run scenario</Button>
              <Button type="button" variant="secondary" loading={save.isPending} disabled={!Object.keys(clean()).length} onClick={() => save.mutate(undefined)}>Save scenario</Button>
            </div>
          </form>
        </Panel>
        <Panel title="Saved scenarios">
          {!list?.length ? <p className="text-[13px] text-muted">None yet.</p> : (
            <ul className="divide-y divide-line/70">{list.map((s) => (
              <li key={s.id}><button onClick={() => { setSel(s.id); setPreview(null) }} className={clsx('w-full text-left py-2 px-2 -mx-2 rounded', sel === s.id && !preview && 'bg-sage-50')}>
                <div className="flex items-center gap-2 text-[13.5px] font-medium">{s.name}{!s.result.feasible ? <Badge tone="crit">Infeasible</Badge> : s.applied_design_id ? <Badge tone="info">Applied</Badge> : null}</div>
                <div className="text-[12px] text-muted truncate">{Object.entries(s.changes).map(([k, v]) => `${k.replace(/_m$/, '').replace(/_/g, ' ')} ${typeof v === 'number' && k.endsWith('_m') ? (+v).toFixed(2) + ' m' : v}`).join(' · ')}</div>
              </button></li>
            ))}</ul>
          )}
        </Panel>
      </div>
      <div className="space-y-4 min-w-0">
        {!res ? (
          <Panel><Empty icon={<GitCompareArrows className="size-8" />} title="Compare a change against your current design">Every scenario re-runs the full layout engine, capacity, costs, resources and crop scoring on a copy of the design.</Empty></Panel>
        ) : (
          <>
            <Panel title={preview ? 'Preview (not saved)' : shown?.name} description={res.feasible ? res.strategy : undefined}
              actions={!preview && shown && <>
                <Button size="sm" variant="ghost" icon={<Trash2 className="size-4" />} aria-label="Delete scenario" onClick={() => remove.mutate(shown.id)} />
                <Button size="sm" disabled={!res.feasible} onClick={() => setApplying(shown)}>Apply as new design</Button>
              </>}>
              <Compare res={res} currency={farm.currency} />
            </Panel>
            {res.feasible && res.racks && (
              <PlanView length={farm.room!.length_m} width={farm.room!.width_m} unit={unit} obstacles={obstacles} racks={res.racks} aisles={Object.values((res as any).validation?.aisles ?? {}).map((a: any) => a.rect)} height={380} />
            )}
            {!res.feasible && <p className="text-[13px] text-muted flex gap-2"><AlertTriangle className="size-4 text-warn" />Constraints are never relaxed to make a scenario look feasible.</p>}
          </>
        )}
      </div>
      <ConfirmDialog open={!!applying} onClose={() => setApplying(null)} title="Apply this scenario?" confirmLabel="Apply as new design" loading={apply.isPending}
        onConfirm={() => applying && apply.mutate(applying.id)}
        body={<>A new design “{applying?.name} (from scenario)” is created from the re-checked layout and made active. Your current design “{base?.name}” stays saved and can be re-activated from Farms & designs.</>} />
    </div>
  )
}

export default function ScenariosPage() {
  return (
    <FarmGate needDesign>{(farm) => (
      <>
        <PageHeader crumb={<FarmCrumb farm={farm} page="What-if scenarios" />} title="What-if scenarios" description="Try more racks, different sizes, a narrower walkway, another crop or budget — and see exactly what changes." />
        <Scenarios farm={farm} />
      </>
    )}</FarmGate>
  )
}
