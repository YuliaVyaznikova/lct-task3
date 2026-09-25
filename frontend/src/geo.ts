import type { Engineer, Order, Plan, PlanGeometry, Scenario } from './types'

export type LatLon = [number, number]

export function haversineKm(a: LatLon, b: LatLon): number {
  const earthRadiusKm = 6371
  const radians = (degrees: number) => (degrees * Math.PI) / 180
  const latitudeDelta = radians(b[0] - a[0])
  const longitudeDelta = radians(b[1] - a[1])
  const haversine =
    Math.sin(latitudeDelta / 2) ** 2 + Math.cos(radians(a[0])) * Math.cos(radians(b[0])) * Math.sin(longitudeDelta / 2) ** 2
  return 2 * earthRadiusKm * Math.asin(Math.sqrt(haversine))
}

export const orderPoint = (order: Order | undefined): LatLon | null =>
  order && order.lat != null && order.lon != null ? [order.lat, order.lon] : null

export function startPoint(engineer: Engineer | undefined, scenario: Scenario): LatLon | null {
  const p = engineer?.start ?? scenario.office
  if (p.lat != null && p.lon != null) return [p.lat, p.lon]
  if (scenario.office.lat != null && scenario.office.lon != null) return [scenario.office.lat, scenario.office.lon]
  return null
}

export function straightPath(
  engineerId: string,
  orderIds: string[],
  scenario: Scenario,
  orders: Record<string, Order>,
): LatLon[] {
  const engineer = scenario.engineers.find((e) => e.id === engineerId)
  const path: LatLon[] = []
  const start = startPoint(engineer, scenario)
  if (start) path.push(start)
  for (const id of orderIds) {
    const stopPoint = orderPoint(orders[id])
    if (stopPoint) path.push(stopPoint)
  }
  return path
}

export function routeLegs(
  plan: Plan,
  engineerId: string,
  scenario: Scenario,
  orders: Record<string, Order>,
  geometry: PlanGeometry | null,
): LatLon[][] {
  const route = plan.routes.find((r) => r.engineer_id === engineerId)
  if (!route) return []
  const serviceLegs = geometry?.legs?.[engineerId]
  if (serviceLegs && serviceLegs.length === route.stops.length && serviceLegs.every((leg) => leg.length >= 1)) {
    return serviceLegs
  }
  const engineer = scenario.engineers.find((e) => e.id === engineerId)
  let previousPoint = startPoint(engineer, scenario)
  return route.stops.map((stop) => {
    const stopPoint = orderPoint(orders[stop.order_id]) ?? previousPoint
    const leg: LatLon[] = previousPoint && stopPoint ? [previousPoint, stopPoint] : stopPoint ? [stopPoint] : []
    previousPoint = stopPoint
    return leg
  })
}

export function pointAlong(path: LatLon[], fraction: number): LatLon | null {
  if (!path.length) return null
  if (path.length === 1 || fraction <= 0) return path[0]
  if (fraction >= 1) return path[path.length - 1]
  const segmentLengthsKm: number[] = []
  let totalKm = 0
  for (let i = 1; i < path.length; i += 1) {
    const segmentKm = haversineKm(path[i - 1], path[i])
    segmentLengthsKm.push(segmentKm)
    totalKm += segmentKm
  }
  if (totalKm === 0) return path[path.length - 1]
  let remainingKm = fraction * totalKm
  for (let i = 0; i < segmentLengthsKm.length; i += 1) {
    if (remainingKm <= segmentLengthsKm[i]) {
      const segmentFraction = segmentLengthsKm[i] ? remainingKm / segmentLengthsKm[i] : 0
      const from = path[i]
      const to = path[i + 1]
      return [from[0] + (to[0] - from[0]) * segmentFraction, from[1] + (to[1] - from[1]) * segmentFraction]
    }
    remainingKm -= segmentLengthsKm[i]
  }
  return path[path.length - 1]
}
