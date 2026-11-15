import { useId } from 'react'
import { fromM, toM } from '../lib/units'
import type { RackConfig, Unit } from '../lib/types'
import { Field, Input, Select } from './ui'

export const DEFAULT_CONFIG: RackConfig = {
  rack_length_m: 1.2, rack_depth_m: 0.45, rack_height_m: 1.8, levels: 4, level_gap_m: null, plants_per_level: null, plant_spacing_m: null,
  orientation: 'ANY', max_racks: null, walkway_m: 0.75, obstacle_clearance_m: 0.15, rack_gap_m: 0.05, wall_clearance_m: 0, ceiling_clearance_m: 0.3, min_passage_m: 0.6,
}

/** Length input that shows the user's display unit but reads/writes metres. */
export function LenField({ label, m, onChange, unit, hint, nullable }: { label: string; m: number | null; onChange: (m: number | null) => void; unit: Unit; hint?: string; nullable?: boolean }) {
  const id = useId()
  const shown = m === null ? '' : +fromM(m, unit).toFixed(unit === 'm' ? 3 : 2)
  return (
    <Field label={label} hint={hint} htmlFor={id}>
      <Input id={id} type="number" step="any" min="0" suffix={unit} value={shown} placeholder={nullable ? 'Auto' : undefined}
        onChange={(e) => onChange(e.target.value === '' ? (nullable ? null : 0) : toM(Number(e.target.value), unit))} />
    </Field>
  )
}

export default function RackConfigForm({ cfg, onChange, unit }: { cfg: RackConfig; onChange: (c: RackConfig) => void; unit: Unit }) {
  const set = <K extends keyof RackConfig>(k: K, v: RackConfig[K]) => onChange({ ...cfg, [k]: v })
  const lv = useId(), or = useId(), mr = useId(), pp = useId()
  return (
    <div className="space-y-5">
      <fieldset className="grid grid-cols-2 gap-3">
        <legend className="text-[13px] font-semibold mb-2 col-span-2">Rack</legend>
        <LenField label="Length" unit={unit} m={cfg.rack_length_m} onChange={(v) => set('rack_length_m', v ?? 0)} />
        <LenField label="Depth" unit={unit} m={cfg.rack_depth_m} onChange={(v) => set('rack_depth_m', v ?? 0)} />
        <LenField label="Height" unit={unit} m={cfg.rack_height_m} onChange={(v) => set('rack_height_m', v ?? 0)} />
        <Field label="Levels" htmlFor={lv}><Input id={lv} type="number" min={1} max={12} value={cfg.levels} onChange={(e) => onChange({ ...cfg, levels: Math.max(1, Number(e.target.value) || 1), level_gap_m: null })} /></Field>
        <LenField label="Level gap" unit={unit} m={cfg.level_gap_m} nullable hint="Auto = height ÷ levels" onChange={(v) => set('level_gap_m', v)} />
        <Field label="Plants per level" htmlFor={pp} hint="Auto = from crop spacing"><Input id={pp} type="number" min={1} placeholder="Auto" value={cfg.plants_per_level ?? ''} onChange={(e) => set('plants_per_level', e.target.value ? Number(e.target.value) : null)} /></Field>
      </fieldset>
      <fieldset className="grid grid-cols-2 gap-3">
        <legend className="text-[13px] font-semibold mb-2 col-span-2">Clearance & access</legend>
        <LenField label="Walkway width" unit={unit} m={cfg.walkway_m} hint="Clear aisle in front of each rack" onChange={(v) => set('walkway_m', v ?? 0)} />
        <LenField label="Obstacle clearance" unit={unit} m={cfg.obstacle_clearance_m} hint="Gap to pillars, furniture" onChange={(v) => set('obstacle_clearance_m', v ?? 0)} />
        <LenField label="Gap between racks" unit={unit} m={cfg.rack_gap_m} onChange={(v) => set('rack_gap_m', v ?? 0)} />
        <LenField label="Space above racks" unit={unit} m={cfg.ceiling_clearance_m} hint="For lights & air" onChange={(v) => set('ceiling_clearance_m', v ?? 0)} />
        <LenField label="Gap from walls" unit={unit} m={cfg.wall_clearance_m} onChange={(v) => set('wall_clearance_m', v ?? 0)} />
        <LenField label="Narrowest route from door" unit={unit} m={cfg.min_passage_m} onChange={(v) => set('min_passage_m', v ?? 0.6)} />
      </fieldset>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Orientation" htmlFor={or}><Select id={or} value={cfg.orientation} onChange={(e) => set('orientation', e.target.value as RackConfig['orientation'])}>
          <option value="ANY">Try both</option><option value="X">Along room length</option><option value="Y">Along room width</option></Select></Field>
        <Field label="Max racks" htmlFor={mr} hint="Blank = as many as fit"><Input id={mr} type="number" min={1} placeholder="No limit" value={cfg.max_racks ?? ''} onChange={(e) => set('max_racks', e.target.value ? Number(e.target.value) : null)} /></Field>
      </div>
    </div>
  )
}
