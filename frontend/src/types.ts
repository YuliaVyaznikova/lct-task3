export type Skill = 'local' | 'connection' | 'emergency'
export type Transport = 'car' | 'foot' | 'bike' | 'public'
export type Priority = 'normal' | 'urgent'
export type MapMode = 'plan' | 'sim'
export type Objective = 'auto' | 'min_engineers' | 'min_distance' | 'balanced'

export interface Point {
  address: string
  lat: number | null
  lon: number | null
}

export interface Order {
  id: string
  external_id: string
  address: string
  address_normalized: string
  district: string
  lat: number | null
  lon: number | null
  geocode_quality: string
  skill: Skill
  work_type: string
  description: string
  duration_min: number
  window_start: string
  window_end: string
  priority: Priority
  priority_tier: number
  required_transport: Transport | null
  attributes: Record<string, unknown>
}

export interface Engineer {
  id: string
  name: string
  skills: Skill[]
  transport: Transport
  shift_start: string
  shift_end: string
  start: Point
}

export interface Stop {
  order_id: string
  seq: number
  travel_km: number
  travel_min: number
  arrival: string
  wait_min: number
  start: string
  finish: string
  locked: boolean
  late_min: number
  departure: string | null
}

export interface Route {
  engineer_id: string
  stops: Stop[]
  distance_km: number
  travel_min: number
  work_min: number
  wait_min: number
  end_time: string
  break: { start: string; finish: string } | null
}

export type ReasonCode =
  | 'NO_SKILL'
  | 'NO_TRANSPORT'
  | 'NO_EQUIPMENT'
  | 'SHIFT_MISMATCH'
  | 'UNREACHABLE'
  | 'CAPACITY'
  | 'NO_COORDS'
  | 'CANCELLED'
  | 'ENGINEER_UNAVAILABLE'
  | 'MANUAL'

export interface Unassigned {
  order_id: string
  reason_code: ReasonCode
  reason: string
  detail: string
}

export interface Metrics {
  orders_total: number
  assigned: number
  unassigned: number
  urgent_total: number
  urgent_assigned: number
  engineers_total: number
  engineers_used: number
  distance_total_km: number
  distance_per_order_km: number
  distance_by_engineer: Record<string, number>
  travel_min_total: number
  work_min_total: number
  wait_min_total: number
  utilization_by_engineer: Record<string, number>
  extra_engineers_needed: number
  late_risk: number
  rescheduled: number
  response_measured: number
  response_median_min: number
  response_max_min: number
  response_over_norm: number
}

export interface Check {
  ok: boolean
  text: string
}

export interface OrderExplanation {
  order_id: string
  engineer_id: string
  headline: string
  checks: Check[]
  travel: string
  alternatives: string[]
  why: string
}

export type PlanEvent =
  | { type: 'urgent_order'; time: string; order: Partial<Order> & { id: string } }
  | { type: 'new_order'; time: string; order: Partial<Order> & { id: string } }
  | { type: 'cancel_order'; time: string; order_id: string }
  | { type: 'engineer_unavailable'; time: string; engineer_id: string }
  | { type: 'engineer_delayed'; time: string; engineer_id: string; minutes: number }

export interface PlanParams {
  objective: Objective
  time_limit_s: number
  seed: number
  stability_weight_m: number
  lunch: boolean
  allow_reschedule: boolean
  travel_model: string
  required_orders?: string[]
}

export interface WorkType {
  work_type: string
  skill: Skill
  duration_min: number
  priority: 'normal' | 'urgent'
  priority_tier: number
  normative: string
}

export interface Plan {
  id: string
  scenario_id: string
  kind: 'optimized' | 'baseline'
  origin: 'solver' | 'manual' | 'event'
  params: PlanParams
  planned_from: string
  parent_plan_id: string | null
  event: PlanEvent | null
  routes: Route[]
  unassigned: Unassigned[]
  metrics: Metrics
  explanations: Record<string, OrderExplanation>
  route_explanations: Record<string, string>
  plan_explanation: string
}

export interface Scenario {
  id: string
  name: string
  date: string
  office: Point
  orders: Order[]
  engineers: Engineer[]
  events: PlanEvent[]
  meta: { source: string; generator_seed: number | null; geocoder: string; notes: string }
}

export interface ScenarioBrief {
  id: string
  name: string
  date: string
  orders: number
  engineers: number
  engineers_min: number
  events: number
  office: string
}

export interface MetricRow {
  key: string
  title: string
  ours: number
  baseline: number
  delta: number
  better: boolean | null
}

export interface ControlRow {
  title: string
  ours: number
  control: number
}

export interface ControlReference {
  available: boolean
  summary: string
  brigades: number
  covered_orders: number
  late_starts: number
  rows: ControlRow[]
}

export type VariantKey = 'min_engineers' | 'min_distance' | 'balanced'

export interface Variant {
  key: VariantKey
  title: string
  plan_id: string
  metrics: Metrics
}

export interface PlanResponse {
  optimized: Plan
  baseline: Plan
  comparison: MetricRow[]
  control: ControlReference
  scenario: Scenario
  variants: Variant[]
  diff: Diff | null
}

export interface SavedPlan {
  id: string
  name: string
  saved_at: string
  scenario_id: string
  metrics: Metrics
  from_title: string | null
}

export interface JobProgress {
  elapsed_s: number
  variant: string
  assigned: number
  total: number
  engineers_used: number
  distance_km: number
  routes: Record<string, string[]>
}

export interface UploadProgress {
  stage: 'geocode'
  done: number
  total: number
}

export interface NearestWindow {
  available: boolean
  window_start: string | null
  window_end: string | null
  engineer_id: string | null
  start: string | null
  text: string
}

export interface ShiftedVisit {
  order_id: string
  from_start: string
  to_start: string
}

export type CandidateReasonCode = 'NO_SKILL' | 'NO_TRANSPORT' | 'NO_EQUIPMENT' | 'WINDOW' | 'SHIFT' | 'LUNCH' | 'CAPACITY'

export interface Candidate {
  engineer_id: string
  feasible: boolean
  reason_code: CandidateReasonCode | null
  reason: string | null
  position: number | null
  arrival: string | null
  start: string | null
  added_km: number | null
  donor_removed_km: number | null
  total_delta_km: number | null
  shifted: ShiftedVisit[]
  preview_routes: Record<string, string[]>
}

export interface Change {
  order_id: string
  from_engineer: string | null
  to_engineer: string | null
  from_seq: number | null
  to_seq: number | null
  from_start: string | null
  to_start: string | null
}

export interface Diff {
  event: PlanEvent
  before_plan_id: string
  after_plan_id: string
  changed: Change[]
  newly_assigned: string[]
  newly_unassigned: string[]
  removed: string[]
  added: string[]
  routes_changed: string[]
  locked_stops: number
  metrics_before: Metrics
  metrics_after: Metrics
  summary: string
}

export interface PlanGeometry {
  available: boolean
  source: string
  profile: string
  routes: Record<string, [number, number][]>
  legs: Record<string, [number, number][][]>
  errors: string[]
}

export interface ReplanResponse {
  plan: Plan
  diff: Diff
  scenario: Scenario
  variants: Variant[]
}

export interface Matched {
  optimized: Plan
  baseline: Plan
  control: ControlReference
  scenario: Scenario
}

export type BarVariant = Omit<Variant, 'key'> & { key: string }

export interface MineVariant {
  planId: string
  title?: string
  metrics: Metrics
  from?: string
  draft: boolean
}

export interface RunningJob {
  kind: 'plan' | 'event'
  label: string
  startedAt: number
  budgetS: number
  last: JobProgress | null
  byVariant: Record<string, JobProgress>
  expected: string[]
}

export type EventKind = PlanEvent['type']

export type Selection = { kind: 'order'; id: string } | { kind: 'engineer'; id: string } | null

export type Tab = 'map' | 'schedule' | 'compare'
