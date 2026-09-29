import { effectiveTier, engineerName } from './labels'
import { minutes } from './time'
import type { Change, Diff, Engineer, JobProgress, Matched, Metrics, Order, Plan, PlanEvent, PlanResponse, Scenario, Stop, Variant } from './types'

export interface StopRef {
  engineerId: string
  stop: Stop
  position: number
  total: number
}

export function stopsByOrder(plan: Plan): Record<string, StopRef> {
  const result: Record<string, StopRef> = {}
  for (const route of plan.routes) {
    route.stops.forEach((stop, index) => {
      result[stop.order_id] = {
        engineerId: route.engineer_id,
        stop,
        position: index + 1,
        total: route.stops.length,
      }
    })
  }
  return result
}

export const routeSequenceKey = (plan: Plan) =>
  plan.id + '|' + plan.routes.map((route) => route.engineer_id + ':' + route.stops.map((stop) => stop.order_id).join(',')).join(';')

export function ordersById(scenario: Scenario): Record<string, Order> {
  return Object.fromEntries(scenario.orders.map((o) => [o.id, o]))
}

export interface TierCoverage {
  tier: number
  assigned: number
  total: number
}

export const assignedOrderIds = (plan: Plan) => new Set(plan.routes.flatMap((r) => r.stops.map((s) => s.order_id)))

export function tierCoverage(scenario: Scenario, assigned: Set<string>): TierCoverage[] {
  const tiers = new Map<number, TierCoverage>()
  for (const order of scenario.orders) {
    if (order.attributes?.cancelled_at) {
      continue
    }
    const tier = effectiveTier(order)
    const row = tiers.get(tier) ?? { tier, assigned: 0, total: 0 }
    row.total += 1
    if (assigned.has(order.id)) {
      row.assigned += 1
    }
    tiers.set(tier, row)
  }
  return [...tiers.values()].sort((a, b) => a.tier - b.tier)
}

export interface EngineerComparison {
  engineer: Engineer
  optimized: { visits: number; km: number } | null
  baseline: { visits: number; km: number } | null
}

function activeRouteSummary(plan: Plan, metrics: Metrics, engineerId: string) {
  const route = plan.routes.find((r) => r.engineer_id === engineerId)
  const visits = route?.stops.length ?? 0
  if (!visits) {
    return null
  }
  return { visits, km: metrics.distance_by_engineer[engineerId] ?? route?.distance_km ?? 0 }
}

export function engineerComparison(
  scenario: Scenario,
  optimized: Plan,
  baseline: Plan,
): EngineerComparison[] {
  return scenario.engineers.map((engineer) => ({
    engineer,
    optimized: activeRouteSummary(optimized, optimized.metrics, engineer.id),
    baseline: activeRouteSummary(baseline, baseline.metrics, engineer.id),
  }))
}

export type ChangeKind = 'engineer' | 'position' | 'time'

export interface VisitChange {
  orderId: string
  before: StopRef
  after: StopRef
  kinds: ChangeKind[]
  shiftMin: number
}

export interface RouteChange {
  engineerId: string
  visitsBefore: number
  visitsAfter: number
  kmBefore: number
  kmAfter: number
}

export interface EventChanges {
  changed: VisitChange[]
  added: StopRef[]
  removed: StopRef[]
  frozen: StopRef[]
  routes: RouteChange[]
  lateWindowStops: StopRef[]
}

const visitKinds = (change: Change): ChangeKind[] => {
  if (change.from_engineer !== change.to_engineer) {
    return ['engineer']
  }
  const kinds: ChangeKind[] = []
  if (change.from_seq !== change.to_seq) {
    kinds.push('position')
  }
  if (change.from_start !== change.to_start) {
    kinds.push('time')
  }
  return kinds
}

const present = (refs: (StopRef | undefined)[]): StopRef[] => refs.filter((ref): ref is StopRef => ref !== undefined)

export type DiffLike = Pick<Diff, 'changed' | 'added' | 'removed' | 'newly_unassigned' | 'routes_changed'>

export function changesFromDiff(diff: DiffLike, before: Plan, after: Plan): EventChanges {
  const stopsBefore = stopsByOrder(before)
  const stopsAfter = stopsByOrder(after)
  const changed = diff.changed
    .filter((change) => stopsBefore[change.order_id] && stopsAfter[change.order_id])
    .map((change) => ({
      orderId: change.order_id,
      before: stopsBefore[change.order_id],
      after: stopsAfter[change.order_id],
      kinds: visitKinds(change),
      shiftMin: minutes(change.to_start ?? '00:00') - minutes(change.from_start ?? '00:00'),
    }))
    .sort((a, b) => a.after.engineerId.localeCompare(b.after.engineerId) || a.after.position - b.after.position)
  const routes = [...diff.routes_changed].sort().map((engineerId) => ({
    engineerId,
    visitsBefore: before.routes.find((route) => route.engineer_id === engineerId)?.stops.length ?? 0,
    visitsAfter: after.routes.find((route) => route.engineer_id === engineerId)?.stops.length ?? 0,
    kmBefore: before.metrics.distance_by_engineer[engineerId] ?? 0,
    kmAfter: after.metrics.distance_by_engineer[engineerId] ?? 0,
  }))
  const currentStops = Object.values(stopsAfter)
  return {
    changed,
    added: present(diff.added.map((id) => stopsAfter[id])),
    removed: present([...diff.removed, ...diff.newly_unassigned].map((id) => stopsBefore[id])),
    frozen: currentStops
      .filter((ref) => ref.stop.locked)
      .sort((x, y) => x.engineerId.localeCompare(y.engineerId) || x.position - y.position),
    routes,
    lateWindowStops: currentStops.filter((ref) => ref.stop.late_min > 0),
  }
}

export interface EventRecord {
  event: PlanEvent
  diff: Diff
  before: Plan
  after: Plan
  changes: EventChanges
}

export interface EventReview {
  record: EventRecord
  scenario: Scenario
  added?: string
  decide: (apply: boolean) => void
  variants: Variant[]
  chosen: string
  dropsByPlan: Record<string, string[]>
  onChoose: (planId: string) => void
  onPreview: (planId: string | null) => void
  previewed: string | null
}

export const matchedFrom = (response: PlanResponse): Matched => ({
  optimized: response.optimized,
  baseline: response.baseline,
  control: response.control,
  scenario: response.scenario,
})

export const makeRecord = (event: PlanEvent, diff: Diff, before: Plan, after: Plan): EventRecord => ({
  event,
  diff,
  before,
  after,
  changes: changesFromDiff(diff, before, after),
})

export function addedLabel(event: PlanEvent, plan: Plan, scenario: Scenario): string | undefined {
  if (event.type !== 'urgent_order' && event.type !== 'new_order') {
    return undefined
  }
  const ref = stopsByOrder(plan)[event.order.id]
  if (!ref) {
    return `${event.order.id} не размещена`
  }
  return `${event.order.id} → ${engineerName(scenario.engineers, ref.engineerId)}, начало ${ref.stop.start}`
}

const visitKeys = (plan: Plan) =>
  new Map(plan.routes.flatMap((route) => route.stops.map((stop) => [stop.order_id, `${route.engineer_id}@${stop.start}`] as const)))

export function differingOrders(base: Plan, other: Plan): Set<string> {
  const baseKeys = visitKeys(base)
  return new Set([...visitKeys(other)].filter(([id, key]) => baseKeys.get(id) !== key).map(([id]) => id))
}

export function changedOrders(record: EventRecord | null): Set<string> {
  if (!record) {
    return new Set()
  }
  return new Set([...record.changes.changed.map((change) => change.orderId), ...record.changes.added.map((ref) => ref.stop.order_id)])
}

const CITY_PREFIX = /^(?:г\.\s*)?(?:город\s+)?/i
const MOSCOW_HEAD = /^(?:г\.\s*)?(?:город\s+)?москва\s+(?=[^,\s])/i

export function cityOf(address: string): string {
  if (MOSCOW_HEAD.test(address)) {
    return 'Москва'
  }
  return address.split(',')[0].trim().replace(CITY_PREFIX, '')
}

const BASE_PREFIX = /^выездная база:\s*/i

export function placeLabel(address: string): string {
  return BASE_PREFIX.test(address) ? address.replace(BASE_PREFIX, '') : addressWithoutCity(address)
}

export function displayAddress(address: string): string {
  if (!address.includes(',') && !MOSCOW_HEAD.test(address)) {
    return address
  }
  return `${cityOf(address)}, ${addressWithoutCity(address)}`
}

const MOSCOW = /^москва(\s|$)/i

export function orderCity(order: Pick<Order, 'address' | 'district'>): string {
  const head = cityOf(order.address)
  if (MOSCOW.test(head)) {
    return 'Москва'
  }
  return order.district || head
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export function addressInCity(address: string, city: string): string {
  const cityHead = new RegExp(`^(?:г\\.?\\s*)?(?:город\\s+)?${escapeRegExp(city)}(?:\\s*,\\s*|\\s+)(?=\\S)`, 'i')
  const parts = address.split(',').map((part) => part.trim())
  for (let index = 0; index < parts.length; index++) {
    const rest = parts.slice(index).join(', ')
    if (cityHead.test(rest)) {
      return rest.replace(cityHead, '')
    }
  }
  return addressWithoutCity(address)
}

export function addressWithoutCity(address: string): string {
  if (MOSCOW_HEAD.test(address)) {
    return address.replace(MOSCOW_HEAD, '')
  }
  const comma = address.indexOf(',')
  if (comma < 0) {
    return address
  }
  const rest = address.slice(comma + 1).trim()
  return rest || address
}

export interface BaselineComparison {
  delta: number
  better: boolean | null
}

export function compareWithBaseline(
  current: number,
  baseline: number,
  higherIsBetter: boolean,
): BaselineComparison {
  const delta = current - baseline
  if (delta === 0) {
    return { delta: 0, better: null }
  }
  return {
    delta,
    better: higherIsBetter ? delta > 0 : delta < 0,
  }
}

export interface KpiView {
  assigned: number
  total: number
  engineersUsed: number
  engineersTotal: number
  km: number
  rescheduled: number
  tiers: TierCoverage[]
  response: { median: number; max: number; over: number; measured: number } | null
}

export function kpiFromPlan(plan: Plan, scenario: Scenario): KpiView {
  const m = plan.metrics
  return {
    assigned: m.assigned,
    total: m.orders_total,
    engineersUsed: m.engineers_used,
    engineersTotal: m.engineers_total,
    km: m.distance_total_km,
    rescheduled: m.rescheduled,
    tiers: tierCoverage(scenario, assignedOrderIds(plan)),
    response: m.response_measured
      ? { median: m.response_median_min, max: m.response_max_min, over: m.response_over_norm, measured: m.response_measured }
      : null,
  }
}

export function emptyKpi(scenario: Scenario | null, engineerCount: number | null): KpiView {
  return {
    assigned: 0,
    total: scenario?.orders.length ?? 0,
    engineersUsed: 0,
    engineersTotal: engineerCount ?? scenario?.engineers.length ?? 0,
    km: 0,
    rescheduled: 0,
    tiers: scenario ? tierCoverage(scenario, new Set()) : [],
    response: null,
  }
}

export function kpiFromProgress(p: JobProgress, scenario: Scenario): KpiView {
  return {
    assigned: p.assigned,
    total: p.total,
    engineersUsed: p.engineers_used,
    engineersTotal: scenario.engineers.length,
    km: p.distance_km,
    rescheduled: 0,
    tiers: tierCoverage(scenario, new Set(Object.values(p.routes).flat())),
    response: null,
  }
}
