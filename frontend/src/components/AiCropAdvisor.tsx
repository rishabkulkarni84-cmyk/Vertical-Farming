import { useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { ExternalLink, Minus, Sparkles, TrendingDown, TrendingUp } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { get, post } from '../lib/api'
import { useAction, useInvalidateFarm } from '../lib/hooks'
import { fmtMoney, timeAgo } from '../lib/units'
import type { AiSettings, CropAdvice, Farm, PlanResult, SeasonView } from '../lib/types'
import LocationPicker, { SeasonCard } from './LocationPicker'
import { Badge, Button, Callout, Panel, SourceBadge } from './ui'

const TREND = {
  rising: { icon: <TrendingUp className="size-3" />, tone: 'good' as const, label: 'Demand rising' },
  steady: { icon: <Minus className="size-3" />, tone: 'neutral' as const, label: 'Steady demand' },
  falling: { icon: <TrendingDown className="size-3" />, tone: 'warn' as const, label: 'Demand falling' },
  unknown: { icon: null, tone: 'neutral' as const, label: 'Trend unknown' },
}

export default function AiCropAdvisor({ farm }: { farm: Farm }) {
  const qc = useQueryClient()
  const nav = useNavigate()
  const invalidate = useInvalidateFarm()
  const { data: ai } = useQuery({ queryKey: ['ai-settings'], queryFn: () => get<AiSettings>('/ai/settings') })
  const { data: season } = useQuery({ queryKey: ['season', farm.id], queryFn: () => get<SeasonView>(`/farms/${farm.id}/season`) })
  const { data: advice } = useQuery({ queryKey: ['advice', farm.id], queryFn: () => get<CropAdvice | null>(`/farms/${farm.id}/ai/crop-advice`) })
  const [editLoc, setEditLoc] = useState(false)
  const ask = useAction(() => post<CropAdvice>(`/farms/${farm.id}/ai/crop-advice`), { onSuccess: (r) => qc.setQueryData(['advice', farm.id], r), success: 'AI crop advice ready' })
  const apply = useAction((slug: string) => post<PlanResult>(`/farms/${farm.id}/ai/crop-advice/apply`, { slug }), {
    success: (r) => (r.feasible ? `Re-planned for ${r.crop?.name}: ${r.racks?.length} rack(s), ${r.plants} plant sites, ${fmtMoney(r.setup_total, r.currency)}` : r.reason ?? 'No plan fits'),
    onSuccess: (r) => { invalidate(farm.id); qc.invalidateQueries({ queryKey: ['prices', farm.id] }); if (r.feasible) nav(`/farms/${farm.id}/plan`) },
  })
  const hasLoc = !!season && season.location.latitude !== null

  return (
    <Panel title={<span className="flex items-center gap-2"><Sparkles className="size-4 text-forest-700" />AI crop advisor</span>}
      description="Best crops for your location, this season and the budget plan, with current local prices and demand."
      actions={hasLoc && <Button size="sm" variant="ghost" onClick={() => setEditLoc(!editLoc)}>{editLoc ? 'Done' : 'Change location'}</Button>}>
      <div className="space-y-4">
        {!hasLoc || editLoc ? <LocationPicker farmId={farm.id} onDone={() => setEditLoc(false)} /> : season && <SeasonCard v={season} />}
        {!ai?.configured ? (
          <Callout tone="info" title="Add your API key to get AI suggestions">Go to <Link className="underline" to="/settings">Settings → AI assistant</Link>. Until then, the rule-based scores below still show which crops fit your racks.</Callout>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <Button icon={<Sparkles className="size-4" />} loading={ask.isPending} disabled={!hasLoc} onClick={() => ask.mutate(undefined)}>{advice ? 'Ask again' : 'Suggest crops for my location & budget'}</Button>
            {!hasLoc && <span className="text-[13px] text-muted">Set the location first.</span>}
            {ask.isPending && <span className="text-[13px] text-muted">{ai.web_search ? 'Checking current prices and demand on the web…' : 'Thinking…'} this can take up to a minute.</span>}
          </div>
        )}
        {advice && (
          <div className="space-y-3" data-testid="ai-advice">
            <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-muted">
              <SourceBadge source="MODEL" />{advice.web_search && <SourceBadge source="EXTERNAL_DATA" />}
              <span>{advice.model} · {timeAgo(advice.generated_at)} · for {advice.location.name}</span>
            </div>
            {advice.season_summary && <p className="text-[13.5px] text-ink-soft">{advice.season_summary}</p>}
            <ol className="space-y-2">
              {advice.recommendations.map((r) => {
                const t = TREND[(r.demand_trend as keyof typeof TREND)] ?? TREND.unknown
                return (
                  <li key={r.slug} className={clsx('rounded-lg border px-4 py-3', r.rank === 1 ? 'border-forest-700 bg-sage-50' : 'border-line')}>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-display text-lg font-semibold">{r.rank}. {r.name}</span>
                      {r.rank === 1 && <Badge tone="good">Best pick</Badge>}
                      <Badge tone={t.tone}>{t.icon}{t.label}</Badge>
                      {r.price_low && r.price_high && <span className="text-[13px] font-medium">{fmtMoney(r.price_low, advice.currency)}–{fmtMoney(r.price_high, advice.currency)}/kg</span>}
                      {r.season_fit !== null && <span className="text-[12px] text-muted">season fit {Math.round(r.season_fit * 100)}%</span>}
                      <Button size="sm" className="ml-auto" variant={r.rank === 1 ? 'primary' : 'secondary'} loading={apply.isPending && apply.variables === r.slug} onClick={() => apply.mutate(r.slug)}>Use & re-plan</Button>
                    </div>
                    <p className="text-[13.5px] text-ink-soft mt-1">{r.why}</p>
                    <div className="text-[12.5px] text-muted mt-1 space-y-0.5">
                      {r.price_basis && <div>Price basis: {r.price_basis}</div>}
                      {r.best_selling_channel && <div>Sell to: {r.best_selling_channel}</div>}
                      {r.risk && <div>Risk: {r.risk}</div>}
                    </div>
                  </li>
                )
              })}
            </ol>
            {advice.trending_notes.length > 0 && (
              <div className="text-[13px]"><div className="font-semibold mb-1">Trending locally</div><ul className="list-disc pl-5 text-ink-soft space-y-0.5">{advice.trending_notes.map((n, i) => <li key={i}>{n}</li>)}</ul></div>
            )}
            {advice.avoid.length > 0 && <p className="text-[12.5px] text-muted">Avoid now: {advice.avoid.map((a) => `${a.slug} (${a.reason})`).join('; ')}</p>}
            {advice.sources.length > 0 && (
              <div className="text-[12.5px]"><div className="font-semibold mb-1">Sources the AI used</div>
                <ul className="space-y-0.5">{advice.sources.map((s) => <li key={s.url}><a className="text-forest-700 hover:underline inline-flex items-center gap-1" href={s.url} target="_blank" rel="noreferrer">{s.title}<ExternalLink className="size-3" /></a></li>)}</ul></div>
            )}
            <p className="text-[12px] text-muted">{advice.disclaimer} Only crops that physically fit your racks are suggested. Choosing one saves its price as an AI estimate and makes a new budget plan for it.</p>
          </div>
        )}
      </div>
    </Panel>
  )
}
