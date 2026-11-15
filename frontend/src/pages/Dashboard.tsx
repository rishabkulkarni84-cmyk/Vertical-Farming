import { useQuery } from '@tanstack/react-query'
import { Activity, Plus, Sprout } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge, Button, Empty, ErrorState, PageHeader, Panel, SourceBadge, Spinner } from '../components/ui'
import { get } from '../lib/api'
import { useDisplayUnit, useMe } from '../lib/hooks'
import { fmtLen, fmtMoney, fmtNum, timeAgo } from '../lib/units'
import type { Farm } from '../lib/types'

type DashFarm = Farm & {
  summary: { rack_count: number; capacity: number | null; utilization_pct: number; setup_total: number; monthly_total: number; crop: { name: string } | null; valid: boolean } | null
  simulator: string; open_alerts: number
  latest_reading: { ts: string; source_type: string; temperature_c: number | null; humidity_pct: number | null; ph: number | null; water_level_pct: number | null } | null
}

const STAGES = ['Room', 'Obstacles', 'Layout', 'Crop', 'Monitoring'] as const

function stageOf(f: DashFarm): number {
  if (!f.room) return 0
  if (!f.obstacle_count) return 1
  if (!f.summary) return 2
  if (!f.summary.crop) return 3
  return f.simulator === 'STOPPED' && !f.latest_reading ? 4 : 5
}
const NEXT: Record<number, [string, string]> = { 0: ['setup', 'Enter room size'], 1: ['space', 'Mark door & obstacles'], 2: ['plan', 'Make the budget plan'], 3: ['crops', 'Choose a crop'], 4: ['monitor', 'Start the simulator'], 5: ['insights', 'Review insights'] }

function FarmRow({ f }: { f: DashFarm }) {
  const unit = useDisplayUnit()
  const stage = stageOf(f)
  const [to, label] = NEXT[stage]
  return (
    <article className="grid gap-5 md:grid-cols-[1.3fr_1fr_auto] items-center py-5 first:pt-0 last:pb-0">
      <div className="min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <Link to={`/farms/${f.id}/${f.room ? 'layout' : 'setup'}`} className="font-display text-[19px] font-semibold hover:text-forest-700 truncate">{f.name}</Link>
          {f.is_sample && <Badge tone="info">Sample</Badge>}
          {f.open_alerts > 0 && <Badge tone="crit">{f.open_alerts} open alert{f.open_alerts > 1 ? 's' : ''}</Badge>}
        </div>
        <div className="text-[13px] text-muted mt-0.5">
          {f.room ? `${fmtLen(f.room.length_m, unit)} × ${fmtLen(f.room.width_m, unit)} × ${fmtLen(f.room.height_m, unit)}` : 'Room not measured yet'} · updated {timeAgo(f.updated_at)}
        </div>
        <ol className="mt-3 flex gap-1" aria-label={`Progress: ${stage} of 5 stages complete`}>
          {STAGES.map((s, i) => (
            <li key={s} className="flex-1 min-w-0">
              <div className={`h-1 rounded-full ${i < stage ? 'bg-forest-600' : 'bg-sage-200'}`} />
              <div className={`text-[11.5px] mt-1 truncate ${i < stage ? 'text-ink-soft' : 'text-muted'}`}>{s}</div>
            </li>
          ))}
        </ol>
      </div>
      <dl className="grid grid-cols-3 gap-4 text-[13px]">
        <div><dt className="text-muted">Racks</dt><dd className="font-display text-xl font-semibold">{f.summary?.rack_count ?? '—'}</dd></div>
        <div><dt className="text-muted">Plant sites</dt><dd className="font-display text-xl font-semibold">{fmtNum(f.summary?.capacity)}</dd></div>
        <div><dt className="text-muted">Setup est.</dt><dd className="font-display text-xl font-semibold">{f.summary ? fmtMoney(f.summary.setup_total, f.currency) : '—'}</dd></div>
        {f.latest_reading && (
          <div className="col-span-3 flex items-center gap-2 text-ink-soft">
            <SourceBadge source={f.latest_reading.source_type} />
            {fmtNum(f.latest_reading.temperature_c, 1)} °C · {fmtNum(f.latest_reading.humidity_pct)} % RH · pH {fmtNum(f.latest_reading.ph, 2)}
            <span className="text-muted">({timeAgo(f.latest_reading.ts)})</span>
          </div>
        )}
      </dl>
      <Link to={`/farms/${f.id}/${to}`}><Button variant={stage < 5 ? 'primary' : 'secondary'} size="sm">{label}</Button></Link>
    </article>
  )
}

export default function Dashboard() {
  const { data: me } = useMe()
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ['dashboard'], queryFn: () => get<{ farms: DashFarm[]; open_alerts: number; activity: { action: string; detail: string; created_at: string; farm_id: number | null }[] }>('/dashboard'), refetchInterval: 15000 })
  const first = me?.name?.split(' ')[0]
  return (
    <>
      <PageHeader title={first ? `Good to see you, ${first}` : 'Overview'} description="Plan, build, monitor and optimise each farm. Pick up where you left off."
        actions={<Link to="/farms/new"><Button icon={<Plus className="size-4" />}>New farm</Button></Link>} />
      {isLoading ? <Spinner /> : error ? <ErrorState error={error} retry={refetch} /> : (
        <div className="grid gap-6 xl:grid-cols-[1fr_320px]">
          <Panel title="Your farms" description={`${data!.farms.length} active`}>
            {data!.farms.length === 0 ? (
              <Empty icon={<Sprout className="size-8" />} title="Plan your first farm" action={<Link to="/farms/new"><Button>Start room setup</Button></Link>}>
                Measure the room you have in mind — length, width and ceiling height are enough to begin.
              </Empty>
            ) : <div className="divide-y divide-line">{data!.farms.map((f) => <FarmRow key={f.id} f={f} />)}</div>}
          </Panel>
          <div className="space-y-6">
            <Panel title="Recent activity">
              {data!.activity.length === 0 ? <p className="text-sm text-muted">Nothing yet.</p> : (
                <ul className="space-y-3">
                  {data!.activity.map((a, i) => (
                    <li key={i} className="flex gap-3 text-[13px]">
                      <Activity className="size-3.5 text-sage-500 mt-0.5 shrink-0" aria-hidden />
                      <div className="min-w-0"><div className="text-ink truncate">{a.action.replace('.', ' ')}{a.detail && <span className="text-muted"> — {a.detail}</span>}</div><div className="text-muted text-[12px]">{timeAgo(a.created_at)}</div></div>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
            <Panel title="About the numbers">
              <p className="text-[13px] text-ink-soft leading-relaxed">Layouts and capacity are deterministic calculations from your room. Prices marked <SourceBadge source="ILLUSTRATIVE" /> are placeholders; sensor readings marked <SourceBadge source="SIMULATED" /> come from the software simulator.</p>
              <Link to="/help" className="text-[13px] font-medium text-forest-700 hover:underline mt-2 inline-block">How each value is sourced</Link>
            </Panel>
          </div>
        </div>
      )}
    </>
  )
}
