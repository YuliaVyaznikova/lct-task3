import { effectiveTier } from './labels'
import type { Engineer, Metrics, Order, Plan, Route, Scenario, Stop } from './types'
import { minutes } from './colors'

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

export function ordersById(scenario: Scenario): Record<string, Order> {
  return Object.fromEntries(scenario.orders.map((o) => [o.id, o]))
}

export function engineersById(scenario: Scenario): Record<string, Engineer> {
  return Object.fromEntries(scenario.engineers.map((e) => [e.id, e]))
}

export interface TierCoverage {
  tier: number
  assigned: number
  total: number
}

export function tierCoverage(plan: Plan, scenario: Scenario): TierCoverage[] {
  const assigned = new Set(plan.routes.flatMap((r) => r.stops.map((s) => s.order_id)))
  const tiers = new Map<number, TierCoverage>()
  for (const order of scenario.orders) {
    const tier = effectiveTier(order)
    const row = tiers.get(tier) ?? { tier, assigned: 0, total: 0 }
    row.total += 1
    if (assigned.has(order.id)) row.assigned += 1
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
  if (!visits) return null
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
  frozen: StopRef[]
  routes: RouteChange[]
  lateWindowStops: StopRef[]
}

export function eventChanges(before: Plan, after: Plan, backendChangedRouteIds: string[]): EventChanges {
  const stopsBefore = stopsByOrder(before)
  const stopsAfter = stopsByOrder(after)
  const changed: VisitChange[] = []
  const added: StopRef[] = []

  for (const [orderId, next] of Object.entries(stopsAfter)) {
    const prev = stopsBefore[orderId]
    if (!prev) {
      added.push(next)
      continue
    }
    const kinds: ChangeKind[] = []
    if (prev.engineerId !== next.engineerId) kinds.push('engineer')
    else if (prev.position !== next.position) kinds.push('position')
    if (prev.stop.start !== next.stop.start) kinds.push('time')
    if (kinds.length) {
      changed.push({
        orderId,
        before: prev,
        after: next,
        kinds,
        shiftMin: minutes(next.stop.start) - minutes(prev.stop.start),
      })
    }
  }
  changed.sort(
    (a, b) =>
      a.after.engineerId.localeCompare(b.after.engineerId) || a.after.position - b.after.position,
  )

  const routeOrderIds = (route: Route | undefined) => (route?.stops ?? []).map((stop) => stop.order_id)
  const engineerIds = new Set([
    ...before.routes.map((r) => r.engineer_id),
    ...after.routes.map((r) => r.engineer_id),
  ])
  const routes: RouteChange[] = []
  for (const id of engineerIds) {
    const beforeRoute = before.routes.find((route) => route.engineer_id === id)
    const afterRoute = after.routes.find((route) => route.engineer_id === id)
    const sameVisitOrder = routeOrderIds(beforeRoute).join('|') === routeOrderIds(afterRoute).join('|')
    const sameVisitStarts =
      sameVisitOrder && (beforeRoute?.stops ?? []).every((stop, index) => afterRoute?.stops[index]?.start === stop.start)
    if (sameVisitOrder && sameVisitStarts && !backendChangedRouteIds.includes(id)) continue
    routes.push({
      engineerId: id,
      visitsBefore: beforeRoute?.stops.length ?? 0,
      visitsAfter: afterRoute?.stops.length ?? 0,
      kmBefore: before.metrics.distance_by_engineer[id] ?? 0,
      kmAfter: after.metrics.distance_by_engineer[id] ?? 0,
    })
  }
  routes.sort((x, y) => x.engineerId.localeCompare(y.engineerId))

  const allCurrentStops = Object.values(stopsAfter)
  return {
    changed,
    added,
    frozen: allCurrentStops
      .filter((ref) => ref.stop.locked)
      .sort((x, y) => x.engineerId.localeCompare(y.engineerId) || x.position - y.position),
    routes,
    lateWindowStops: allCurrentStops.filter((ref) => ref.stop.late_min > 0),
  }
}

export function coveragePercent(m: Metrics): number {
  return m.orders_total ? Math.round((m.assigned / m.orders_total) * 100) : 0
}

export interface EventRecord {
  event: import('./types').PlanEvent
  diff: import('./types').Diff
  before: Plan
  after: Plan
  changes: EventChanges
}
