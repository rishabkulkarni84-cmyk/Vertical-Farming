import { useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Camera, Check, ImageUp, Sparkles, Trash2, Wand2 } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import LocationPicker, { SeasonCard } from '../components/LocationPicker'
import { Badge, Button, Callout, Field, Input, KV, PageHeader, Panel, Select, SourceBadge, Spinner } from '../components/ui'
import { api, del, errorMessage, get, patch, post, put } from '../lib/api'
import { FARMING_TYPES, fmtMoney, toM } from '../lib/units'
import type { AiSettings, Crop, Farm, PlanResult, RoomAi, SeasonView, Unit } from '../lib/types'

const STEPS = ['Basics', 'Location', 'Room photo', 'Room size', 'Budget', 'Review'] as const
const CURRENCIES = ['INR', 'USD', 'EUR', 'GBP', 'AED', 'SGD', 'AUD', 'CAD']

export type Room = { length: string; width: string; height: string; unit: Unit; grid_cell: string; grid_cell_unit: Unit; temperature_c: string; humidity_pct: string; light_source: string; water_access: string; electrical_access: string; market_location: string; notes: string }
type Basics = { name: string; farming_type: string; experience_level: string; preferred_crop: string; crop_categories: string[]; budget: string; currency: string; fx_rate_per_usd: string; electricity_rate: string }

const emptyRoom: Room = { length: '', width: '', height: '', unit: 'ft', grid_cell: '1', grid_cell_unit: 'ft', temperature_c: '', humidity_pct: '', light_source: 'GROW_LIGHTS', water_access: '', electrical_access: '', market_location: '', notes: '' }
const emptyBasics: Basics = { name: '', farming_type: 'HYDROPONIC_NFT', experience_level: 'BEGINNER', preferred_crop: '', crop_categories: [], budget: '', currency: 'INR', fx_rate_per_usd: '1', electricity_rate: '' }

const num = (s: string) => (s.trim() === '' ? null : Number(s))
const tri = (s: string) => (s === '' ? null : s === 'yes')
const trim = (v: number, u: Unit) => String(+(v / ({ m: 1, cm: 0.01, ft: 0.3048, in: 0.0254 }[u])).toFixed(u === 'm' ? 2 : 1))

export function validateRoom(r: Room): Record<string, string> {
  const e: Record<string, string> = {}
  const L = num(r.length), W = num(r.width), H = num(r.height), G = num(r.grid_cell)
  for (const [k, v] of [['length', L], ['width', W], ['height', H]] as const) {
    if (v === null || Number.isNaN(v)) e[k] = 'Required'
    else if (v <= 0) e[k] = 'Must be greater than 0'
  }
  if (!e.length && (toM(L!, r.unit) < 0.5 || toM(L!, r.unit) > 100)) e.length = 'Between 0.5 m and 100 m'
  if (!e.width && (toM(W!, r.unit) < 0.5 || toM(W!, r.unit) > 100)) e.width = 'Between 0.5 m and 100 m'
  if (!e.height && (toM(H!, r.unit) < 1 || toM(H!, r.unit) > 20)) e.height = 'Ceiling must be between 1 m and 20 m'
  if (G === null || Number.isNaN(G) || G <= 0) e.grid_cell = 'Required'
  else if (!e.length && !e.width && (toM(G, r.grid_cell_unit) < 0.05 || toM(G, r.grid_cell_unit) > Math.min(toM(L!, r.unit), toM(W!, r.unit)))) e.grid_cell = 'At least 5 cm and no larger than the shorter wall'
  const t = num(r.temperature_c), h = num(r.humidity_pct)
  if (t !== null && (t < -20 || t > 60)) e.temperature_c = 'Between −20 and 60 °C'
  if (h !== null && (h < 0 || h > 100)) e.humidity_pct = 'Between 0 and 100 %'
  return e
}

function Stepper({ step, maxReached, go }: { step: number; maxReached: number; go: (i: number) => void }) {
  return (
    <ol className="flex flex-wrap gap-x-1 gap-y-2 mb-6" aria-label="Setup steps">
      {STEPS.map((s, i) => {
        const done = i < step, cur = i === step, reach = i <= maxReached
        return (
          <li key={s} className="flex items-center">
            <button type="button" disabled={!reach} onClick={() => go(i)} aria-current={cur ? 'step' : undefined}
              className={clsx('flex items-center gap-2 rounded-full pl-1 pr-3 h-8 text-[13px] transition-colors', cur ? 'bg-forest-800 text-white' : reach ? 'text-ink hover:bg-sage-100' : 'text-muted')}>
              <span className={clsx('size-6 rounded-full grid place-items-center text-[11.5px] font-semibold', cur ? 'bg-white text-forest-800' : done ? 'bg-forest-600 text-white' : 'bg-sage-200 text-ink-soft')}>
                {done ? <Check className="size-3.5" /> : i + 1}
              </span>{s}
            </button>
            {i < STEPS.length - 1 && <span aria-hidden className="w-4 h-px bg-line-strong mx-1" />}
          </li>
        )
      })}
    </ol>
  )
}

function YesNo({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  const id = useId()
  return <Field label={label} htmlFor={id}><Select id={id} value={value} onChange={(e) => onChange(e.target.value)}><option value="">Not sure</option><option value="yes">Yes</option><option value="no">No</option></Select></Field>
}

function PhotoStep({ farmId, unit, onApplied }: { farmId: number; unit: Unit; onApplied: (f: Farm) => void }) {
  const qc = useQueryClient()
  const { data: ai } = useQuery({ queryKey: ['ai-settings'], queryFn: () => get<AiSettings>('/ai/settings') })
  const { data: imgs, isLoading } = useQuery({ queryKey: ['images', farmId], queryFn: () => get<any[]>(`/farms/${farmId}/images`) })
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const analyze = async (id: number) => {
    setErr(null); setBusy('ai')
    try { await post<RoomAi>(`/images/${id}/ai-analyze`); qc.invalidateQueries({ queryKey: ['images', farmId] }) }
    catch (e) { setErr(errorMessage(e)) } finally { setBusy(null) }
  }
  const upload = async (f: File | undefined) => {
    if (!f) return
    setErr(null)
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(f.type)) return setErr('Use a JPEG, PNG or WebP photo.')
    if (f.size > 8 * 1024 * 1024) return setErr('Photo must be 8 MB or smaller.')
    const fd = new FormData()
    fd.append('file', f)
    setBusy('upload')
    try {
      const img = await api<{ id: number }>(`/farms/${farmId}/images`, { method: 'POST', form: fd })
      qc.invalidateQueries({ queryKey: ['images', farmId] })
      setBusy(null)
      if (ai?.configured) await analyze(img.id)
    } catch (e) { setErr(errorMessage(e)); setBusy(null) }
  }
  const apply = async (id: number) => {
    setBusy('apply')
    try {
      const r = await post<{ applied: { dimensions: boolean; objects: number }; farm: Farm }>(`/images/${id}/ai-apply`, { dimensions: true, objects: true, unit })
      toast.success(`Filled in ${r.applied.dimensions ? 'room size' : ''}${r.applied.dimensions && r.applied.objects ? ' and ' : ''}${r.applied.objects ? `${r.applied.objects} objects` : ''} — please check them`)
      qc.invalidateQueries({ queryKey: ['farm', farmId] }); qc.invalidateQueries({ queryKey: ['obstacles', farmId] })
      onApplied(r.farm)
    } catch (e) { setErr(errorMessage(e)) } finally { setBusy(null) }
  }
  const latest = imgs?.[0]
  const res: RoomAi | undefined = latest?.analysis?.ai
  return (
    <div className="space-y-4">
      <p className="text-[14px] text-ink-soft max-w-2xl">Take or upload one photo of the room from a corner, showing as much floor and wall as possible. {ai?.configured ? 'The AI will estimate the room size and pick out doors, windows and furniture for you.' : ''}</p>
      {!ai?.configured && <Callout tone="info" title="AI photo reading is off">Add your API key in <Link className="underline" to="/settings">Settings → AI assistant</Link> to fill in the room automatically. You can still enter everything by hand.</Callout>}
      {err && <Callout tone="crit">{err}</Callout>}
      <label className={clsx('flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-line-strong bg-sage-50 py-9 cursor-pointer hover:border-forest-600', busy && 'opacity-60 pointer-events-none')}>
        <ImageUp className="size-7 text-sage-500" aria-hidden />
        <span className="text-sm font-medium">{busy === 'upload' ? 'Uploading…' : busy === 'ai' ? 'AI is reading the photo…' : 'Take a photo or choose one'}</span>
        <span className="text-[12px] text-muted">JPEG, PNG or WebP, up to 8 MB</span>
        <input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" className="sr-only" data-testid="photo-input" onChange={(e) => upload(e.target.files?.[0])} />
      </label>
      <p className="text-[12px] text-muted flex items-center gap-1.5"><Camera className="size-3.5" />On phones and tablets this opens the camera.</p>
      {isLoading ? <Spinner /> : latest && (
        <div className="rounded-lg border border-line p-3 space-y-3">
          <div className="flex gap-4 items-start">
            <img src={latest.url} alt="Room photo" className="w-44 h-32 object-cover rounded" />
            <div className="flex-1 min-w-0 text-[13px]">
              <div className="font-medium truncate">{latest.original_name}</div>
              <ul className="mt-1 space-y-0.5 text-ink-soft">{latest.analysis?.quality_checks?.map((q: any, k: number) => <li key={k}>{q.message}</li>)}</ul>
              {ai?.configured && !res && <Button className="mt-2" size="sm" icon={<Sparkles className="size-4" />} loading={busy === 'ai'} onClick={() => analyze(latest.id)}>Read photo with AI</Button>}
            </div>
            <Button size="sm" variant="ghost" aria-label="Delete photo" icon={<Trash2 className="size-4" />} onClick={async () => { await del(`/images/${latest.id}`); qc.invalidateQueries({ queryKey: ['images', farmId] }) }} />
          </div>
          {res && (
            <div className="rounded-md bg-sage-50 px-4 py-3 text-[13.5px] space-y-2" data-testid="ai-result">
              <div className="flex items-center gap-2 font-semibold"><Sparkles className="size-4 text-forest-700" />What the AI sees <SourceBadge source="MODEL" /><span className="text-[12px] font-normal text-muted">{res.model}</span></div>
              <p className="text-ink-soft">{res.summary}</p>
              <KV items={[
                ['Room size (estimate)', res.room.length_m ? `${res.room.length_m} × ${res.room.width_m} × ${res.room.height_m} m · ${res.room.confidence} confidence` : 'Could not estimate'],
                ['Scale based on', res.room.basis || '—'],
                ['Natural light', `${res.light.natural_light}${res.light.notes ? ` — ${res.light.notes}` : ''}`],
                ['Objects found', res.objects.length ? res.objects.map((o) => o.label).join(', ') : 'None'],
                ['Power sockets / water seen', `${res.power_outlets_visible === null ? '?' : res.power_outlets_visible ? 'yes' : 'no'} / ${res.water_source_visible === null ? '?' : res.water_source_visible ? 'yes' : 'no'}`],
              ]} />
              {res.warnings.map((w, i) => <p key={i} className="text-[12.5px] text-warn">{w}</p>)}
              <div className="flex flex-wrap gap-2 pt-1">
                <Button size="sm" icon={<Wand2 className="size-4" />} loading={busy === 'apply'} onClick={() => apply(latest.id)}>Use these details</Button>
                <Button size="sm" variant="ghost" loading={busy === 'ai'} onClick={() => analyze(latest.id)}>Read again</Button>
              </div>
              <p className="text-[12px] text-muted">One photo can't measure a room exactly. You'll check the size on the next step, and objects are added to the plan as unconfirmed suggestions.</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function SetupWizard() {
  const { farmId } = useParams()
  const isNew = !farmId
  const id = farmId ? Number(farmId) : null
  const nav = useNavigate()
  const qc = useQueryClient()
  const { data: farm, isLoading } = useQuery({ queryKey: ['farm', id], queryFn: () => get<Farm>(`/farms/${id}`), enabled: !!id })
  const { data: crops } = useQuery({ queryKey: ['crops'], queryFn: () => get<{ crops: Crop[] }>('/crops') })
  const { data: season } = useQuery({ queryKey: ['season', id], queryFn: () => get<SeasonView>(`/farms/${id}/season`), enabled: !!id })
  const [step, setStep] = useState(0)
  const [maxReached, setMax] = useState(0)
  const [b, setB] = useState<Basics>(emptyBasics)
  const [r, setR] = useState<Room>(emptyRoom)
  const [aiFilled, setAiFilled] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [planErr, setPlanErr] = useState<string | null>(null)

  const roomToState = (rm: NonNullable<Farm['room']>): Room => ({
    length: trim(rm.length_m, rm.input_unit), width: trim(rm.width_m, rm.input_unit), height: trim(rm.height_m, rm.input_unit), unit: rm.input_unit,
    grid_cell: String(rm.grid_cell ?? 1), grid_cell_unit: rm.grid_cell_unit, temperature_c: rm.temperature_c?.toString() ?? '', humidity_pct: rm.humidity_pct?.toString() ?? '',
    light_source: rm.light_source, water_access: rm.water_access === null ? '' : rm.water_access ? 'yes' : 'no', electrical_access: rm.electrical_access === null ? '' : rm.electrical_access ? 'yes' : 'no',
    market_location: rm.market_location ?? '', notes: rm.notes ?? '' })

  const initFor = useRef<number | null>(null)
  useEffect(() => {
    if (!farm || initFor.current === farm.id) return // initialise once per farm; refetches must not reset the step
    initFor.current = farm.id
    setB({ name: farm.name, farming_type: farm.farming_type, experience_level: farm.experience_level, preferred_crop: farm.preferred_crop ?? '', crop_categories: farm.crop_categories,
      budget: farm.budget?.toString() ?? '', currency: farm.currency, fx_rate_per_usd: String(farm.fx_rate_per_usd), electricity_rate: farm.electricity_rate?.toString() ?? '' })
    if (farm.room) { setR(roomToState(farm.room)); setAiFilled(!!farm.room.notes?.includes('estimated by AI')) }
    const s = Math.min(farm.wizard_step, STEPS.length - 1)
    setMax((m) => Math.max(m, s, farm.room ? 5 : 1))
    setStep((cur) => (cur > 0 ? cur : farm.room && farm.wizard_step >= 5 ? 0 : s))
  }, [farm])

  const roomBody = () => ({ length: num(r.length), width: num(r.width), height: num(r.height), unit: r.unit, grid_cell: num(r.grid_cell), grid_cell_unit: r.grid_cell_unit,
    temperature_c: num(r.temperature_c), humidity_pct: num(r.humidity_pct), light_source: r.light_source, water_access: tri(r.water_access), electrical_access: tri(r.electrical_access),
    market_location: r.market_location || farm?.location?.name || null, notes: r.notes || null })
  const budgetBody = () => ({ budget: num(b.budget), currency: b.currency.toUpperCase(), fx_rate_per_usd: b.currency === 'INR' || b.currency === 'USD' ? 1 : num(b.fx_rate_per_usd) ?? 1,
    electricity_rate: num(b.electricity_rate), preferred_crop: b.preferred_crop || null, crop_categories: b.crop_categories })

  const validate = (s: number) => {
    let e: Record<string, string> = {}
    if (s === 0 && !b.name.trim()) e.name = 'Give the farm a name'
    if (s === 3) e = validateRoom(r)
    if (s === 4) {
      const bud = num(b.budget)
      if (bud === null || Number.isNaN(bud)) e.budget = 'Enter the budget — the plan is built from it'
      else if (bud <= 0) e.budget = 'Must be greater than 0'
      if (b.currency !== 'INR' && b.currency !== 'USD' && !(num(b.fx_rate_per_usd)! > 0)) e.fx_rate_per_usd = 'Needed to convert sample prices'
    }
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const next = async () => {
    if (!validate(step)) return
    setSaving(true)
    try {
      let fid = id
      if (step === 0) {
        const body = { name: b.name.trim(), farming_type: b.farming_type, experience_level: b.experience_level }
        if (isNew) {
          const f = await post<Farm>('/farms', { ...body, currency: 'INR', wizard_step: 1 })
          fid = f.id
          qc.invalidateQueries({ queryKey: ['farms'] })
          nav(`/farms/${f.id}/setup`, { replace: true })
        } else await patch(`/farms/${fid}`, body)
      }
      if (step === 3) await put(`/farms/${fid}/room`, roomBody())
      if (step === 4) await patch(`/farms/${fid}`, budgetBody())
      const ns = Math.min(step + 1, STEPS.length - 1)
      if (fid && !isNew) await patch(`/farms/${fid}`, { wizard_step: Math.max(ns, farm?.wizard_step ?? 0) })
      qc.invalidateQueries({ queryKey: ['farm', fid] })
      setStep(ns)
      setMax((m) => Math.max(m, ns))
    } catch (e) {
      toast.error(errorMessage(e))
    } finally { setSaving(false) }
  }

  const createPlan = async () => {
    setSaving(true); setPlanErr(null)
    try {
      const p = await post<PlanResult>(`/farms/${id}/autoplan`, { reserve_pct: 5 })
      if (!p.feasible) { setPlanErr(p.reason ?? 'No plan fits this budget.'); return }
      qc.invalidateQueries({ queryKey: ['farm', id] }); qc.invalidateQueries({ queryKey: ['dashboard'] })
      toast.success(`Plan ready: ${p.racks?.length} rack(s), ${p.plants} plant sites for ${fmtMoney(p.setup_total, p.currency)}`)
      nav(`/farms/${id}/plan`)
    } catch (e) { setPlanErr(errorMessage(e)) } finally { setSaving(false) }
  }

  if (!isNew && isLoading) return <Spinner label="Loading farm" />
  const L = num(r.length), W = num(r.width), G = num(r.grid_cell)
  const cells = L && W && G ? `${Math.floor(toM(L, r.unit) / toM(G, r.grid_cell_unit) + 1e-9)} × ${Math.floor(toM(W, r.unit) / toM(G, r.grid_cell_unit) + 1e-9)}` : null
  const crop = crops?.crops.find((c) => c.slug === b.preferred_crop)
  const missing = [!farm?.location && 'location', !r.temperature_c && 'room temperature'].filter(Boolean) as string[]

  return (
    <>
      <PageHeader title={isNew ? 'New farm' : 'Room setup'} description="Tell us about the room and the budget. Verdant works out the racks, levels and equipment for you." />
      <Stepper step={step} maxReached={isNew ? 0 : maxReached} go={(i) => (validate(step) || i < step ? setStep(i) : undefined)} />
      <Panel className="max-w-4xl">
        <form onSubmit={(e) => { e.preventDefault(); next() }} noValidate className="space-y-6">
          <h2 className="text-xl font-semibold">{STEPS[step]}</h2>

          {step === 0 && (
            <div className="grid gap-5 sm:grid-cols-2">
              <div className="sm:col-span-2"><Field label="Farm name" required htmlFor="name" error={errors.name} hint="For example “Terrace greens” or “Spare bedroom farm”.">
                <Input id="name" value={b.name} maxLength={120} aria-invalid={!!errors.name} onChange={(e) => setB({ ...b, name: e.target.value })} autoFocus /></Field></div>
              <Field label="Growing method" htmlFor="ft" hint="Hydroponic NFT is the most common choice for leafy greens on racks.">
                <Select id="ft" value={b.farming_type} onChange={(e) => setB({ ...b, farming_type: e.target.value })}>{Object.entries(FARMING_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
              <Field label="Growing experience" htmlFor="exp"><Select id="exp" value={b.experience_level} onChange={(e) => setB({ ...b, experience_level: e.target.value })}>
                <option value="BEGINNER">New to growing</option><option value="INTERMEDIATE">Some experience</option><option value="ADVANCED">Experienced grower</option></Select></Field>
            </div>
          )}

          {step === 1 && id && <LocationPicker farmId={id} />}

          {step === 2 && id && <PhotoStep farmId={id} unit={r.unit} onApplied={(f) => { if (f.room) { setR(roomToState(f.room)); setAiFilled(true) } setStep(3); setMax((m) => Math.max(m, 3)) }} />}

          {step === 3 && (
            <>
              {aiFilled && <Callout tone="warn" title="Filled in from your photo by AI">These are estimates. Check the length, width and ceiling height with a tape measure and correct them here; every rack position is calculated from these numbers.</Callout>}
              <div className="grid gap-5 sm:grid-cols-4">
                <Field label="Units" htmlFor="unit"><Select id="unit" value={r.unit} onChange={(e) => {
                  const u = e.target.value as Unit
                  const conv = (v: string) => (v === '' ? v : trim(toM(Number(v), r.unit), u))
                  setR({ ...r, unit: u, length: conv(r.length), width: conv(r.width), height: conv(r.height) })
                }}><option value="ft">Feet</option><option value="in">Inches</option><option value="m">Metres</option><option value="cm">Centimetres</option></Select></Field>
                {(['length', 'width', 'height'] as const).map((k) => (
                  <Field key={k} label={k === 'height' ? 'Ceiling height' : k[0].toUpperCase() + k.slice(1)} required htmlFor={k} error={errors[k]}
                    hint={k === 'length' ? 'Longest wall' : k === 'width' ? 'Wall at right angles' : 'Floor to ceiling'}>
                    <Input id={k} type="number" inputMode="decimal" step="any" min="0" suffix={r.unit} value={r[k]} aria-invalid={!!errors[k]} onChange={(e) => setR({ ...r, [k]: e.target.value })} />
                  </Field>
                ))}
              </div>
              <div className="grid gap-5 sm:grid-cols-4">
                <Field label="Typical room temperature" htmlFor="t" error={errors.temperature_c} hint="Optional"><Input id="t" type="number" step="any" suffix="°C" value={r.temperature_c} onChange={(e) => setR({ ...r, temperature_c: e.target.value })} /></Field>
                <Field label="Light source" htmlFor="ls"><Select id="ls" value={r.light_source} onChange={(e) => setR({ ...r, light_source: e.target.value })}>
                  <option value="GROW_LIGHTS">Grow lights</option><option value="MIXED">Window + grow lights</option><option value="SUNLIGHT">Window only</option><option value="UNKNOWN">Not sure</option></Select></Field>
                <YesNo label="Water nearby?" value={r.water_access} onChange={(v) => setR({ ...r, water_access: v })} />
                <YesNo label="Power sockets?" value={r.electrical_access} onChange={(v) => setR({ ...r, electrical_access: v })} />
              </div>
              {cells && <p className="text-[13px] text-ink-soft">Planning grid: {cells} cells of {r.grid_cell} {r.grid_cell_unit}.</p>}
            </>
          )}

          {step === 4 && (
            <div className="space-y-5">
              <div className="grid gap-5 sm:grid-cols-[1fr_140px]">
                <Field label="Customer's total budget for setup" required htmlFor="bud" error={errors.budget} hint="Racks, lights, pumps, trays and all other equipment are chosen to fit inside this — it is never exceeded.">
                  <Input id="bud" type="number" min="0" step="any" inputMode="decimal" suffix={b.currency} value={b.budget} aria-invalid={!!errors.budget} placeholder="e.g. 30000" onChange={(e) => setB({ ...b, budget: e.target.value })} autoFocus /></Field>
                <Field label="Currency" htmlFor="cur"><Select id="cur" value={b.currency} onChange={(e) => setB({ ...b, currency: e.target.value })}>{CURRENCIES.map((c) => <option key={c}>{c}</option>)}</Select></Field>
              </div>
              {b.currency !== 'INR' && b.currency !== 'USD' && (
                <Field label={`Exchange rate: 1 USD = ? ${b.currency}`} htmlFor="fx" error={errors.fx_rate_per_usd} hint="Sample prices exist in INR and USD; this converts them.">
                  <Input id="fx" type="number" step="any" min="0" value={b.fx_rate_per_usd} onChange={(e) => setB({ ...b, fx_rate_per_usd: e.target.value })} /></Field>
              )}
              <div className="grid gap-5 sm:grid-cols-2">
                <Field label="Crop" htmlFor="pc" hint="Leave on “Choose for me” — the AI crop advisor can suggest the most profitable crop for your location after the plan.">
                  <Select id="pc" value={b.preferred_crop} onChange={(e) => setB({ ...b, preferred_crop: e.target.value })}>
                    <option value="">Choose for me</option>{crops?.crops.map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}</Select></Field>
                <Field label={`Electricity price per kWh (${b.currency})`} htmlFor="er" hint={b.currency === 'INR' ? 'Optional — from your bill. Otherwise ₹8/kWh is assumed and labelled.' : 'Optional — from your bill.'}>
                  <Input id="er" type="number" step="any" min="0" value={b.electricity_rate} onChange={(e) => setB({ ...b, electricity_rate: e.target.value })} /></Field>
              </div>
            </div>
          )}

          {step === 5 && (
            <div className="grid gap-6 md:grid-cols-2">
              <div className="space-y-4">
                <KV items={[
                  ['Farm', b.name], ['Method', FARMING_TYPES[b.farming_type]],
                  ['Room', L && W ? `${r.length} × ${r.width} × ${r.height} ${r.unit}${aiFilled ? ' (AI estimate, checked by you)' : ''}` : '—'],
                  ['Budget', b.budget ? fmtMoney(Number(b.budget), b.currency) : '—'],
                  ['Crop', crop?.name ?? 'Choose for me'],
                ]} />
                {season && season.location.latitude !== null && <SeasonCard v={season} />}
              </div>
              <div className="space-y-3">
                <Callout tone="info" title="What happens next">Verdant tries every standard rack size, orientation and number of levels, and picks the combination with the most plant sites whose full setup cost stays within {b.budget ? fmtMoney(Number(b.budget) * 0.95, b.currency) : 'the budget'} (5% kept in reserve).</Callout>
                {missing.length > 0 && <Callout tone="warn">Not provided: {missing.join(', ')}. Seasonal advice is less specific without a location.</Callout>}
                {planErr && <Callout tone="crit" title="No plan fits">{planErr}</Callout>}
              </div>
            </div>
          )}

          <div className="flex items-center justify-between pt-4 border-t border-line">
            <Button type="button" variant="ghost" disabled={step === 0} onClick={() => setStep(step - 1)}>Back</Button>
            <div className="flex items-center gap-2">
              {(step === 1 || step === 2) && <Badge>Optional</Badge>}
              {step < 5 ? <Button type="submit" loading={saving}>{step === 1 || step === 2 ? 'Continue' : 'Save and continue'}</Button>
                : <Button type="button" icon={<Sparkles className="size-4" />} loading={saving} onClick={createPlan}>Create my budget plan</Button>}
            </div>
          </div>
        </form>
      </Panel>
    </>
  )
}
