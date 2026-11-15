import type { Unit } from './types'

export const TO_M: Record<Unit, number> = { m: 1, cm: 0.01, ft: 0.3048, in: 0.0254 }
export const UNIT_LABEL: Record<Unit, string> = { m: 'metres', cm: 'centimetres', ft: 'feet', in: 'inches' }

export const toM = (v: number, u: Unit) => v * TO_M[u]
export const fromM = (m: number, u: Unit) => m / TO_M[u]

/** Format a length in metres for display in `u`, e.g. "2.44 m" or "8.0 ft". */
export function fmtLen(m: number | null | undefined, u: Unit = 'm', digits?: number) {
  if (m === null || m === undefined || Number.isNaN(m)) return '—'
  const v = fromM(m, u)
  const d = digits ?? (u === 'm' ? 2 : u === 'cm' ? 0 : 1)
  return `${v.toFixed(d)} ${u}`
}

export function fmtArea(m2: number, u: Unit = 'm') {
  if (u === 'ft' || u === 'in') return `${(m2 / 0.09290304).toFixed(1)} ft²`
  return `${m2.toFixed(2)} m²`
}

export function fmtMoney(v: number | null | undefined, currency = 'USD') {
  if (v === null || v === undefined) return '—'
  try {
    if (currency === 'INR') return new Intl.NumberFormat('en-IN', { style: 'currency', currency, maximumFractionDigits: Math.abs(v) < 10 ? 2 : 0 }).format(v)
    return new Intl.NumberFormat(undefined, { style: 'currency', currency, maximumFractionDigits: Math.abs(v) >= 1000 ? 0 : 2 }).format(v)
  } catch {
    return `${v.toFixed(2)} ${currency}`
  }
}

export const fmtNum = (v: number | null | undefined, d = 0) => (v === null || v === undefined ? '—' : v.toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }))

export function timeAgo(iso: string) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 60) return `${Math.max(0, Math.round(s))}s ago`
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return new Date(iso).toLocaleDateString()
}

export const FARMING_TYPES: Record<string, string> = {
  HYDROPONIC_NFT: 'Hydroponic — NFT channels',
  HYDROPONIC_DWC: 'Hydroponic — deep water culture',
  HYDROPONIC_EBB_FLOW: 'Hydroponic — ebb & flow',
  AEROPONIC: 'Aeroponic',
  SOIL_CONTAINER: 'Soil / containers',
}

export const METRIC_META: Record<string, { label: string; unit: string; digits: number }> = {
  temperature_c: { label: 'Air temperature', unit: '°C', digits: 1 },
  humidity_pct: { label: 'Relative humidity', unit: '%', digits: 0 },
  ph: { label: 'Solution pH', unit: '', digits: 2 },
  ec_ms_cm: { label: 'EC', unit: 'mS/cm', digits: 2 },
  tds_ppm: { label: 'TDS', unit: 'ppm', digits: 0 },
  water_level_pct: { label: 'Reservoir level', unit: '%', digits: 0 },
  light_ppfd: { label: 'Light (PPFD)', unit: 'µmol/m²/s', digits: 0 },
}
