import { useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Download, FlaskConical, History, Pause, Play, Square, Table2, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { CartesianGrid, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { toast } from 'sonner'
import FarmGate, { FarmCrumb } from '../components/FarmGate'
import { Badge, Button, Callout, ConfirmDialog, ErrorState, PageHeader, Panel, Segmented, Select, SourceBadge, Spinner, Table } from '../components/ui'
import { del, download, errorMessage, get, patch, post, put } from '../lib/api'
import { useAction } from '../lib/hooks'
import { METRIC_META, fmtNum, timeAgo } from '../lib/units'
import type { Alert, Farm, SensorRecord, SimState, Threshold } from '../lib/types'

const CHART_METRICS = ['temperature_c', 'humidity_pct', 'ph', 'ec_ms_cm', 'water_level_pct', 'light_ppfd'] as const
type Series = { range: string; count: number; points: ({ ts: string } & Record<string, number | null>)[]; source_type: string | null }

function statusOf(v: number | null, t?: Threshold) {
  if (v === null || !t || !t.enabled) return { tone: 'neutral' as const, label: v === null ? 'No reading' : 'No rule' }
  if ((t.crit_min !== null && v < t.crit_min) || (t.crit_max !== null && v > t.crit_max)) return { tone: 'crit' as const, label: 'Critical' }
  if ((t.warn_min !== null && v < t.warn_min) || (t.warn_max !== null && v > t.warn_max)) return { tone: 'warn' as const, label: 'Warning' }
  return { tone: 'good' as const, label: 'In range' }
}

function Reading({ metric, v, t }: { metric: string; v: number | null; t?: Threshold }) {
  const m = METRIC_META[metric]
  const s = statusOf(v, t)
  return (
    <div className={clsx('rounded-lg border bg-surface px-4 py-3', s.tone === 'crit' ? 'border-crit/50' : s.tone === 'warn' ? 'border-warn/50' : 'border-line')}>
      <div className="flex items-center justify-between gap-2"><span className="text-[12.5px] text-muted">{m.label}</span><Badge tone={s.tone}>{s.label}</Badge></div>
      <div className="font-display text-[28px] font-semibold leading-tight mt-1 tabular-nums">{v === null ? '—' : fmtNum(v, m.digits)}<span className="text-[14px] font-sans font-normal text-muted ml-1">{m.unit}</span></div>
      {t && <div className="text-[12px] text-muted">Target {t.warn_max === null ? `≥ ${t.warn_min}` : t.warn_min === null ? `≤ ${t.warn_max}` : `${t.warn_min}–${t.warn_max}`} {m.unit}</div>}
    </div>
  )
}

function MetricChart({ metric, data, t, range }: { metric: string; data: Series['points']; t?: Threshold; range: string }) {
  const m = METRIC_META[metric]
  const fmtT = (iso: string) => { const d = new Date(iso); return range === '7d' ? d.toLocaleDateString(undefined, { weekday: 'short', hour: '2-digit' }) : d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) }
  const has = data.some((p) => p[metric] !== null && p[metric] !== undefined)
  return (
    <figure className="rounded-lg border border-line bg-surface px-3 pt-3 pb-1">
      <figcaption className="flex items-baseline justify-between px-1"><span className="text-[13px] font-semibold">{m.label}</span><span className="text-[11.5px] text-muted">{m.unit}{t?.warn_min !== null && t?.warn_max !== null && t && metric !== 'light_ppfd' ? ' · shaded = target range' : ''}</span></figcaption>
      <div className="h-40">
        {!has ? <div className="h-full grid place-items-center text-[12.5px] text-muted">No readings in this range</div> : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
              <CartesianGrid stroke="#e5ece6" vertical={false} />
              {t && t.warn_min !== null && t.warn_max !== null && metric !== 'light_ppfd' && <ReferenceArea y1={t.warn_min} y2={t.warn_max} fill="#3e8e5e" fillOpacity={0.07} stroke="none" />}
              <XAxis dataKey="ts" tickFormatter={fmtT} tick={{ fontSize: 11, fill: '#66766c' }} axisLine={{ stroke: '#c4cfc6' }} tickLine={false} minTickGap={40} />
              <YAxis tick={{ fontSize: 11, fill: '#66766c' }} axisLine={false} tickLine={false} domain={['auto', 'auto']} width={48} tickFormatter={(v) => fmtNum(v, m.digits)} tickCount={5} />
              <Tooltip cursor={{ stroke: '#8da594', strokeWidth: 1 }} contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #dfe5df' }}
                labelFormatter={(l) => `${new Date(String(l)).toLocaleString()} · simulated`} formatter={(v) => [`${fmtNum(Number(v), m.digits)} ${m.unit}`, m.label]} />
              <Line type="monotone" dataKey={metric} stroke="#285e47" strokeWidth={2} dot={false} activeDot={{ r: 4, stroke: '#fff', strokeWidth: 2 }} connectNulls={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </figure>
  )
}

function ThresholdEditor({ farmId, rows }: { farmId: number; rows: Threshold[] }) {
  const [draft, setDraft] = useState(rows)
  useEffect(() => setDraft(rows), [rows])
  const qc = useQueryClient()
  const save = useAction(() => put<Threshold[]>(`/farms/${farmId}/thresholds`, draft.map(({ basis: _b, ...r }) => r)), { success: 'Alert rules saved', onSuccess: (r) => qc.setQueryData(['thresholds', farmId], r) })
  const reset = useAction(() => post<Threshold[]>(`/farms/${farmId}/thresholds/reset`), { success: 'Rules reset to crop defaults', onSuccess: (r) => qc.setQueryData(['thresholds', farmId], r) })
  const upd = (i: number, k: keyof Threshold, v: string | boolean) => setDraft(draft.map((r, j) => (j === i ? { ...r, [k]: typeof v === 'boolean' ? v : v === '' ? null : Number(v) } : r)))
  const cell = (i: number, k: keyof Threshold, label: string) => (
    <input aria-label={label} type="number" step="any" value={(draft[i][k] as number | null) ?? ''} onChange={(e) => upd(i, k, e.target.value)}
      className="w-20 h-8 rounded border border-line px-2 text-right text-[13px] focus:border-forest-600 focus:outline-none" />
  )
  return (
    <Panel title="Alert rules" description="Rule-based thresholds. Defaults come from the crop catalogue when known — they are starting points, not universal standards."
      actions={<><Button size="sm" variant="ghost" onClick={() => reset.mutate(undefined)} loading={reset.isPending}>Reset</Button><Button size="sm" onClick={() => save.mutate(undefined)} loading={save.isPending}>Save rules</Button></>}>
      <Table head={['Metric', 'Critical below', 'Warn below', 'Warn above', 'Critical above', 'On', 'Basis']}>
        {draft.map((t, i) => {
          const m = METRIC_META[t.metric]
          return (
            <tr key={t.metric}>
              <td className="font-medium whitespace-nowrap">{m.label} <span className="text-muted font-normal">{m.unit}</span></td>
              <td>{cell(i, 'crit_min', `${m.label} critical minimum`)}</td><td>{cell(i, 'warn_min', `${m.label} warning minimum`)}</td>
              <td>{cell(i, 'warn_max', `${m.label} warning maximum`)}</td><td>{cell(i, 'crit_max', `${m.label} critical maximum`)}</td>
              <td><input type="checkbox" className="accent-forest-700 size-4" aria-label={`${m.label} rule enabled`} checked={t.enabled} onChange={(e) => upd(i, 'enabled', e.target.checked)} /></td>
              <td className="text-[12px] text-muted min-w-40">{t.basis}</td>
            </tr>
          )
        })}
      </Table>
    </Panel>
  )
}

function Monitor({ farm }: { farm: Farm }) {
  const qc = useQueryClient()
  const { data: sim, error: simErr } = useQuery({ queryKey: ['sim', farm.id], queryFn: () => get<SimState>(`/farms/${farm.id}/simulator`), refetchInterval: (q) => (q.state.data?.status === 'RUNNING' ? 3000 : false) })
  const running = sim?.status === 'RUNNING'
  const [range, setRange] = useState<'1h' | '6h' | '24h' | '7d'>('1h')
  const [table, setTable] = useState(false)
  const [clearing, setClearing] = useState(false)
  const poll = running ? 3000 : false
  const { data: latest } = useQuery({ queryKey: ['latest', farm.id], queryFn: () => get<SensorRecord | null>(`/farms/${farm.id}/sensors/latest`), refetchInterval: poll })
  const { data: series } = useQuery({ queryKey: ['series', farm.id, range], queryFn: () => get<Series>(`/farms/${farm.id}/sensors/series?range=${range}`), refetchInterval: poll })
  const { data: thresholds } = useQuery({ queryKey: ['thresholds', farm.id], queryFn: () => get<Threshold[]>(`/farms/${farm.id}/thresholds`) })
  const { data: recent } = useQuery({ queryKey: ['records', farm.id], queryFn: () => get<{ items: SensorRecord[]; total: number }>(`/farms/${farm.id}/sensors?limit=12`), refetchInterval: poll })
  const { data: alerts } = useQuery({ queryKey: ['alerts', farm.id, 'OPEN'], queryFn: () => get<Alert[]>(`/farms/${farm.id}/alerts?status=OPEN&limit=5`), refetchInterval: poll })
  const refresh = () => ['sim', 'latest', 'series', 'records', 'alerts', 'dashboard', 'alert-summary', 'insights'].forEach((k) => qc.invalidateQueries({ queryKey: k === 'dashboard' || k === 'alert-summary' ? [k] : [k, farm.id] }))
  const ctl = useAction((a: 'start' | 'pause' | 'stop') => post<SimState>(`/farms/${farm.id}/simulator/${a}`), { success: (r) => `Simulator ${r.status.toLowerCase()}`, onSuccess: refresh })
  const setMode = useAction((body: Partial<SimState>) => patch<SimState>(`/farms/${farm.id}/simulator`, body), { onSuccess: refresh })
  const backfill = useAction(() => post<{ generated: number }>(`/farms/${farm.id}/simulator/backfill?hours=24`), { success: (r) => `${r.generated} simulated readings added for the last 24 h`, onSuccess: refresh })
  const test = useAction(() => post<{ alerts_created: Alert[] }>(`/farms/${farm.id}/alerts/test`), { success: (r) => `Test reading injected — ${r.alerts_created.length} alert(s) raised`, onSuccess: refresh })
  const clear = useAction(() => del(`/farms/${farm.id}/sensors`), { success: 'Sensor history and alerts cleared', onSuccess: () => { setClearing(false); refresh() } })
  const tmap = Object.fromEntries((thresholds ?? []).map((t) => [t.metric, t]))

  if (simErr) return <ErrorState error={simErr} />
  if (!sim) return <Spinner label="Loading simulator" />
  return (
    <div className="space-y-6">
      <div className="rounded-[10px] border border-sim/30 bg-sim-soft/50 px-5 py-4 flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <SourceBadge source="SIMULATED" />
          <div className="text-[13.5px]">
            <div className="font-semibold">Simulator {sim.status.toLowerCase()}{running && ` · new reading every ${sim.interval_s}s`}</div>
            <div className="text-muted text-[12.5px]">{sim.record_count.toLocaleString()} stored readings · {sim.last_tick_at ? `last ${timeAgo(sim.last_tick_at)}` : 'no readings yet'} · {sim.data_flow}</div>
          </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {running ? <Button size="sm" variant="secondary" icon={<Pause className="size-4" />} onClick={() => ctl.mutate('pause')}>Pause</Button>
            : <Button size="sm" icon={<Play className="size-4" />} onClick={() => ctl.mutate('start')} loading={ctl.isPending}>{sim.status === 'PAUSED' ? 'Resume' : 'Start'}</Button>}
          <Button size="sm" variant="secondary" icon={<Square className="size-3.5" />} onClick={() => ctl.mutate('stop')} disabled={sim.status === 'STOPPED'}>Stop</Button>
          <label className="sr-only" htmlFor="mode">Test condition</label>
          <Select id="mode" className="h-8 w-48! text-[13px]" value={sim.mode} onChange={(e) => setMode.mutate({ mode: e.target.value as SimState['mode'] })}>
            <option value="NORMAL">Normal conditions</option><option value="WARNING">Drift to warning</option><option value="ABNORMAL">Abnormal (critical)</option>
          </Select>
          <label className="sr-only" htmlFor="interval">Interval</label>
          <Select id="interval" className="h-8 w-32! text-[13px]" value={sim.interval_s} onChange={(e) => setMode.mutate({ interval_s: Number(e.target.value) })}>
            {[2, 5, 10, 30, 60].map((s) => <option key={s} value={s}>Every {s}s</option>)}
          </Select>
        </div>
      </div>
      <p className="text-[12.5px] text-muted -mt-3">Targets: {sim.target_basis} Physical sensors (ESP32 → MQTT) are not connected in this version.</p>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6">
        {(['temperature_c', 'humidity_pct', 'ph', 'ec_ms_cm', 'water_level_pct'] as const).map((k) => <Reading key={k} metric={k} v={latest?.[k] ?? null} t={tmap[k]} />)}
        <div className="rounded-lg border border-line bg-surface px-4 py-3 text-[13px] space-y-1.5">
          <div className="text-[12.5px] text-muted">Equipment (simulated)</div>
          <div className="flex justify-between"><span>Pump</span><Badge tone={latest?.pump_on ? 'good' : 'neutral'}>{latest ? (latest.pump_on ? 'Running' : 'Off') : '—'}</Badge></div>
          <div className="flex justify-between"><span>Fan</span><Badge tone={latest?.fan_on ? 'good' : 'neutral'}>{latest ? (latest.fan_on ? 'Running' : 'Off') : '—'}</Badge></div>
          <div className="flex justify-between"><span>Lights</span><Badge tone={latest?.light_ppfd ? 'good' : 'neutral'}>{latest ? (latest.light_ppfd ? `${fmtNum(latest.light_ppfd)} PPFD` : 'Off') : '—'}</Badge></div>
        </div>
      </div>

      {alerts && alerts.length > 0 && (
        <Callout tone={alerts.some((a) => a.severity === 'CRITICAL') ? 'crit' : 'warn'} title={`${alerts.length} open alert${alerts.length > 1 ? 's' : ''}`}>
          <ul className="space-y-0.5">{alerts.map((a) => <li key={a.id}><b className="font-medium text-ink">{a.message}</b> {a.suggestion}</li>)}</ul>
        </Callout>
      )}

      <Panel title="History" description={series ? `${series.count.toLocaleString()} stored readings in range, averaged into buckets.` : undefined}
        actions={<>
          <Segmented label="Time range" value={range} onChange={setRange} options={[{ value: '1h', label: '1 h' }, { value: '6h', label: '6 h' }, { value: '24h', label: '24 h' }, { value: '7d', label: '7 d' }]} />
          <Button size="sm" variant="ghost" icon={<Table2 className="size-4" />} aria-pressed={table} onClick={() => setTable(!table)}>{table ? 'Charts' : 'Table'}</Button>
        </>}>
        {!series ? <Spinner /> : series.count === 0 ? (
          <div className="py-10 text-center text-[13.5px] text-muted">No readings yet. Start the simulator, or add 24 hours of simulated history to see the charts.
            <div className="mt-3"><Button size="sm" variant="secondary" icon={<History className="size-4" />} loading={backfill.isPending} onClick={() => backfill.mutate(undefined)}>Add 24 h of simulated history</Button></div></div>
        ) : table ? (
          <Table head={['Time', 'Source', ...CHART_METRICS.map((m) => `${METRIC_META[m].label}`)]}>
            {recent?.items.map((r) => <tr key={r.id}><td className="whitespace-nowrap">{new Date(r.ts).toLocaleString()}</td><td><SourceBadge source={r.source_type} /></td>{CHART_METRICS.map((m) => <td key={m} className="tabular-nums">{fmtNum(r[m], METRIC_META[m].digits)}</td>)}</tr>)}
          </Table>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{CHART_METRICS.map((m) => <MetricChart key={m} metric={m} data={series.points} t={tmap[m]} range={range} />)}</div>
        )}
      </Panel>

      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" size="sm" icon={<FlaskConical className="size-4" />} loading={test.isPending} onClick={() => test.mutate(undefined)}>Trigger a test alert</Button>
        <Button variant="secondary" size="sm" icon={<History className="size-4" />} loading={backfill.isPending} onClick={() => backfill.mutate(undefined)}>Add 24 h simulated history</Button>
        <Button variant="secondary" size="sm" icon={<Download className="size-4" />} onClick={() => download(`/farms/${farm.id}/sensors/export.csv`, 'sensor_history_SIMULATED.csv').catch((e) => toast.error(errorMessage(e)))}>Export CSV</Button>
        <Button variant="ghost" size="sm" icon={<Trash2 className="size-4" />} onClick={() => setClearing(true)}>Clear history</Button>
      </div>

      {thresholds && <ThresholdEditor farmId={farm.id} rows={thresholds} />}
      <ConfirmDialog open={clearing} onClose={() => setClearing(false)} danger title="Clear sensor history?" confirmLabel="Delete all readings" loading={clear.isPending}
        onConfirm={() => clear.mutate(undefined)} body="All stored simulated readings and alerts for this farm are deleted. Alert rules are kept." />
    </div>
  )
}

export default function MonitorPage() {
  return (
    <FarmGate>{(farm) => (
      <>
        <PageHeader crumb={<FarmCrumb farm={farm} page="Monitoring" />} title="Monitoring" description="A working monitoring pipeline fed by a software simulator. Every reading is stored and labelled simulated — nothing here comes from physical sensors." />
        <Monitor farm={farm} />
      </>
    )}</FarmGate>
  )
}
