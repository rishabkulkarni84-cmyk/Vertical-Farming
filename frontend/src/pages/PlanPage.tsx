import { useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCcw, Sparkles, Wallet } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import FarmGate, { FarmCrumb } from '../components/FarmGate'
import PlanView, { PlanLegend } from '../components/PlanView'
import { Badge, Button, Callout, Empty, Field, PageHeader, Panel, Select, SourceBadge, Spinner, Stat, Table } from '../components/ui'
import { get, post } from '../lib/api'
import { useAction, useDesign, useDisplayUnit, useInvalidateFarm, useObstacles } from '../lib/hooks'
import { fmtLen, fmtMoney, fmtNum } from '../lib/units'
import type { CostView, Crop, Farm, PlanResult } from '../lib/types'

function BudgetBar({ budget, spent, reserve, currency }: { budget: number; spent: number; reserve: number; currency: string }) {
  const pct = (v: number) => `${Math.min(100, (v / budget) * 100)}%`
  const left = Math.max(0, budget - spent)
  return (
    <div>
      <div className="flex items-baseline justify-between text-[13px] mb-1.5">
        <span><b className="font-display text-[22px]">{fmtMoney(spent, currency)}</b> <span className="text-muted">of {fmtMoney(budget, currency)} budget</span></span>
        <span className="text-grow font-medium">{fmtMoney(left, currency)} left</span>
      </div>
      <div className="h-3 rounded-full bg-sage-100 overflow-hidden flex" role="meter" aria-valuemin={0} aria-valuemax={budget} aria-valuenow={spent} aria-label="Budget used">
        <div className="bg-forest-700 h-full" style={{ width: pct(spent) }} />
        <div className="h-full" style={{ width: pct(Math.max(0, left - reserve)) }} />
      </div>
      <div className="flex justify-between text-[12px] text-muted mt-1"><span>Equipment & setup</span><span>{fmtMoney(reserve, currency)} kept as safety reserve</span></div>
    </div>
  )
}

function Plan({ farm }: { farm: Farm }) {
  const unit = useDisplayUnit()
  const qc = useQueryClient()
  const invalidate = useInvalidateFarm()
  const { data: design, isLoading } = useDesign(farm.active_design_id)
  const { data: obstacles } = useObstacles(farm.id)
  const { data: costs } = useQuery({ queryKey: ['costs', farm.active_design_id], queryFn: () => get<CostView>(`/designs/${farm.active_design_id}/costs`), enabled: !!farm.active_design_id })
  const { data: crops } = useQuery({ queryKey: ['crops'], queryFn: () => get<{ crops: Crop[] }>('/crops') })
  const { data: alt } = useQuery({ queryKey: ['plan-alt', farm.id, farm.active_design_id, farm.budget], queryFn: () => post<PlanResult>(`/farms/${farm.id}/autoplan`, { save: false, crop_slug: design?.crop_slug }), enabled: !!farm.budget && !!farm.room && (!farm.active_design_id || !!design) })
  const [reserve, setReserve] = useState('5')
  const [crop, setCrop] = useState('')
  const [planErr, setPlanErr] = useState<string | null>(null)
  const replan = useAction(() => post<PlanResult>(`/farms/${farm.id}/autoplan`, { reserve_pct: Number(reserve), crop_slug: crop || design?.crop_slug || null }), {
    onSuccess: (r) => {
      if (!r.feasible) { setPlanErr(r.reason ?? 'No plan fits.'); return }
      setPlanErr(null); invalidate(farm.id); qc.invalidateQueries({ queryKey: ['plan-alt'] })
    },
    success: (r) => (r.feasible ? `New plan: ${r.racks?.length} rack(s), ${r.plants} plant sites` : 'No plan fits this budget'),
  })

  if (!farm.budget) return <Panel><Empty icon={<Wallet className="size-8" />} title="Add the customer's budget" action={<Link to={`/farms/${farm.id}/setup`}><Button>Open room setup</Button></Link>}>The plan is built from the budget: racks, levels and equipment are chosen to fit inside it.</Empty></Panel>
  if (isLoading) return <Spinner label="Loading plan" />

  const controls = (
    <Panel title="Re-plan">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); replan.mutate(undefined) }}>
        <Field label="Crop" htmlFor="rc"><Select id="rc" value={crop || design?.crop_slug || ''} onChange={(e) => setCrop(e.target.value)}>
          <option value="">Choose for me</option>{crops?.crops.map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}</Select></Field>
        <Field label="Safety reserve" htmlFor="rs" hint="Part of the budget kept back for delivery, tools and surprises.">
          <Select id="rs" value={reserve} onChange={(e) => setReserve(e.target.value)}>{['0', '5', '10', '15', '20'].map((v) => <option key={v} value={v}>{v}%</option>)}</Select></Field>
        <Button type="submit" className="w-full" icon={<RefreshCcw className="size-4" />} loading={replan.isPending}>Make a new plan</Button>
        <p className="text-[12px] text-muted">Change the budget in <Link className="underline" to={`/farms/${farm.id}/setup`}>Room setup</Link>.</p>
      </form>
    </Panel>
  )

  if (!design) return (
    <div className="grid gap-6 xl:grid-cols-[1fr_320px]">
      <Panel><Empty icon={<Sparkles className="size-8" />} title="No plan yet" action={<Button loading={replan.isPending} onClick={() => replan.mutate(undefined)}>Create budget plan</Button>}>
        Verdant picks the racks, levels and equipment that give the most plant sites for {fmtMoney(farm.budget, farm.currency)}.</Empty>
        {planErr && <Callout tone="crit" title="No plan fits">{planErr}</Callout>}</Panel>
      {controls}
    </div>
  )

  const cfg = design.rack_config
  const included = costs?.items.filter((i) => i.included && i.cost_type === 'ONE_TIME') ?? []
  const reserveAmt = alt?.feasible ? (farm.budget * (alt.reserve_pct ?? 5)) / 100 : farm.budget * 0.05
  return (
    <div className="space-y-6">
      {design.origin !== 'BUDGET_PLAN' && <Callout tone="info">The active design was made by hand or from a scenario. Make a new plan to let Verdant choose everything from the budget.</Callout>}
      {design.over_budget && <Callout tone="crit" title="Over budget">Edited prices push this design above the budget. Make a new plan or adjust the costs.</Callout>}
      <div className="grid gap-6 xl:grid-cols-[1fr_320px]">
        <div className="space-y-6 min-w-0">
          <Panel>
            <BudgetBar budget={farm.budget} spent={design.cost_totals.setup_total} reserve={reserveAmt} currency={farm.currency} />
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-5 mt-5">
              <Stat label="Racks chosen" value={`${design.rack_count} × ${cfg.levels} levels`} sub={`${fmtLen(cfg.rack_length_m, unit)} × ${fmtLen(cfg.rack_depth_m, unit)}, ${fmtLen(cfg.rack_height_m, unit)} tall`} />
              <Stat label="Plant sites" value={fmtNum(design.capacity.total)} sub={design.crop?.name ?? 'leafy greens (assumed)'} />
              <Stat label="Running cost / month" value={fmtMoney(design.cost_totals.monthly_total, farm.currency)} sub={`${fmtNum(design.resources.energy_kwh_month)} kWh electricity`} />
              <Stat label="Est. margin / month" value={design.profitability.available ? fmtMoney(design.profitability.estimated_margin, farm.currency) : '—'}
                tone={design.profitability.available ? ((design.profitability.estimated_margin ?? 0) < 0 ? 'crit' : 'good') : undefined}
                sub={design.profitability.available ? 'at your price assumption' : <Link className="underline" to={`/farms/${farm.id}/crops`}>Get prices from AI advisor</Link>} />
            </div>
          </Panel>
          <div>
            <PlanView length={farm.room!.length_m} width={farm.room!.width_m} unit={unit} obstacles={obstacles} racks={design.racks} aisles={Object.values(design.validation.aisles).map((a) => a.rect)} gridCell={farm.room!.grid_cell_m} height={400} />
            <PlanLegend items={['rack', 'walkway', 'door', 'obstacle']} />
          </div>
          <Panel title="Equipment in this plan" description="Chosen automatically to match the racks. Prices are editable on the Costs page."
            actions={<Link to={`/farms/${farm.id}/costs`}><Button size="sm" variant="secondary">Edit costs</Button></Link>}>
            <Table head={['Item', 'Qty', 'Cost', 'Price']}>
              {included.map((i) => <tr key={i.id}><td>{i.name}</td><td>{fmtNum(i.quantity, 1)} {i.unit}</td><td className="tabular-nums">{fmtMoney(i.subtotal, i.currency)}</td><td><SourceBadge source={i.price_source} /></td></tr>)}
            </Table>
          </Panel>
          {alt?.tried && alt.tried.length > 0 && (
            <Panel title="Options the planner compared" description={`Best result per rack size within ${fmtMoney(alt.spend_limit, farm.currency)} (budget minus reserve). Objective: ${alt.objective ?? 'plant sites'}.`}>
              <Table head={['Rack size', 'Fits in room', 'Affordable', 'Plant sites', 'Setup cost']}>
                {alt.tried.map((t) => (
                  <tr key={t.rack}><td className="font-medium">{t.rack}{alt.rack_name === t.rack && <Badge tone="good" className="ml-2">Chosen</Badge>}</td>
                    <td>{t.max_racks ? `up to ${t.max_racks}` : t.note ?? 'no'}</td>
                    <td>{t.best_racks ? `${t.best_racks} × ${t.best_levels} levels` : 'none within budget'}</td>
                    <td className="tabular-nums">{t.plants ? fmtNum(t.plants) : '—'}</td><td className="tabular-nums">{t.setup ? fmtMoney(t.setup, farm.currency) : '—'}</td></tr>
                ))}
              </Table>
              {alt.notes?.map((n, i) => <p key={i} className="text-[12.5px] text-muted mt-2">{n}</p>)}
            </Panel>
          )}
        </div>
        <div className="space-y-4">
          {controls}
          {planErr && <Callout tone="crit" title="No plan fits">{planErr}</Callout>}
          <Panel title="Most profitable crop?"><p className="text-[13px] text-ink-soft">The AI crop advisor checks your season and local prices, then re-plans for the crop you pick.</p>
            <Link to={`/farms/${farm.id}/crops`} className="block mt-3"><Button className="w-full" variant="subtle" icon={<Sparkles className="size-4" />}>Open AI crop advisor</Button></Link></Panel>
        </div>
      </div>
    </div>
  )
}

export default function PlanPage() {
  return (
    <FarmGate>{(farm) => (
      <>
        <PageHeader crumb={<FarmCrumb farm={farm} page="Budget plan" />} title="Budget plan"
          description="Racks, levels and equipment chosen automatically for the customer's budget. The setup cost never goes over it." />
        <Plan farm={farm} />
      </>
    )}</FarmGate>
  )
}
