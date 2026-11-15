import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import FarmGate, { FarmCrumb } from '../components/FarmGate'
import PlanView from '../components/PlanView'
import { Button, ErrorState, Field, Input, PageHeader, Panel, Select, Spinner, Stat } from '../components/ui'
import { get, put } from '../lib/api'
import { useAction, useDisplayUnit, useInvalidateFarm, useObstacles } from '../lib/hooks'
import { fmtLen, toM } from '../lib/units'
import type { Farm, Unit } from '../lib/types'

const STATE_INFO: Record<string, { label: string; sw: string; text: string }> = {
  FREE: { label: 'Free', sw: 'bg-white border border-line-strong', text: 'Nothing placed or blocked.' },
  RACK: { label: 'Rack', sw: 'bg-forest-700/60', text: 'Covered by a rack in the active design.' },
  WALKWAY: { label: 'Walkway', sw: 'bg-sage-300', text: 'Access aisle in front of a rack.' },
  DOOR_CLEARANCE: { label: 'Door clearance', sw: 'bg-[#e6b860]/60', text: 'Door opening and swing zone.' },
  OBSTACLE: { label: 'Obstacle', sw: 'bg-ink-soft/50', text: 'Pillar, furniture, equipment or fixed object.' },
  RESTRICTED: { label: 'Restricted', sw: 'bg-crit/40', text: 'Zone you asked to keep free.' },
  UNCERTAIN: { label: 'Uncertain', sw: 'bg-sim/40', text: 'Unconfirmed obstacle, treated as blocked.' },
}

function Grid({ farm }: { farm: Farm }) {
  const unit = useDisplayUnit()
  const room = farm.room!
  const { data: obstacles } = useObstacles(farm.id)
  const [cell, setCell] = useState(String(room.grid_cell ?? 1))
  const [cu, setCu] = useState<Unit>(room.grid_cell_unit)
  const { data: g, isLoading, error, refetch } = useQuery({ queryKey: ['grid', farm.id, room.grid_cell_m], queryFn: () => get<any>(`/farms/${farm.id}/grid`) })
  const { data: design } = useQuery({ queryKey: ['design', farm.active_design_id], queryFn: () => get<any>(`/designs/${farm.active_design_id}`), enabled: !!farm.active_design_id })
  const invalidate = useInvalidateFarm()
  const cellM = Number(cell) > 0 ? toM(Number(cell), cu) : null
  const tooSmall = cellM !== null && cellM < 0.05
  const tooBig = cellM !== null && cellM > Math.min(room.length_m, room.width_m)
  const apply = useAction(() => put(`/farms/${farm.id}/room`, { length: room.length, width: room.width, height: room.height, unit: room.input_unit, grid_cell: Number(cell), grid_cell_unit: cu,
    temperature_c: room.temperature_c, humidity_pct: room.humidity_pct, light_source: room.light_source, water_access: room.water_access, electrical_access: room.electrical_access, market_location: room.market_location, notes: room.notes }),
  { success: 'Grid cell size saved', onSuccess: () => invalidate(farm.id) })
  const previewCols = cellM ? Math.floor(room.length_m / cellM + 1e-9) : null
  const previewRows = cellM ? Math.floor(room.width_m / cellM + 1e-9) : null

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
      <div>
        {isLoading ? <Spinner /> : error ? <ErrorState error={error} retry={refetch} /> : (
          <PlanView length={room.length_m} width={room.width_m} unit={unit} obstacles={obstacles} racks={design?.racks ?? []} gridCell={g.cell_m} cellStates={g.states} height={520}
            showLayers={{ aisles: false }} />
        )}
        <ul className="mt-3 grid sm:grid-cols-2 lg:grid-cols-4 gap-x-4 gap-y-2 text-[12.5px]">
          {Object.entries(STATE_INFO).map(([k, v]) => (
            <li key={k} className="flex gap-2"><span className={`size-3 mt-0.5 rounded-[2px] shrink-0 ${v.sw}`} aria-hidden /><span><b className="font-medium">{v.label}</b>{g && <span className="text-muted"> · {g.counts[k]}</span>}<span className="block text-muted">{v.text}</span></span></li>
          ))}
        </ul>
      </div>
      <div className="space-y-4">
        {g && (
          <Panel title="Grid size">
            <div className="grid grid-cols-3 gap-3">
              <Stat label="Columns" value={g.columns} sub="along length" />
              <Stat label="Rows" value={g.rows} sub="along width" />
              <Stat label="Full cells" value={g.full_cells} />
            </div>
            <p className="text-[13px] text-ink-soft mt-4 leading-relaxed">
              columns = floor({fmtLen(room.length_m, unit)} ÷ {fmtLen(g.cell_m, unit)}) = {g.columns}; rows = floor({fmtLen(room.width_m, unit)} ÷ {fmtLen(g.cell_m, unit)}) = {g.rows}.
              {(g.remainder_x_m > 0.001 || g.remainder_y_m > 0.001) && <> A {fmtLen(g.remainder_x_m, unit)} strip at the right and {fmtLen(g.remainder_y_m, unit)} at the bottom are partial cells and aren't counted.</>}
            </p>
            <p className="text-[12.5px] text-muted mt-2">Full cells are not the same as usable rack space — obstacles, door access, walkways and rack footprints are checked with exact geometry, not by cell.</p>
          </Panel>
        )}
        <Panel title="Change cell size">
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); apply.mutate(undefined) }}>
            <div className="grid grid-cols-[1fr_96px] gap-2">
              <Field label="Cell side" htmlFor="cell" error={tooSmall ? 'Minimum 5 cm' : tooBig ? 'Larger than the room' : undefined}><Input id="cell" type="number" step="any" min="0" value={cell} onChange={(e) => setCell(e.target.value)} /></Field>
              <Field label="Unit" htmlFor="cu"><Select id="cu" value={cu} onChange={(e) => setCu(e.target.value as Unit)}><option value="ft">ft</option><option value="in">in</option><option value="m">m</option><option value="cm">cm</option></Select></Field>
            </div>
            {previewCols !== null && !tooSmall && !tooBig && <p className="text-[13px] text-ink-soft" aria-live="polite">Preview: {previewCols} × {previewRows} = {(previewCols * previewRows!).toLocaleString()} cells</p>}
            <Button type="submit" loading={apply.isPending} disabled={!cellM || tooSmall || tooBig}>Apply cell size</Button>
          </form>
        </Panel>
      </div>
    </div>
  )
}

export default function GridPage() {
  return (
    <FarmGate>{(farm) => (
      <>
        <PageHeader crumb={<FarmCrumb farm={farm} page="Planning grid" />} title="Planning grid" description="A square grid laid over the floor, showing what each cell is used for in the active design." />
        <Grid farm={farm} />
      </>
    )}</FarmGate>
  )
}
