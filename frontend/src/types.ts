/** Типы отражают модели бэкенда (backend/planner/core/models.py). */

export type Skill = 'local' | 'connection' | 'emergency'
export type Transport = 'car' | 'foot' | 'bike' | 'public'
export type Priority = 'normal' | 'urgent'
export type Objective = 'auto' | 'min_engineers' | 'min_distance'

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
}

export interface Route {
  engineer_id: string
  stops: Stop[]
  distance_km: number
  travel_min: number
  work_min: number
  wait_min: number
  end_time: string
}

export interface Unassigned {
  order_id: string
  reason_code: string
  reason: string
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
  | { type: 'cancel_order'; time: string; order_id: string }
  | { type: 'engineer_unavailable'; time: string; engineer_id: string }

export interface Plan {
  id: string
  scenario_id: string
  kind: 'optimized' | 'baseline'
  params: { objective: Objective; time_limit_s: number; [k: string]: unknown }
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

export interface PlanResponse {
  optimized: Plan
  baseline: Plan
  comparison: MetricRow[]
  scenario: Scenario
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

export interface ReplanResponse {
  plan: Plan
  diff: Diff
  scenario: Scenario
}

export const SKILL_RU: Record<Skill, string> = {
  local: 'Локальные работы',
  connection: 'Подключение и дозаказы',
  emergency: 'Аварийные работы',
}

export const TRANSPORT_RU: Record<Transport, string> = {
  car: 'автомобиль',
  foot: 'пешком',
  bike: 'велосипед',
  public: 'общественный транспорт',
}

export const SKILL_COLOR: Record<Skill, string> = {
  local: '#4c9f70',
  connection: '#3f76c4',
  emergency: '#c9513e',
}
