import { useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { AlertTriangle, CheckCircle2, Plus, Redo2, RotateCw, Sparkles, Trash2, Undo2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import FarmGate, { FarmCrumb } from '../components/FarmGate'
import PlanView, { PlanLegend, type PlanItem } from '../components/PlanView'
import RackConfigForm, { DEFAULT_CONFIG } from '../components/RackConfigForm'
import { Badge, Button, Callout, Dialog, Field, Input, PageHeader, Panel, Segmented, Spinner, Stat } from '../components/ui'
import { ApiError, errorMessage, patch, post } from '../lib/api'
import { useAction, useDesign, useDisplayUnit, useInvalidateFarm, useObstacles } from '../lib/hooks'
import { fmtArea, fmtLen, fmtMoney, fmtNum } from '../lib/units'
import type { Design, Evaluation, Farm, GenerateResult, LayoutOption, Rack, RackConfig, Violation } from '../lib/types'

function Metrics({ ev, currency }: { ev: Pick<Evaluation, 'metrics' | 'capacity'> & { setup?: number; over?: boolean }; currency: string }) {
  const unit = useDisplayUnit()
  const m = ev.metrics
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-4">
      <Stat label="Racks" value={m.rack_count} sub={fmtArea(m.rack_footprint_m2, unit) + ' footprint'} />
      <Stat label="Plant sites" value={fmtNum(ev.capacity.total)} sub={ev.capacity.total !== null ? `${ev.capacity.plants_per_level} × ${ev.capacity.levels_per_rack} lv × ${ev.capacity.rack_count}` : 'Choose a crop'} />
      <Stat label="Floor utilisation" value={`${m.utilization_pct}%`} sub="rack footprint ÷ floor area" />
      {ev.setup !== undefined && <Stat label="Setup estimate" value={fmtMoney(ev.setup, currency)} tone={ev.over ? 'warn' : undefined} sub={ev.over ? 'Over budget' : 'Illustrative prices'} />}
      <div className="col-span-2 text-[12.5px] text-ink-soft grid grid-cols-3 gap-2 pt-1 border-t border-line">
        <span>Blocked<br /><b className="font-medium text-ink">{fmtArea(m.blocked_area_m2, unit)}</b></span>
        <span>Walkways & door<br /><b className="font-medium text-ink">{fmtArea(m.reserved_area_m2, unit)}</b></span>
        <span>Unused<br /><b className="font-medium text-ink">{fmtArea(m.free_area_m2, unit)}</b></span>
      </div>
    </div>
  )
}

function Issues({ violations, warnings }: { violations: Violation[]; warnings: Violation[] }) {
  if (!violations.length && !warnings.length) return <Callout tone="good" title="All hard constraints pass">Inside the room, clear of obstacles and door zones, no overlaps, every rack has a walkway reachable from the door.</Callout>
  return (
    <div className="space-y-2">
      {violations.length > 0 && <Callout tone="crit" title={`${violations.length} constraint violation${violations.length > 1 ? 's' : ''} — can't save`}>
        <ul className="list-disc pl-4 space-y-0.5">{violations.map((v, i) => <li key={i}>{v.message}</li>)}</ul></Callout>}
      {warnings.map((w, i) => <Callout key={i} tone="warn">{w.message}</Callout>)}
    </div>
  )
}

/* ================================================================== generate */
function Generate({ farm, onSaved }: { farm: Farm; onSaved: () => void }) {
  const unit = useDisplayUnit()
  const room = farm.room!
  const { data: obstacles } = useObstacles(farm.id)
  const [cfg, setCfg] = useState<RackConfig>(DEFAULT_CONFIG)
  const [res, setRes] = useState<GenerateResult | null>(null)
  const [pick, setPick] = useState(0)
  const [naming, setNaming] = useState(false)
  const [name, setName] = useState('')
  const invalidate = useInvalidateFarm()
  const gen = useAction((c: RackConfig) => post<GenerateResult>(`/farms/${farm.id}/layouts/generate`, c), { onSuccess: (r) => { setRes(r); setPick(0) } })
  const save = useAction((o: LayoutOption) => post<Design>(`/farms/${farm.id}/designs`, { name: name.trim() || 'Plan', rack_config: res!.config, racks: o.racks, strategy: o.strategy, activate: true }),
    { success: 'Layout saved and set as active design', onSuccess: () => { setNaming(false); invalidate(farm.id); onSaved() } })
  const opt = res?.options[pick]

  return (
    <div className="grid gap-6 xl:grid-cols-[320px_1fr]">
      <Panel title="Rack settings" description={`Showing lengths in ${unit}. Change units in Settings.`}>
        <form onSubmit={(e) => { e.preventDefault(); gen.mutate(cfg) }} className="space-y-5">
          <RackConfigForm cfg={cfg} onChange={setCfg} unit={unit} />
          <Button type="submit" className="w-full" loading={gen.isPending} icon={<Sparkles className="size-4" />}>Generate layouts</Button>
        </form>
      </Panel>
      <div className="space-y-4 min-w-0">
        {!res ? (
          <>
            <PlanView length={room.length_m} width={room.width_m} unit={unit} obstacles={obstacles} gridCell={room.grid_cell_m} height={440} />
            <p className="text-[13px] text-muted">Adjust rack settings and generate. The engine tries row patterns in both orientations, rejects every candidate that breaks a hard constraint, and ranks the rest.</p>
          </>
        ) : !res.feasible ? (
          <Panel title="No layout fits with these settings">
            <ul className="space-y-3">{res.diagnosis.map((d, i) => (
              <li key={i} className="flex gap-3 text-[13.5px]"><AlertTriangle className="size-4 text-warn shrink-0 mt-0.5" aria-hidden /><div><div className="text-ink">{d.reason}</div><div className="text-forest-700 font-medium mt-0.5">{d.suggestion}</div></div></li>
            ))}</ul>
          </Panel>
        ) : (
          <>
            <div role="radiogroup" aria-label="Layout options" className="grid gap-2 sm:grid-cols-2 2xl:grid-cols-4">
              {res.options.map((o, i) => (
                <button key={i} role="radio" aria-checked={pick === i} onClick={() => setPick(i)}
                  className={clsx('text-left rounded-lg border px-3.5 py-3 transition-colors', pick === i ? 'border-forest-700 bg-sage-50 ring-1 ring-forest-700' : 'border-line bg-surface hover:border-line-strong')}>
                  <div className="flex items-center justify-between"><span className="font-display text-lg font-semibold">{o.metrics.rack_count} racks</span>{i === 0 ? <Badge tone="good">Best score</Badge> : <span className="text-[12.5px] text-muted">score {o.score}</span>}</div>
                  <div className="text-[12.5px] text-ink-soft mt-0.5 line-clamp-2">{o.strategy}</div>
                  <div className="text-[12.5px] text-muted mt-1">{fmtNum(o.capacity.total)} plant sites · {o.metrics.utilization_pct}% floor{o.over_budget && ' · over budget'}</div>
                </button>
              ))}
            </div>
            {opt && (
              <div className="grid gap-4 2xl:grid-cols-[1fr_300px]">
                <div>
                  <PlanView length={room.length_m} width={room.width_m} unit={unit} obstacles={obstacles} racks={opt.racks} aisles={Object.values(opt.validation.aisles).map((a) => a.rect)} gridCell={room.grid_cell_m} height={440} />
                  <PlanLegend items={['rack', 'walkway', 'door', 'obstacle']} />
                </div>
                <div className="space-y-4">
                  <Panel title="This option"><Metrics ev={{ metrics: opt.metrics, capacity: opt.capacity, setup: opt.setup_cost, over: opt.over_budget }} currency={farm.currency} /></Panel>
                  <Issues violations={[]} warnings={opt.validation.warnings} />
                  {opt.over_budget && <Callout tone="crit" title="Over budget">This option costs more than the budget. Pick a smaller option, reduce Max racks or levels, or use the Budget plan page.</Callout>}
                  <Button className="w-full" disabled={opt.over_budget} onClick={() => { setName(`Plan — ${opt.metrics.rack_count} racks`); setNaming(true) }}>Save this layout</Button>
                  <details className="text-[12.5px] text-muted"><summary className="cursor-pointer">How options are scored</summary><p className="mt-1">{res.scoring}</p>
                    {Object.keys(res.rejections).length > 0 && <p className="mt-1">Rejected candidates: {Object.entries(res.rejections).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`).join(', ')}.</p>}</details>
                </div>
              </div>
            )}
          </>
        )}
      </div>
      <Dialog open={naming} onClose={() => setNaming(false)} title="Save layout"
        footer={<><Button variant="secondary" onClick={() => setNaming(false)}>Cancel</Button><Button loading={save.isPending} onClick={() => opt && save.mutate(opt)}>Save layout</Button></>}>
        <Field label="Design name" htmlFor="dn"><Input id="dn" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} /></Field>
        <p className="text-[12.5px] text-muted mt-2">The server re-validates the layout before saving; it becomes the farm's active design.</p>
      </Dialog>
    </div>
  )
}

/* ================================================================== edit */
function Editor({ farm, design }: { farm: Farm; design: Design }) {
  const unit = useDisplayUnit()
  const room = farm.room!
  const cfg = design.rack_config
  const { data: obstacles } = useObstacles(farm.id)
  const [racks, setRacks] = useState<Rack[]>(design.racks)
  const [hist, setHist] = useState<{ past: Rack[][]; future: Rack[][] }>({ past: [], future: [] })
  const [sel, setSel] = useState<PlanItem | null>(null)
  const [ev, setEv] = useState<Evaluation | null>(design)
  const [checking, setChecking] = useState(false)
  const dirty = JSON.stringify(racks) !== JSON.stringify(design.racks)
  const qc = useQueryClient()
  const invalidate = useInvalidateFarm()
  const dragStart = useRef<Rack[] | null>(null)

  useEffect(() => { setRacks(design.racks); setEv(design); setHist({ past: [], future: [] }) }, [design])

  // live server-side validation (debounced) — the browser never decides validity on its own
  useEffect(() => {
    if (!dirty) { setEv(design); return }
    setChecking(true)
    const t = setTimeout(async () => {
      try { setEv(await post<Evaluation>(`/designs/${design.id}/validate`, { racks })) } catch { /* keep last */ } finally { setChecking(false) }
    }, 250)
    return () => clearTimeout(t)
  }, [racks, dirty, design])

  const commit = useCallback((next: Rack[], from?: Rack[]) => {
    setHist((h) => ({ past: [...h.past.slice(-49), from ?? racks], future: [] }))
    setRacks(next)
  }, [racks])
  const undo = () => {
    if (!hist.past.length) return
    setHist({ past: hist.past.slice(0, -1), future: [racks, ...hist.future] })
    setRacks(hist.past[hist.past.length - 1])
  }
  const redo = () => {
    if (!hist.future.length) return
    const [nx, ...rest] = hist.future
    setHist({ past: [...hist.past, racks], future: rest })
    setRacks(nx)
  }

  const selRack = racks.find((r) => sel?.kind === 'rack' && r.label === sel.id)
  const rotate = () => {
    if (!selRack) return
    const cx = selRack.x + selRack.w / 2, cy = selRack.y + selRack.d / 2
    const nr: Rack = { ...selRack, w: selRack.d, d: selRack.w, rotation: selRack.rotation === 0 ? 90 : 0, access_side: null, x: Math.max(0, +(cx - selRack.d / 2).toFixed(3)), y: Math.max(0, +(cy - selRack.w / 2).toFixed(3)) }
    commit(racks.map((r) => (r.label === selRack.label ? nr : r)))
  }
  const addRack = () => {
    const n = Math.max(0, ...racks.map((r) => Number(r.label.replace(/\D/g, '')) || 0)) + 1
    const label = `R${n}`
    commit([...racks, { label, x: Math.max(0, room.length_m / 2 - cfg.rack_length_m / 2), y: Math.max(0, room.width_m / 2 - cfg.rack_depth_m / 2), w: cfg.rack_length_m, d: cfg.rack_depth_m, rotation: 0, access_side: null }])
    setSel({ kind: 'rack', id: label })
  }
  const remove = () => { if (selRack) { commit(racks.filter((r) => r.label !== selRack.label)); setSel(null) } }
  const nudge = (dx: number, dy: number) => selRack && commit(racks.map((r) => (r.label === selRack.label ? { ...r, x: Math.max(0, +(r.x + dx).toFixed(3)), y: Math.max(0, +(r.y + dy).toFixed(3)) } : r)))

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('input,select,textarea')) return
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); if (e.shiftKey) redo(); else undo() }
      else if (selRack && e.key === 'r') rotate()
      else if (selRack && (e.key === 'Delete' || e.key === 'Backspace')) remove()
      else if (selRack && e.key.startsWith('Arrow')) {
        e.preventDefault()
        const s = e.shiftKey ? 0.25 : 0.05
        nudge(e.key === 'ArrowLeft' ? -s : e.key === 'ArrowRight' ? s : 0, e.key === 'ArrowUp' ? -s : e.key === 'ArrowDown' ? s : 0)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const save = useAction(() => patch<Design>(`/designs/${design.id}`, { racks }), {
    success: 'Layout saved', silentError: true,
    onSuccess: (d) => { qc.setQueryData(['design', design.id], d); invalidate(farm.id) },
  })
  const saveErr = save.error instanceof ApiError ? (save.error.details as any)?.violations as Violation[] | undefined : undefined
  const invalid = useMemo(() => new Set((ev?.validation.violations ?? []).map((v) => v.rack).filter(Boolean) as string[]), [ev])
  const valid = ev?.validation.valid ?? false

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_330px]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <Button size="sm" variant="secondary" icon={<Plus className="size-4" />} onClick={addRack}>Add rack</Button>
          <Button size="sm" variant="secondary" icon={<RotateCw className="size-4" />} onClick={rotate} disabled={!selRack}>Rotate</Button>
          <Button size="sm" variant="secondary" icon={<Trash2 className="size-4" />} onClick={remove} disabled={!selRack}>Remove</Button>
          <span className="w-px h-6 bg-line mx-1" aria-hidden />
          <Button size="sm" variant="ghost" icon={<Undo2 className="size-4" />} onClick={undo} disabled={!hist.past.length} aria-label="Undo" />
          <Button size="sm" variant="ghost" icon={<Redo2 className="size-4" />} onClick={redo} disabled={!hist.future.length} aria-label="Redo" />
          <span className="ml-auto text-[12.5px] text-muted hidden md:block">Drag racks · arrows nudge (Shift = 25 cm) · R rotates · Ctrl/⌘Z undo</span>
        </div>
        <PlanView length={room.length_m} width={room.width_m} unit={unit} obstacles={obstacles} racks={racks} invalidRacks={invalid}
          aisles={Object.values(ev?.validation.aisles ?? {}).map((a) => a.rect)} gridCell={room.grid_cell_m} editable="racks" selected={sel} onSelect={setSel} height={520}
          onMove={(it, x, y) => { if (!dragStart.current) dragStart.current = racks; setRacks((rs) => rs.map((r) => (r.label === it.id ? { ...r, x: +x.toFixed(3), y: +y.toFixed(3) } : r))) }}
          onDragEnd={() => { if (dragStart.current) { const from = dragStart.current; dragStart.current = null; setHist((h) => ({ past: [...h.past.slice(-49), from], future: [] })) } }} />
        <PlanLegend items={['rack', 'invalid', 'walkway', 'door', 'obstacle', 'restricted']} />
        {selRack && (
          <div className="mt-3 text-[13px] text-ink-soft" aria-live="polite">
            <b className="text-ink">{selRack.label}</b> at x {fmtLen(selRack.x, unit)}, y {fmtLen(selRack.y, unit)} · {fmtLen(selRack.w, unit)} × {fmtLen(selRack.d, unit)} · {selRack.rotation}°
          </div>
        )}
      </div>
      <div className="space-y-4">
        <Panel title={<span className="flex items-center gap-2">{design.name}{valid ? <Badge tone="good"><CheckCircle2 className="size-3" />Valid</Badge> : <Badge tone="crit"><AlertTriangle className="size-3" />Invalid</Badge>}{checking && <span className="text-[12px] text-muted font-normal">checking…</span>}</span>}
          description={dirty ? 'Unsaved changes' : 'Saved'}>
          {ev ? <Metrics ev={{ metrics: ev.metrics, capacity: ev.capacity, setup: ev.cost_totals.setup_total, over: ev.over_budget }} currency={farm.currency} /> : <Spinner />}
        </Panel>
        {ev && <Issues violations={ev.validation.violations} warnings={ev.validation.warnings} />}
        {saveErr && <Callout tone="crit" title="Server rejected the save">{saveErr.map((v) => v.message).join(' ')}</Callout>}
        {save.error && !saveErr && <Callout tone="crit">{errorMessage(save.error)}</Callout>}
        <div className="flex gap-2">
          <Button className="flex-1" disabled={!dirty || !valid || checking} loading={save.isPending} onClick={() => save.mutate(undefined)}>Save layout</Button>
          <Button variant="secondary" disabled={!dirty} onClick={() => commit(design.racks)}>Discard</Button>
        </div>
        {ev?.capacity.warnings.map((w, i) => <Callout key={i} tone="warn">{w}</Callout>)}
        <div className="text-[12.5px] text-muted space-y-1">
          <p>Rack: {fmtLen(cfg.rack_length_m, unit)} × {fmtLen(cfg.rack_depth_m, unit)} × {fmtLen(cfg.rack_height_m, unit)}, {cfg.levels} levels · walkway {fmtLen(cfg.walkway_m, unit)}</p>
          <p>Constraints are never relaxed to make a layout fit. <Link className="text-forest-700 hover:underline" to={`/farms/${farm.id}/scenarios`}>Try different rack sizes in a scenario</Link>.</p>
        </div>
      </div>
    </div>
  )
}

function Builder({ farm }: { farm: Farm }) {
  const { data: design, isLoading } = useDesign(farm.active_design_id)
  const [tab, setTab] = useState<'edit' | 'generate'>(farm.active_design_id ? 'edit' : 'generate')
  useEffect(() => { if (!farm.active_design_id) setTab('generate') }, [farm.active_design_id])
  return (
    <>
      <PageHeader crumb={<FarmCrumb farm={farm} page="Layout builder" />} title="Layout builder"
        description="Generate rack layouts that respect every clearance rule, then fine-tune them by hand. Invalid positions are shown with the reason and can't be saved."
        actions={farm.active_design_id && <Segmented label="Mode" value={tab} onChange={setTab} options={[{ value: 'edit', label: 'Edit saved layout' }, { value: 'generate', label: 'Generate new' }]} />} />
      {tab === 'generate' ? <Generate farm={farm} onSaved={() => setTab('edit')} /> : isLoading || !design ? <Spinner label="Loading design" /> : <Editor farm={farm} design={design} />}
    </>
  )
}

export default function LayoutBuilder() {
  return <FarmGate>{(farm) => <Builder farm={farm} />}</FarmGate>
}
