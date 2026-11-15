import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CloudSun, LocateFixed, MapPin } from 'lucide-react'
import { useState } from 'react'
import { get, put } from '../lib/api'
import { useAction } from '../lib/hooks'
import type { SeasonView } from '../lib/types'
import { Badge, Button, Callout, Input, SourceBadge } from './ui'

export function SeasonCard({ v }: { v: SeasonView }) {
  return (
    <div className="rounded-lg border border-line bg-sage-50 px-4 py-3 text-[13.5px] space-y-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <MapPin className="size-4 text-forest-700" aria-hidden /><b>{v.location.name ?? 'Location not set'}</b>
        {v.location.source && <Badge>{v.location.source === 'BROWSER_GPS' ? 'From your device' : 'Typed'}</Badge>}
      </div>
      <div><span className="text-muted">Season now: </span><b>{v.season.name}</b> <SourceBadge source="RULE" /> <span className="text-ink-soft">— {v.season.detail}</span></div>
      {v.weather ? (
        <div className="flex flex-wrap items-center gap-2"><CloudSun className="size-4 text-sage-500" aria-hidden />
          Next 7 days outdoors: {v.weather.min_temp_c}–{v.weather.max_temp_c} °C (mean {v.weather.mean_temp_c} °C){v.weather.mean_humidity_pct !== null && `, ${v.weather.mean_humidity_pct}% humidity`}
          <SourceBadge source="EXTERNAL_DATA" /><span className="text-[12px] text-muted">{v.weather.source}</span></div>
      ) : v.location.latitude !== null && <div className="text-[12.5px] text-muted">Live weather unavailable right now; the season estimate is used instead.</div>}
    </div>
  )
}

export default function LocationPicker({ farmId, onDone }: { farmId: number; onDone?: (v: SeasonView) => void }) {
  const qc = useQueryClient()
  const { data: v } = useQuery({ queryKey: ['season', farmId], queryFn: () => get<SeasonView>(`/farms/${farmId}/season`) })
  const [city, setCity] = useState('')
  const [geoErr, setGeoErr] = useState<string | null>(null)
  const [locating, setLocating] = useState(false)
  const save = useAction((body: object) => put<SeasonView>(`/farms/${farmId}/location`, body), {
    success: (r) => `Location set: ${r.location.name}`,
    onSuccess: (r) => { qc.setQueryData(['season', farmId], r); qc.invalidateQueries({ queryKey: ['farm', farmId] }); onDone?.(r) },
  })
  const useDevice = () => {
    setGeoErr(null)
    if (!('geolocation' in navigator)) return setGeoErr('This browser cannot share location. Type your city instead.')
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      (p) => { setLocating(false); save.mutate({ latitude: p.coords.latitude, longitude: p.coords.longitude, source: 'BROWSER_GPS' }) },
      (e) => { setLocating(false); setGeoErr(e.code === 1 ? 'Location permission was blocked. Allow it in the address bar, or type your city.' : 'Could not get your location. Type your city instead.') },
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 600000 },
    )
  }
  return (
    <div className="space-y-4">
      <p className="text-[14px] text-ink-soft max-w-2xl">Your location sets the growing season and local weather, and lets the AI check which crops are selling well near you right now. Only an approximate position is stored with this farm.</p>
      <div className="flex flex-wrap items-end gap-3">
        <Button type="button" icon={<LocateFixed className="size-4" />} loading={locating || (save.isPending && !city)} onClick={useDevice}>Enable location</Button>
        <span className="text-[13px] text-muted pb-2.5">or</span>
        <form className="flex gap-2 items-end" onSubmit={(e) => { e.preventDefault(); if (city.trim().length > 1) save.mutate({ name: city.trim(), source: 'USER_INPUT' }) }}>
          <div><label htmlFor="city" className="block text-[13px] font-medium mb-1.5">Type your city</label>
            <Input id="city" value={city} placeholder="e.g. Bengaluru" onChange={(e) => setCity(e.target.value)} className="w-56" /></div>
          <Button type="submit" variant="secondary" loading={save.isPending && !!city} disabled={city.trim().length < 2}>Set city</Button>
        </form>
      </div>
      {geoErr && <Callout tone="warn">{geoErr}</Callout>}
      {v && v.location.latitude !== null && <SeasonCard v={v} />}
    </div>
  )
}
