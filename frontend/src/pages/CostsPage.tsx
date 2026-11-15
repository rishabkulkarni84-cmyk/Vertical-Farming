import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Plus, RefreshCcw, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import FarmGate, { FarmCrumb } from '../components/FarmGate'
import { Badge, Button, Callout, ConfirmDialog, Dialog, ErrorState, Field, Input, KV, PageHeader, Panel, Select, SourceBadge, Spinner, Stat } from '../components/ui'
import { del, download, errorMessage, get, patch, post } from '../lib/api'
import { useAction } from '../lib/hooks'
import { fmtMoney, fmtNum } from '../lib/units'
import type { CostItem, CostView, Farm } from '../lib/types'
import { toast } from 'sonner'

function CellNum({ value, onCommit, label, step = 'any' }: { value: number; onCommit: (v: number) => void; label: string; step?: string }) {
  const [v, setV] = useState(String(value))
  useEffect(() => setV(String(+value.toFixed(4))), [value])
  const commit = () => {
    const n = Number(v)
    if (v === '' || Number.isNaN(n) || n < 0) { setV(String(value)); toast.error(`${label} must be a number ≥ 0`); return }
    if (n !== value) onCommit(n)
  }
  return <input aria-label={label} type="number" min={0} step={step} value={v} onChange={(e) => setV(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
    className="w-24 h-8 rounded border border-line bg-surface px-2 text-right text-[13px] focus:border-forest-600 focus:outline-none" />
}

function Costs({ farm }: { farm: Farm }) {
  const did = farm.active_design_id!
  const qc = useQueryClient()
  const { data: cv, isLoading, error, refetch } = useQuery({ queryKey: ['costs', did], queryFn: () => get<CostView>(`/designs/${did}/costs`) })
  const { data: prices } = useQuery({ queryKey: ['prices', farm.id], queryFn: () => get<any[]>(`/farms/${farm.id}/market-prices`) })
  const { data: mstatus } = useQuery({ queryKey: ['market-status'], queryFn: () => get<{ message: string }>('/market/status') })
  const set = (r: CostView) => { qc.setQueryData(['costs', did], r); qc.invalidateQueries({ queryKey: ['design', did] }); qc.invalidateQueries({ queryKey: ['dashboard'] }) }
  const edit = useAction((v: { id: number; body: Partial<CostItem> }) => patch<CostView>(`/cost-items/${v.id}`, v.body), { onSuccess: set })
  const remove = useAction((id: number) => del<CostView>(`/cost-items/${id}`), { success: 'Line removed', onSuccess: set })
  const regen = useAction((reset: boolean) => post<CostView>(`/designs/${did}/costs/regenerate${reset ? '?reset=true' : ''}`), { success: 'Bill of materials recalculated from the design', onSuccess: set })
  const [adding, setAdding] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [item, setItem] = useState({ name: '', category: 'Other', quantity: '1', unit: 'pcs', unit_price: '', cost_type: 'ONE_TIME' })
  const add = useAction(() => post<CostView>(`/designs/${did}/cost-items`, { ...item, quantity: Number(item.quantity), unit_price: Number(item.unit_price) }),
    { success: 'Line added', onSuccess: (r) => { set(r); setAdding(false); setItem({ ...item, name: '', unit_price: '' }) } })
  const [price, setPrice] = useState('')
  const addPrice = useAction(() => post(`/farms/${farm.id}/market-prices`, { crop_slug: cv!.crop!.slug, price: Number(price), location: farm.room?.market_location || null }),
    { success: 'Price assumption saved', invalidate: [['prices', farm.id], ['costs', did]], onSuccess: () => setPrice('') })

  if (isLoading) return <Spinner label="Calculating costs" />
  if (error || !cv) return <ErrorState error={error} retry={refetch} />
  const cur = cv.currency
  const groups = [['ONE_TIME', 'Setup (one-time)'], ['MONTHLY', 'Running costs (per month)']] as const
  const p = cv.profitability

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-4 rounded-[10px] border border-line bg-surface px-5 py-4">
        <Stat label="Setup total" value={fmtMoney(cv.totals.setup_total, cur)} tone={cv.over_budget ? 'warn' : undefined} sub={cv.budget ? `Budget ${fmtMoney(cv.budget, cur)}${cv.over_budget ? ' — over' : ''}` : 'No budget set'} />
        <Stat label="Running cost / month" value={fmtMoney(cv.totals.monthly_total, cur)} sub="Included recurring lines" />
        <Stat label="Energy / month" value={`${fmtNum(cv.resources.energy_kwh_month)} kWh`} sub={`${cv.resources.light_fixtures} light fixtures, ${cv.resources.photoperiod_h} h/day`} />
        <Stat label="Water / month" value={`${fmtNum(cv.resources.water_l_month)} L`} sub={`for ${fmtNum(cv.capacity.total)} plant sites`} />
      </div>
      {cv.totals.illustrative_lines > 0 && <Callout tone="warn" title={`${cv.totals.illustrative_lines} lines use illustrative prices`}>{cv.price_note} Edit a unit price and it becomes <SourceBadge source="USER_INPUT" />.</Callout>}

      <Panel title="Bill of materials" description="Quantities follow the saved design until you edit them. Totals update as soon as a field loses focus."
        actions={<>
          <Button size="sm" variant="secondary" icon={<Plus className="size-4" />} onClick={() => setAdding(true)}>Add line</Button>
          <Button size="sm" variant="ghost" icon={<RefreshCcw className="size-4" />} onClick={() => setResetting(true)}>Recalculate</Button>
          <Button size="sm" variant="ghost" icon={<Download className="size-4" />} onClick={() => download(`/farms/${farm.id}/bom.csv`, 'bill_of_materials.csv').catch((e) => toast.error(errorMessage(e)))}>CSV</Button>
        </>}>
        {groups.map(([type, title]) => {
          const rows = cv.items.filter((i) => i.cost_type === type)
          const sub = rows.filter((i) => i.included).reduce((s, i) => s + i.subtotal, 0)
          return (
            <div key={type} className="mb-6 last:mb-0">
              <div className="flex items-baseline justify-between mb-1"><h3 className="font-sans text-[13.5px] font-semibold">{title}</h3><span className="text-[13.5px] font-semibold">{fmtMoney(sub, cur)}</span></div>
              <div className="overflow-x-auto">
                <table className="w-full text-[13px]">
                  <thead><tr className="text-left text-[12px] text-muted border-b border-line">
                    <th className="py-2 font-medium w-8"><span className="sr-only">Included</span></th><th className="py-2 font-medium">Item</th><th className="py-2 font-medium text-right">Qty</th><th className="py-2 pl-2 font-medium">Unit</th>
                    <th className="py-2 font-medium text-right">Unit price</th><th className="py-2 font-medium text-right">Subtotal</th><th className="py-2 font-medium pl-3">Source</th><th />
                  </tr></thead>
                  <tbody>
                    {rows.map((i) => (
                      <tr key={i.id} className={`border-b border-line/60 ${!i.included ? 'text-muted' : ''}`}>
                        <td className="py-2"><input type="checkbox" className="accent-forest-700 size-4" aria-label={`Include ${i.name}`} checked={i.included} disabled={i.status === 'FUTURE'} onChange={(e) => edit.mutate({ id: i.id, body: { included: e.target.checked } })} /></td>
                        <td className="py-2 pr-3"><div className="font-medium text-ink">{i.name}</div><div className="text-[12px] text-muted">{i.category}{i.status !== 'REQUIRED' && <> · <Badge tone={i.status === 'FUTURE' ? 'neutral' : 'info'}>{i.status.toLowerCase()}</Badge></>}{i.notes && <> · {i.notes}</>}</div></td>
                        <td className="py-2 text-right"><CellNum label={`Quantity of ${i.name}`} value={i.quantity} onCommit={(v) => edit.mutate({ id: i.id, body: { quantity: v } })} /></td>
                        <td className="py-2 pl-2 text-muted">{i.unit}{i.quantity_locked && i.key && <span title="Quantity edited by you — not auto-updated" className="ml-1">•</span>}</td>
                        <td className="py-2 text-right"><CellNum label={`Unit price of ${i.name}`} value={i.unit_price} onCommit={(v) => edit.mutate({ id: i.id, body: { unit_price: v } })} /></td>
                        <td className="py-2 text-right font-medium tabular-nums">{fmtMoney(i.subtotal, cur)}</td>
                        <td className="py-2 pl-3"><SourceBadge source={i.price_source} /></td>
                        <td className="py-2 text-right"><button className="p-1.5 rounded hover:bg-sage-100" aria-label={`Remove ${i.name}`} onClick={() => remove.mutate(i.id)}><Trash2 className="size-3.5 text-muted" /></button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )
        })}
        <p className="text-[12px] text-muted">{cv.totals.definition}</p>
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Revenue & margin estimate" description={p.available ? p.period : 'Needs a selling price and a yield figure.'}>
          {!cv.crop ? <Callout tone="info">Choose a crop for the design to estimate harvests.</Callout> : p.available ? (
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-4">
                <Stat label="Gross revenue" value={fmtMoney(p.estimated_gross_revenue, cur)} />
                <Stat label="Included costs" value={fmtMoney(p.included_costs, cur)} />
                <Stat label="Margin" value={fmtMoney(p.estimated_margin, cur)} tone={(p.estimated_margin ?? 0) < 0 ? 'crit' : 'good'} />
              </div>
              <KV items={[['Saleable yield per cycle', `${p.estimated_saleable_yield_kg_cycle} kg`], ['Cycle length', `${p.cycle_days} days`], ['Payback on setup', p.payback_months ? `${p.payback_months} months` : 'Not reached'],
                ['Price used', p.price_source ? <span className="flex items-center gap-2 justify-end">{fmtMoney(p.price_source.price, cur)}/kg <SourceBadge source={p.price_source.type} /></span> : '—']]} />
              <ul className="text-[12px] text-muted list-disc pl-4 space-y-0.5">{p.assumptions?.map((a, i) => <li key={i}>{a}</li>)}</ul>
            </div>
          ) : <Callout tone="neutral" title="Not estimated">Missing: {p.missing?.join('; ')}. {p.notes?.[0]}</Callout>}
        </Panel>
        <Panel title="Selling price assumptions" description={mstatus?.message}>
          {cv.crop && (
            <form className="flex items-end gap-2 mb-4" onSubmit={(e) => { e.preventDefault(); if (Number(price) > 0) addPrice.mutate(undefined) }}>
              <div className="flex-1"><Field label={`${cv.crop.name} price per kg`} htmlFor="pp"><Input id="pp" type="number" min="0" step="any" suffix={cur} value={price} onChange={(e) => setPrice(e.target.value)} /></Field></div>
              <Button type="submit" disabled={!(Number(price) > 0)} loading={addPrice.isPending}>Save price</Button>
            </form>
          )}
          {!prices?.length ? <p className="text-[13px] text-muted">No prices entered. Live market data is not connected, so nothing is shown that you didn't enter.</p> : (
            <ul className="divide-y divide-line/70 text-[13px]">{prices.map((m) => (
              <li key={m.id} className="flex items-center gap-2 py-2"><span className="font-medium">{m.crop_slug}</span><span>{fmtMoney(m.price, m.currency)}/{m.unit}</span><SourceBadge source={m.source_type} />
                <span className="text-muted text-[12px]">{m.location ?? ''} {m.observed_on}</span>
                <button className="ml-auto p-1 rounded hover:bg-sage-100" aria-label="Delete price" onClick={async () => { await del(`/market-prices/${m.id}`); qc.invalidateQueries({ queryKey: ['prices', farm.id] }); qc.invalidateQueries({ queryKey: ['costs', did] }) }}><Trash2 className="size-3.5 text-muted" /></button></li>
            ))}</ul>
          )}
        </Panel>
      </div>
      <Panel title="Resource assumptions"><ul className="text-[13px] text-ink-soft list-disc pl-4 space-y-0.5">{cv.resources.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul></Panel>

      <Dialog open={adding} onClose={() => setAdding(false)} title="Add a cost line"
        footer={<><Button variant="secondary" onClick={() => setAdding(false)}>Cancel</Button><Button loading={add.isPending} disabled={!item.name.trim() || item.unit_price === '' || Number(item.unit_price) < 0 || Number(item.quantity) < 0} onClick={() => add.mutate(undefined)}>Add line</Button></>}>
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2"><Field label="Item" htmlFor="in"><Input id="in" value={item.name} maxLength={120} onChange={(e) => setItem({ ...item, name: e.target.value })} /></Field></div>
          <Field label="Category" htmlFor="ic"><Input id="ic" value={item.category} maxLength={40} onChange={(e) => setItem({ ...item, category: e.target.value })} /></Field>
          <Field label="Type" htmlFor="it"><Select id="it" value={item.cost_type} onChange={(e) => setItem({ ...item, cost_type: e.target.value })}><option value="ONE_TIME">One-time</option><option value="MONTHLY">Monthly</option></Select></Field>
          <Field label="Quantity" htmlFor="iq"><Input id="iq" type="number" min="0" step="any" value={item.quantity} onChange={(e) => setItem({ ...item, quantity: e.target.value })} /></Field>
          <Field label="Unit" htmlFor="iu"><Input id="iu" value={item.unit} maxLength={20} onChange={(e) => setItem({ ...item, unit: e.target.value })} /></Field>
          <div className="col-span-2"><Field label="Unit price" htmlFor="ip"><Input id="ip" type="number" min="0" step="any" suffix={cur} value={item.unit_price} onChange={(e) => setItem({ ...item, unit_price: e.target.value })} /></Field></div>
        </div>
      </Dialog>
      <ConfirmDialog open={resetting} onClose={() => setResetting(false)} title="Recalculate the bill of materials?" confirmLabel="Reset to design quantities" danger loading={regen.isPending}
        onConfirm={() => { regen.mutate(true); setResetting(false) }} body="All lines, including your edited prices and custom lines, are replaced with quantities and illustrative prices calculated from the current design." />
    </div>
  )
}

export default function CostsPage() {
  return (
    <FarmGate needDesign>{(farm) => (
      <>
        <PageHeader crumb={<FarmCrumb farm={farm} page="Costs & materials" />} title="Costs & materials" description="Setup and running costs for the active design, separated so you can see what you pay once and what you pay every month." />
        <Costs farm={farm} />
      </>
    )}</FarmGate>
  )
}
