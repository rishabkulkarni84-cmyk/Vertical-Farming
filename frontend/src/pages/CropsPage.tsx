import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Check, Info, X } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import AiCropAdvisor from '../components/AiCropAdvisor'
import FarmGate, { FarmCrumb } from '../components/FarmGate'
import { Badge, Button, Callout, ErrorState, PageHeader, Panel, SourceBadge, Spinner, Table } from '../components/ui'
import { get, patch } from '../lib/api'
import { useAction, useInvalidateFarm } from '../lib/hooks'
import { fmtNum } from '../lib/units'
import type { Crop, CropResult, Farm } from '../lib/types'

const FACTOR_LABEL: Record<string, string> = { environment: 'Environment', space: 'Space & capacity', cycle: 'Crop cycle', experience: 'Experience fit', preference: 'Your preference', light: 'Light' }
const range = (r: number[] | null, u = '') => (r ? `${r[0]}–${r[1]}${u}` : 'unknown')

function FactorBars({ r }: { r: CropResult }) {
  return (
    <div className="space-y-1.5">
      {Object.entries(r.factors).map(([k, v]) => (
        <div key={k} className="grid grid-cols-[110px_1fr_36px] items-center gap-2 text-[12px]">
          <span className="text-ink-soft">{FACTOR_LABEL[k]}</span>
          <div className="h-1.5 rounded-full bg-sage-100 overflow-hidden" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(v * 100)} aria-label={FACTOR_LABEL[k]}>
            <div className="h-full bg-forest-600" style={{ width: `${v * 100}%` }} />
          </div>
          <span className="text-muted text-right">{Math.round(r.weights[k] * 100)}%</span>
        </div>
      ))}
    </div>
  )
}

function Crops({ farm }: { farm: Farm }) {
  const { data: rec, isLoading, error, refetch } = useQuery({ queryKey: ['recs', farm.id], queryFn: () => get<{ results: CropResult[]; method: string; model_status: string; note?: string; design_id: number | null }>(`/farms/${farm.id}/recommendations`) })
  const { data: cat } = useQuery({ queryKey: ['crops'], queryFn: () => get<{ crops: Crop[]; provenance: string; last_reviewed: string }>('/crops') })
  const { data: design } = useQuery({ queryKey: ['design', farm.active_design_id], queryFn: () => get<any>(`/designs/${farm.active_design_id}`), enabled: !!farm.active_design_id })
  const [open, setOpen] = useState<string | null>(null)
  const [compare, setCompare] = useState<string[]>([])
  const [showBlocked, setShowBlocked] = useState(false)
  const invalidate = useInvalidateFarm()
  const assign = useAction((slug: string) => patch(`/designs/${farm.active_design_id}`, { crop_slug: slug }), { success: 'Crop assigned to the active design — capacity and costs recalculated', onSuccess: () => invalidate(farm.id) })
  if (isLoading) return <Spinner label="Scoring crops" />
  if (error || !rec) return <ErrorState error={error} retry={refetch} />
  const byslug = Object.fromEntries((cat?.crops ?? []).map((c) => [c.slug, c]))
  const shown = rec.results.filter((r) => r.suitable || showBlocked)
  const cmp = rec.results.filter((r) => compare.includes(r.slug))
  const current = design?.crop_slug

  return (
    <div className="space-y-6">
      <AiCropAdvisor farm={farm} />
      {rec.note && <Callout tone="info">{rec.note} <Link className="underline" to={`/farms/${farm.id}/layout`}>Save a layout</Link> for design-specific scores.</Callout>}
      <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
        <Panel title="Which crops fit your racks (rule-based)" description={`${rec.results.filter((r) => r.suitable).length} suitable of ${rec.results.length}. Select up to three to compare.`}
          actions={<Button size="sm" variant="ghost" onClick={() => setShowBlocked(!showBlocked)}>{showBlocked ? 'Hide' : 'Show'} unsuitable</Button>}>
          <ol className="divide-y divide-line">
            {shown.map((r, i) => {
              const isOpen = open === r.slug
              const c = byslug[r.slug]
              return (
                <li key={r.slug} className="py-3">
                  <div className="flex items-center gap-3">
                    <span className={clsx('font-display text-[22px] font-semibold w-12 text-right tabular-nums', !r.suitable && 'text-muted')}>{r.suitable ? Math.round(r.score) : '—'}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <button className="font-semibold text-[15px] hover:text-forest-700 text-left" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : r.slug)}>{r.name}</button>
                        {i === 0 && r.suitable && <Badge tone="good">Top match</Badge>}
                        {current === r.slug && <Badge tone="info">In design</Badge>}
                        {!r.suitable && <Badge tone="crit"><X className="size-3" />Not suitable</Badge>}
                        <span className="text-[12px] text-muted">{c?.category.toLowerCase()} · {c?.difficulty.toLowerCase()}</span>
                      </div>
                      <div className="text-[13px] text-ink-soft truncate">{r.blockers[0] ?? r.reasons.find((x) => x.startsWith('Space')) ?? r.reasons[0]}</div>
                    </div>
                    <label className="flex items-center gap-1.5 text-[12.5px] text-muted">
                      <input type="checkbox" className="accent-forest-700 size-4" checked={compare.includes(r.slug)} disabled={!compare.includes(r.slug) && compare.length >= 3}
                        onChange={(e) => setCompare(e.target.checked ? [...compare, r.slug] : compare.filter((s) => s !== r.slug))} />Compare
                    </label>
                  </div>
                  {isOpen && (
                    <div className="mt-3 grid gap-5 md:grid-cols-2 sm:pl-[60px]">
                      <div className="space-y-3">
                        <FactorBars r={r} />
                        {r.missing_inputs.length > 0 && <p className="text-[12px] text-warn">Neutral score used for missing: {r.missing_inputs.join(', ')}.</p>}
                      </div>
                      <div className="space-y-2 text-[13px]">
                        <ul className="space-y-1">{(r.blockers.length ? r.blockers : r.reasons).map((x, k) => <li key={k} className="flex gap-2">{r.blockers.length ? <X className="size-3.5 text-crit mt-0.5 shrink-0" /> : <Check className="size-3.5 text-grow mt-0.5 shrink-0" />}{x}</li>)}</ul>
                        {c?.notes && <p className="text-muted">{c.notes}</p>}
                        <div className="flex items-center gap-2 pt-1"><SourceBadge source={r.source_type} />
                          {farm.active_design_id && r.suitable && current !== r.slug && <Button size="sm" onClick={() => assign.mutate(r.slug)} loading={assign.isPending}>Use in design</Button>}</div>
                      </div>
                    </div>
                  )}
                </li>
              )
            })}
          </ol>
        </Panel>
        <div className="space-y-4">
          <Panel title="How scores work"><p className="text-[13px] text-ink-soft leading-relaxed">{rec.method}</p><p className="text-[12.5px] text-muted mt-2">{rec.model_status}</p></Panel>
          <Panel title="Crop data source"><p className="text-[12.5px] text-ink-soft leading-relaxed">{cat?.provenance}</p><p className="text-[12.5px] text-muted mt-2">Last reviewed {cat?.last_reviewed}. Unknown values are shown as “unknown”, never guessed.</p></Panel>
        </div>
      </div>
      {cmp.length >= 2 && (
        <Panel title="Side-by-side">
          <Table head={['', ...cmp.map((c) => c.name)]}>
            {[
              ['Score', (r: CropResult) => (r.suitable ? Math.round(r.score) : 'Not suitable')],
              ['Plant sites in design', (r: CropResult) => fmtNum(r.capacity.total)],
              ['Days to harvest', (r: CropResult) => range(byslug[r.slug]?.days_to_harvest)],
              ['Air temperature', (r: CropResult) => range(byslug[r.slug]?.temp_c, ' °C')],
              ['pH', (r: CropResult) => range(byslug[r.slug]?.ph)],
              ['EC (mS/cm)', (r: CropResult) => range(byslug[r.slug]?.ec_ms_cm)],
              ['Spacing', (r: CropResult) => (byslug[r.slug]?.spacing_m ? `${byslug[r.slug].spacing_m} m` : 'unknown')],
              ['Mature height', (r: CropResult) => (byslug[r.slug]?.mature_height_m ? `${byslug[r.slug].mature_height_m} m` : 'unknown')],
              ['Yield per plant', (r: CropResult) => (byslug[r.slug]?.yield_g_per_plant ? `≈${byslug[r.slug].yield_g_per_plant} g (indicative)` : 'unknown')],
              ['Difficulty', (r: CropResult) => byslug[r.slug]?.difficulty.toLowerCase()],
            ].map(([label, fn]: any) => <tr key={label}><td className="text-muted">{label}</td>{cmp.map((c) => <td key={c.slug} className="font-medium">{fn(c)}</td>)}</tr>)}
          </Table>
        </Panel>
      )}
      <p className="text-[12.5px] text-muted flex items-center gap-1.5"><Info className="size-3.5" />Ranges are indicative catalogue values, not cultivar-specific agronomy advice.</p>
    </div>
  )
}

export default function CropsPage() {
  return (
    <FarmGate>{(farm) => (
      <>
        <PageHeader crumb={<FarmCrumb farm={farm} page="Crops" />} title="Crops" description="AI suggestions for your location, season and budget, plus rule-based scores showing which crops physically fit your racks." />
        <Crops farm={farm} />
      </>
    )}</FarmGate>
  )
}
