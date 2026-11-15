export type Unit = 'm' | 'cm' | 'ft' | 'in'

export interface User { id: number; email: string; name: string; preferences: { display_unit?: Unit; [k: string]: unknown }; created_at: string }

export interface Room {
  length_m: number; width_m: number; height_m: number; input_unit: Unit
  length: number; width: number; height: number
  grid_cell_m: number; grid_cell: number | null; grid_cell_unit: Unit
  temperature_c: number | null; humidity_pct: number | null; light_source: string
  water_access: boolean | null; electrical_access: boolean | null; market_location: string | null; notes: string | null
  floor_area_m2: number
}

export interface Farm {
  id: number; name: string; status: 'ACTIVE' | 'ARCHIVED'; farming_type: string; budget: number | null; currency: string
  fx_rate_per_usd: number; electricity_rate: number | null; preferred_crop: string | null; crop_categories: string[]
  experience_level: string; automation_level: string; priorities: string[]; desired_plant_count: number | null
  is_sample: boolean; wizard_step: number; created_at: string; updated_at: string
  room: Room | null; active_design_id: number | null; design_count: number; obstacle_count: number; image_count: number
  location: { name: string | null; latitude: number; longitude: number; source: string | null } | null
}

export type ObstacleKind = 'DOOR' | 'WINDOW' | 'PILLAR' | 'FURNITURE' | 'EQUIPMENT' | 'FIXED' | 'RESTRICTED'
export interface Obstacle { id: number; kind: ObstacleKind; label: string | null; x: number; y: number; w: number; d: number; height_m: number | null; clearance_m: number; source: string; confirmed: boolean }

export interface Rack { id?: number; label: string; x: number; y: number; w: number; d: number; rotation: 0 | 90; access_side: string | null }

export interface RackConfig {
  rack_length_m: number; rack_depth_m: number; rack_height_m: number; levels: number; level_gap_m: number | null
  plants_per_level: number | null; plant_spacing_m: number | null; orientation: 'ANY' | 'X' | 'Y'; max_racks: number | null
  walkway_m: number; obstacle_clearance_m: number; rack_gap_m: number; wall_clearance_m: number; ceiling_clearance_m: number
  min_passage_m: number; base_clearance_m?: number; edge_margin_m?: number
}

export interface Violation { code: string; rack: string | null; message: string }
export interface Validation { valid: boolean; violations: Violation[]; warnings: Violation[]; aisles: Record<string, { side: string; rect: { x: number; y: number; w: number; d: number } }> }

export interface Metrics { rack_count: number; rack_footprint_m2: number; room_area_m2: number; blocked_area_m2: number; reserved_area_m2: number; free_area_m2: number; utilization_pct: number; utilization_definition: string }

export interface Capacity { plants_per_level: number | null; levels_per_rack: number; rack_count: number; total: number | null; per_row?: number | null; per_col?: number | null; spacing_m?: number; level_gap_m?: number; assumptions: string[]; warnings: string[]; basis: string }

export interface CostTotals { setup_total: number; monthly_total: number; by_category: Record<string, number>; illustrative_lines: number; definition: string }
export interface Resources { light_fixtures: number; tanks: number; fans: number; photoperiod_h: number; lighting_kw: number; energy_kwh_month: number; energy_breakdown: Record<string, number>; water_l_month: number; assumptions: string[] }
export interface Profitability { available: boolean; missing?: string[]; notes?: string[]; period?: string; estimated_saleable_yield_kg_cycle?: number; cycle_days?: number; cycles_per_month?: number; estimated_gross_revenue?: number; included_costs?: number; estimated_margin?: number; payback_months?: number | null; assumptions?: string[]; price_source?: { type: string; price: number; currency: string; location: string | null; observed_on: string | null } }

export interface Evaluation {
  validation: Validation; metrics: Metrics; capacity: Capacity; resources: Resources; cost_totals: CostTotals; profitability: Profitability
  budget: number | null; over_budget: boolean; crop: { slug: string; name: string } | null
  crop_suitability: { score: number; suitable: boolean; blockers: string[] } | null
}

export interface DesignSummary { id: number; farm_id: number; name: string; is_active: boolean; rack_config: RackConfig; crop_slug: string | null; origin: string; strategy: string | null; rack_count: number; created_at: string; updated_at: string }
export type Design = DesignSummary & Evaluation & { racks: Rack[] }

export interface LayoutOption { strategy: string; racks: Rack[]; validation: Validation; metrics: Metrics; score: number; score_breakdown: Record<string, number>; capacity: Capacity; setup_cost: number; over_budget: boolean }
export interface GenerateResult { options: LayoutOption[]; feasible: boolean; rejections: Record<string, number>; diagnosis: { reason: string; suggestion: string }[]; scoring: string; config: RackConfig }

export interface Crop { slug: string; name: string; category: string; farming_types: string[]; ph: number[] | null; ec_ms_cm: number[] | null; temp_c: number[] | null; humidity_pct: number[] | null; dli: number[] | null; photoperiod_h: number | null; spacing_m: number | null; mature_height_m: number | null; days_to_harvest: number[] | null; difficulty: string; yield_g_per_plant: number | null; notes: string }
export interface CropResult { slug: string; name: string; category: string; suitable: boolean; score: number; raw_score: number; factors: Record<string, number>; weights: Record<string, number>; reasons: string[]; blockers: string[]; missing_inputs: string[]; capacity: Capacity; source_type: string }

export interface CostItem { id: number; key: string | null; name: string; category: string; quantity: number; unit: string; unit_price: number; currency: string; price_source: string; source_date: string | null; cost_type: 'ONE_TIME' | 'MONTHLY'; status: 'REQUIRED' | 'OPTIONAL' | 'FUTURE'; included: boolean; quantity_locked: boolean; notes: string | null; subtotal: number }
export interface CostView { design_id: number; currency: string; fx_rate_per_usd: number; items: CostItem[]; totals: CostTotals; resources: Resources; profitability: Profitability; budget: number | null; over_budget: boolean; capacity: Capacity; crop: { slug: string; name: string } | null; price_note: string }

export interface ScenarioSummary { rack_count: number; plant_capacity: number | null; utilization_pct: number; setup_cost: number; monthly_cost: number; energy_kwh_month: number; water_l_month: number; crop_score: number | null; monthly_margin: number | null; over_budget: boolean; valid: boolean }
export interface ScenarioResult { feasible: boolean; errors?: string[]; diagnosis?: { reason: string; suggestion: string }[]; config?: RackConfig; crop_slug?: string; strategy?: string; racks?: Rack[]; before: ScenarioSummary | null; after: ScenarioSummary | null; notes?: string[]; delta?: Record<string, number | null> }
export interface Scenario { id: number; name: string; base_design_id: number | null; changes: Record<string, unknown>; result: ScenarioResult; applied_design_id: number | null; applied_at: string | null; created_at: string }

export interface SensorRecord { id: number; ts: string; source_type: string; temperature_c: number | null; humidity_pct: number | null; ph: number | null; ec_ms_cm: number | null; tds_ppm: number | null; water_level_pct: number | null; light_ppfd: number | null; pump_on: boolean | null; fan_on: boolean | null; energy_wh: number | null }
export interface SimState { farm_id: number; status: 'RUNNING' | 'PAUSED' | 'STOPPED'; mode: 'NORMAL' | 'WARNING' | 'ABNORMAL'; interval_s: number; last_tick_at: string | null; record_count: number; targets: Record<string, number>; target_basis: string; source_type: string; data_flow: string; future_flow: string }
export interface Alert { id: number; metric: string; severity: 'WARNING' | 'CRITICAL'; value: number | null; message: string; suggestion: string; status: 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED'; source_type: string; data_source: string; created_at: string }
export interface Threshold { metric: string; warn_min: number | null; warn_max: number | null; crit_min: number | null; crit_max: number | null; basis: string; enabled: boolean }
export interface AiSettings { configured: boolean; provider: string | null; model: string | null; web_search: boolean; key_hint: string | null; origin: string | null; providers: { id: string; label: string; default_model: string }[] }
export interface SeasonView { location: { name: string | null; latitude: number | null; longitude: number | null; source: string | null }; season: { name: string; code: string; detail: string; region?: string }; weather: { mean_temp_c: number; max_temp_c: number; min_temp_c: number; mean_humidity_pct: number | null; source: string } | null; crop_fit: { slug: string; name: string; fit: number; why: string }[]; date: string }
export interface RoomAi { room: { length_m: number | null; width_m: number | null; height_m: number | null; confidence: string; basis: string }; light: { natural_light: string; notes: string }; floor: string | null; power_outlets_visible: boolean | null; water_source_visible: boolean | null; objects: { kind: string; label: string; wall: string; confidence: string }[]; warnings: string[]; summary: string; provider: string; model: string }
export interface PlanResult { feasible: boolean; reason?: string; budget?: number; currency?: string; reserve_pct?: number; spend_limit?: number; objective?: string; rack_name?: string; config?: RackConfig; racks?: Rack[]; plants?: number; setup_total?: number; monthly_total?: number; remaining?: number; margin?: number | null; optional_included?: string[]; tried: { rack: string; max_racks: number; best_racks?: number; best_levels?: number | null; plants?: number; setup?: number | null; note?: string }[]; notes?: string[]; crop?: { slug: string; name: string } | null; design_id?: number }
export interface CropAdvice { generated_at: string; provider: string; model: string; web_search: boolean; source_type: string; sources: { title: string; url: string }[]; season: SeasonView['season']; weather: SeasonView['weather']; location: SeasonView['location']; season_summary: string; recommendations: { slug: string; name: string; rank: number; why: string; demand_trend: string; price_low: number | null; price_high: number | null; price_basis: string; best_selling_channel: string; risk: string; rule_score: number; season_fit: number | null }[]; trending_notes: string[]; avoid: { slug: string; reason: string }[]; disclaimer: string; currency: string }
export interface Insight { id: number; category: string; priority: 'HIGH' | 'MEDIUM' | 'LOW'; title: string; explanation: string; evidence: Record<string, unknown>; action: string; source_type: string; created_at: string }
