import { describe, expect, it } from 'vitest'
import { doorZone } from '../components/PlanView'
import { validateRoom, type Room } from '../pages/SetupWizard'
import { fmtLen, fromM, toM } from '../lib/units'

describe('units', () => {
  it('converts to and from metres', () => {
    expect(toM(10, 'ft')).toBeCloseTo(3.048)
    expect(fromM(0.3048, 'in')).toBeCloseTo(12)
    expect(fmtLen(2.4384, 'ft')).toBe('8.0 ft')
    expect(fmtLen(null)).toBe('—')
  })
})

describe('door zone preview mirrors the backend', () => {
  it('extends a north-wall door into the room', () => {
    const z = doorZone({ x: 1.2, y: 0, w: 0.8, d: 0.05, clearance_m: 0.8 }, 3.048, 2.4384)
    expect(z).toMatchObject({ x: 1.2, y: 0, w: 0.8 })
    expect(z.d).toBeCloseTo(0.85)
  })
  it('extends an east-wall door westward and clips to the room', () => {
    const z = doorZone({ x: 2.998, y: 1, w: 0.05, d: 0.8, clearance_m: 0.9 }, 3.048, 2.4384)
    expect(z.x).toBeCloseTo(2.098)
    expect(z.x + z.w).toBeCloseTo(3.048)
  })
})

const room = (o: Partial<Room>): Room => ({ length: '10', width: '8', height: '9', unit: 'ft', grid_cell: '1', grid_cell_unit: 'ft', temperature_c: '', humidity_pct: '', light_source: 'GROW_LIGHTS', water_access: '', electrical_access: '', market_location: '', notes: '', ...o })

describe('room wizard validation', () => {
  it('accepts the reference 10 × 8 × 9 ft room', () => {
    expect(validateRoom(room({}))).toEqual({})
  })
  it('requires dimensions and rejects non-positive values', () => {
    const e = validateRoom(room({ length: '', width: '0' }))
    expect(e.length).toBe('Required')
    expect(e.width).toMatch(/greater than 0/)
  })
  it('rejects an implausible ceiling and oversized grid cells', () => {
    expect(validateRoom(room({ height: '2' })).height).toMatch(/Ceiling/)
    expect(validateRoom(room({ grid_cell: '9' })).grid_cell).toBeTruthy()
  })
  it('validates optional ranges only when present', () => {
    expect(validateRoom(room({ humidity_pct: '140' })).humidity_pct).toBeTruthy()
    expect(validateRoom(room({ temperature_c: '' })).temperature_c).toBeUndefined()
  })
})
