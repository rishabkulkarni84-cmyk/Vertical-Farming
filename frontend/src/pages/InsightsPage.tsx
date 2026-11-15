import { useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { AlertOctagon, AlertTriangle, CheckCheck, Lightbulb, RefreshCcw, X } from 'lucide-react'
import { useState } from 'react'
import FarmGate, { FarmCrumb } from '../components/FarmGate'
import { Badge, Button, Empty, ErrorState, PageHeader, Panel, Segmented, SourceBadge, Spinner } from '../components/ui'
import { get, patch, post } from '../lib/api'
import { useAction } from '../lib/hooks'
import { METRIC_META, timeAgo } from '../lib/units'
import type { Alert, Farm, Insight } from '../lib/types'

const CAT: Record<string, string> = { LAYOUT: 'Layout', CROP: 'Crop', COST: 'Cost', RESOURCE: 'Resources', MONITORING: 'Monitoring', DATA_QUALITY: 'Data quality' }

function Alerts({ farm }: { farm: Farm }) {
  const [status, setStatus] = useState<'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED' | 'ALL'>('OPEN')
  const qc = useQueryClient()
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ['alerts', farm.id, status], queryFn: () => get<Alert[]>(`/farms/${farm.id}/alerts?status=${status}`), refetchInterval: 10000 })
  const set = useAction((v: { id: number; status: Alert['status'] }) => patch(`/alerts/${v.id}`, { status: v.status }), {
    success: (r: any) => `Alert ${r.status.toLowerCase()}`, onSuccess: () => { qc.invalidateQueries({ queryKey: ['alerts', farm.id] }); qc.invalidateQueries({ queryKey: ['dashboard'] }); qc.invalidateQueries({ queryKey: ['alert-summary'] }) } })
  return (
    <Panel title="Monitoring alerts" description="Raised by alert rules on stored readings."
      actions={<Segmented label="Alert status" value={status} onChange={setStatus} options={[{ value: 'OPEN', label: 'Open' }, { value: 'ACKNOWLEDGED', label: 'Acknowledged' }, { value: 'RESOLVED', label: 'Resolved' }, { value: 'ALL', label: 'All' }]} />}>
      {isLoading ? <Spinner /> : error ? <ErrorState error={error} retry={refetch} /> : !data?.length ? (
        <Empty icon={<CheckCheck className="size-8" />} title={status === 'OPEN' ? 'No open alerts' : 'Nothing here'}>{status === 'OPEN' ? 'Readings are within your alert rules. Use “Trigger a test alert” on the monitoring page to check the pipeline.' : 'Alerts with this status will appear here.'}</Empty>
      ) : (
        <ul className="divide-y divide-line">
          {data.map((a) => (
            <li key={a.id} className="py-3 flex gap-3">
              {a.severity === 'CRITICAL' ? <AlertOctagon className="size-5 text-crit shrink-0" aria-hidden /> : <AlertTriangle className="size-5 text-warn shrink-0" aria-hidden />}
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-[14px]">{a.message}</span>
                  <Badge tone={a.severity === 'CRITICAL' ? 'crit' : 'warn'}>{a.severity === 'CRITICAL' ? 'Critical' : 'Warning'}</Badge>
                  <Badge>{a.status.toLowerCase()}</Badge>
                </div>
                <div className="text-[13px] text-ink-soft mt-0.5">{a.suggestion}</div>
                <div className="text-[12px] text-muted mt-1 flex items-center gap-2">{METRIC_META[a.metric]?.label} · {timeAgo(a.created_at)} · <SourceBadge source={a.source_type} /> on <SourceBadge source={a.data_source} /></div>
              </div>
              <div className="flex flex-col gap-1">
                {a.status === 'OPEN' && <Button size="sm" variant="secondary" onClick={() => set.mutate({ id: a.id, status: 'ACKNOWLEDGED' })}>Acknowledge</Button>}
                {a.status !== 'RESOLVED' && <Button size="sm" variant="ghost" onClick={() => set.mutate({ id: a.id, status: 'RESOLVED' })}>Resolve</Button>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

function Insights({ farm }: { farm: Farm }) {
  const qc = useQueryClient()
  const [cat, setCat] = useState<string>('ALL')
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ['insights', farm.id], queryFn: () => get<Insight[]>(`/farms/${farm.id}/insights`) })
  const refresh = useAction(() => post<Insight[]>(`/farms/${farm.id}/insights/refresh`), { success: 'Insights re-evaluated against current data', onSuccess: (r) => qc.setQueryData(['insights', farm.id], r) })
  const dismiss = useAction((id: number) => patch(`/insights/${id}`, {}), { onSuccess: () => qc.invalidateQueries({ queryKey: ['insights', farm.id] }) })
  const cats = ['ALL', ...Array.from(new Set((data ?? []).map((i) => i.category)))]
  const shown = (data ?? []).filter((i) => cat === 'ALL' || i.category === cat)
  return (
    <Panel title="Insights & recommendations" description="Explainable suggestions from rules over your design, costs and stored data. None of these are machine-learning predictions."
      actions={<Button size="sm" variant="secondary" icon={<RefreshCcw className="size-4" />} loading={refresh.isPending} onClick={() => refresh.mutate(undefined)}>Re-evaluate</Button>}>
      {isLoading ? <Spinner /> : error ? <ErrorState error={error} retry={refetch} /> : !data?.length ? (
        <Empty icon={<Lightbulb className="size-8" />} title="No suggestions right now">Your design and data don't trigger any rules.</Empty>
      ) : (
        <>
          <div className="flex flex-wrap gap-1.5 mb-3" role="group" aria-label="Filter by category">
            {cats.map((c) => <button key={c} aria-pressed={cat === c} onClick={() => setCat(c)} className={clsx('h-7 px-2.5 rounded-md text-[12.5px] border', cat === c ? 'bg-forest-800 text-white border-forest-800' : 'border-line text-ink-soft hover:border-line-strong')}>{c === 'ALL' ? 'All' : CAT[c] ?? c}</button>)}
          </div>
          <ul className="space-y-2">
            {shown.map((i) => (
              <li key={i.id} className="rounded-lg border border-line px-4 py-3 flex gap-3">
                <span className={clsx('mt-1.5 size-2 rounded-full shrink-0', i.priority === 'HIGH' ? 'bg-crit' : i.priority === 'MEDIUM' ? 'bg-warn' : 'bg-sage-500')} aria-hidden />
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2"><span className="font-semibold text-[14px]">{i.title}</span><Badge>{CAT[i.category] ?? i.category}</Badge><span className="text-[12px] text-muted">{i.priority.toLowerCase()} priority</span></div>
                  <p className="text-[13px] text-ink-soft mt-0.5">{i.explanation}</p>
                  <p className="text-[13px] mt-1"><span className="text-muted">Suggested: </span>{i.action}</p>
                  <div className="mt-1.5 flex items-center gap-2 text-[12px] text-muted"><SourceBadge source={i.source_type} />{Object.keys(i.evidence).length > 0 && <span className="truncate">Evidence: {Object.entries(i.evidence).map(([k, v]) => `${k.replace(/_/g, ' ')} ${Array.isArray(v) ? v.join(', ') : v}`).join(' · ')}</span>}</div>
                </div>
                <button className="p-1 h-fit rounded hover:bg-sage-100" aria-label={`Dismiss ${i.title}`} onClick={() => dismiss.mutate(i.id)}><X className="size-4 text-muted" /></button>
              </li>
            ))}
          </ul>
        </>
      )}
    </Panel>
  )
}

export default function InsightsPage() {
  return (
    <FarmGate needRoom={false}>{(farm) => (
      <>
        <PageHeader crumb={<FarmCrumb farm={farm} page="Alerts & insights" />} title="Alerts & insights" description="Everything that needs your attention, with the evidence behind it and what to do next." />
        <div className="grid gap-6 2xl:grid-cols-2"><Alerts farm={farm} /><Insights farm={farm} /></div>
      </>
    )}</FarmGate>
  )
}
