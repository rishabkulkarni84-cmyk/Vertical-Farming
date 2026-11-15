import { useQuery } from '@tanstack/react-query'
import { Download, FileSpreadsheet, Printer } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import FarmGate, { FarmCrumb } from '../components/FarmGate'
import PlanView from '../components/PlanView'
import { Badge, Button, ErrorState, KV, PageHeader, Panel, SourceBadge, Spinner, Table } from '../components/ui'
import { download, errorMessage, get } from '../lib/api'
import { useDisplayUnit } from '../lib/hooks'
import { FARMING_TYPES, fmtArea, fmtLen, fmtMoney, fmtNum } from '../lib/units'
import type { Farm } from '../lib/types'

function Report({ farm }: { farm: Farm }) {
  const unit = useDisplayUnit()
  const { data: r, isLoading, error, refetch } = useQuery({ queryKey: ['report', farm.id], queryFn: () => get<any>(`/farms/${farm.id}/report`) })
  const [busy, setBusy] = useState<string | null>(null)
  const dl = async (path: string, name: string) => { setBusy(path); try { await download(path, name) } catch (e) { toast.error(errorMessage(e)) } finally { setBusy(null) } }
  if (isLoading) return <Spinner label="Compiling report" />
  if (error || !r) return <ErrorState error={error} retry={refetch} />
  const d = r.design
  const slug = farm.name.replace(/\W+/g, '_')
  return (
    <>
      <div className="flex flex-wrap gap-2 mb-6 print:hidden">
        <Button icon={<Download className="size-4" />} loading={busy === `/farms/${farm.id}/report.pdf`} onClick={() => dl(`/farms/${farm.id}/report.pdf`, `${slug}_plan.pdf`)}>Download PDF</Button>
        <Button variant="secondary" icon={<FileSpreadsheet className="size-4" />} disabled={!d} onClick={() => dl(`/farms/${farm.id}/bom.csv`, `${slug}_bill_of_materials.csv`)}>Bill of materials CSV</Button>
        <Button variant="secondary" icon={<FileSpreadsheet className="size-4" />} onClick={() => dl(`/farms/${farm.id}/sensors/export.csv`, `${slug}_sensors_SIMULATED.csv`)}>Sensor history CSV</Button>
        <Button variant="ghost" icon={<Printer className="size-4" />} onClick={() => window.print()}>Print</Button>
      </div>
      <article className="space-y-6 max-w-5xl">
        <Panel title="Room & grid">
          {r.room ? <div className="grid gap-6 md:grid-cols-2">
            <KV items={[['Dimensions', `${fmtLen(r.room.length_m, unit)} × ${fmtLen(r.room.width_m, unit)} × ${fmtLen(r.room.height_m, unit)}`], ['Floor area', fmtArea(r.room.floor_area_m2, unit)],
              ['Grid', `${r.grid.columns} × ${r.grid.rows} = ${r.grid.full_cells} cells of ${fmtLen(r.grid.cell_m, unit)}`], ['Method', FARMING_TYPES[r.farm.farming_type]],
              ['Obstacles', `${r.obstacles.length} (${r.obstacles.map((o: any) => o.label || o.kind).join(', ') || 'none'})`]]} />
            {d && <PlanView length={r.room.length_m} width={r.room.width_m} unit={unit} obstacles={r.obstacles} racks={d.racks} aisles={Object.values(d.validation.aisles).map((a: any) => a.rect)} height={260} showLayers={{ grid: false }} />}
          </div> : <p className="text-sm text-muted">Room not set up.</p>}
        </Panel>
        {d && (
          <Panel title={`Rack plan — ${d.name}`} description={d.strategy}>
            <div className="grid gap-6 md:grid-cols-2">
              <KV items={[['Racks', d.metrics.rack_count], ['Rack size', `${fmtLen(d.rack_config.rack_length_m, unit)} × ${fmtLen(d.rack_config.rack_depth_m, unit)} × ${fmtLen(d.rack_config.rack_height_m, unit)}`],
                ['Levels', d.rack_config.levels], ['Walkway', fmtLen(d.rack_config.walkway_m, unit)], ['Obstacle clearance', fmtLen(d.rack_config.obstacle_clearance_m, unit)],
                ['Utilisation', `${d.metrics.utilization_pct}%`], ['Plant sites', fmtNum(d.capacity.total)], ['Crop', d.crop?.name ?? 'Not chosen'],
                ['Valid', d.validation.valid ? <Badge tone="good">All constraints pass</Badge> : <Badge tone="crit">Violations</Badge>]]} />
              <Table head={['Rack', 'x', 'y', 'Footprint', 'Access']}>
                {d.racks.map((k: any) => <tr key={k.label}><td className="font-medium">{k.label}</td><td>{fmtLen(k.x, unit)}</td><td>{fmtLen(k.y, unit)}</td><td>{fmtLen(k.w, unit)} × {fmtLen(k.d, unit)}</td><td>{k.access_side ?? '—'}</td></tr>)}
              </Table>
            </div>
          </Panel>
        )}
        {d && (
          <Panel title="Costs" description={d.cost_totals.definition}>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4 text-[13.5px]">
              <div><div className="text-muted">Setup</div><div className="font-display text-xl font-semibold">{fmtMoney(d.cost_totals.setup_total, r.farm.currency)}</div></div>
              <div><div className="text-muted">Monthly</div><div className="font-display text-xl font-semibold">{fmtMoney(d.cost_totals.monthly_total, r.farm.currency)}</div></div>
              <div><div className="text-muted">Energy</div><div className="font-display text-xl font-semibold">{fmtNum(d.resources.energy_kwh_month)} kWh/mo</div></div>
              <div><div className="text-muted">Margin</div><div className="font-display text-xl font-semibold">{d.profitability.available ? fmtMoney(d.profitability.estimated_margin, r.farm.currency) : 'not estimated'}</div></div>
            </div>
            <Table head={['Item', 'Qty', 'Unit price', 'Subtotal', 'Type', 'Source']}>
              {d.cost_items.filter((i: any) => i.included).map((i: any) => <tr key={i.id}><td>{i.name}</td><td>{fmtNum(i.quantity, 2)} {i.unit}</td><td>{fmtMoney(i.unit_price, i.currency)}</td><td>{fmtMoney(i.subtotal, i.currency)}</td><td>{i.cost_type === 'MONTHLY' ? 'monthly' : 'one-time'}</td><td><SourceBadge source={i.price_source} /></td></tr>)}
            </Table>
          </Panel>
        )}
        {r.crop_recommendations && (
          <Panel title="Crop recommendations" description={r.recommendation_method}>
            <Table head={['Crop', 'Score', 'Why']}>
              {r.crop_recommendations.map((c: any) => <tr key={c.name}><td className="font-medium">{c.name}</td><td>{c.suitable ? Math.round(c.score) : 'not suitable'}</td><td className="text-ink-soft">{(c.blockers.length ? c.blockers : c.reasons).slice(0, 2).join(' ')}</td></tr>)}
            </Table>
          </Panel>
        )}
        {r.scenarios.length > 0 && (
          <Panel title="What-if scenarios">
            <Table head={['Scenario', 'Feasible', 'Racks', 'Plant sites', 'Setup cost']}>
              {r.scenarios.map((s: any, i: number) => <tr key={i}><td className="font-medium">{s.name}</td><td>{s.feasible ? 'yes' : 'no'}</td><td>{s.before?.rack_count ?? '—'} → {s.after?.rack_count ?? '—'}</td><td>{fmtNum(s.before?.plant_capacity)} → {fmtNum(s.after?.plant_capacity)}</td><td>{fmtMoney(s.before?.setup_cost, r.farm.currency)} → {fmtMoney(s.after?.setup_cost, r.farm.currency)}</td></tr>)}
            </Table>
          </Panel>
        )}
        <Panel title={<span className="flex items-center gap-2">Monitoring summary <SourceBadge source="SIMULATED" /></span>}>
          <KV items={[['Readings', r.monitoring.records.toLocaleString()], ['Period', r.monitoring.from ? `${new Date(r.monitoring.from).toLocaleString()} – ${new Date(r.monitoring.to).toLocaleString()}` : '—'],
            ['Average temperature', r.monitoring.avg.temperature_c !== null ? `${r.monitoring.avg.temperature_c} °C` : '—'], ['Average humidity', r.monitoring.avg.humidity_pct !== null ? `${r.monitoring.avg.humidity_pct} %` : '—'],
            ['Average pH / EC', `${r.monitoring.avg.ph ?? '—'} / ${r.monitoring.avg.ec_ms_cm ?? '—'} mS/cm`], ['Alerts', `${r.monitoring.alerts_total} total, ${r.monitoring.alerts_open} open`]]} />
        </Panel>
        {r.warnings.length > 0 && <Panel title="Warnings"><ul className="list-disc pl-5 text-[13.5px] space-y-1">{r.warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}</ul></Panel>}
        <Panel title="Assumptions & limitations"><ul className="list-disc pl-5 text-[13.5px] text-ink-soft space-y-1">{r.assumptions.map((a: string, i: number) => <li key={i}>{a}</li>)}</ul></Panel>
      </article>
    </>
  )
}

export default function ReportPage() {
  return (
    <FarmGate>{(farm) => (
      <>
        <PageHeader crumb={<FarmCrumb farm={farm} page="Report & export" />} title="Farm plan report" description="Everything you need to build: dimensions, rack plan, materials, crop reasoning, scenarios and monitoring — with every assumption listed." />
        <Report farm={farm} />
      </>
    )}</FarmGate>
  )
}
