import { haversineKm, orderPoint, startPoint, type LatLon } from './geo'
import { staticMismatch } from './labels'
import type { Candidate, Order, Plan, Scenario } from './types'

const DETOUR = 1.3

function pathKm(points: LatLon[]): number {
  let total = 0
  for (let i = 1; i < points.length; i += 1) total += haversineKm(points[i - 1], points[i])
  return total * DETOUR
}

export interface EstimatedCandidate extends Candidate {
  estimated: true
}

export function estimateCandidates(plan: Plan, scenario: Scenario, orderId: string): EstimatedCandidate[] {
  const orders = Object.fromEntries(scenario.orders.map((o) => [o.id, o])) as Record<string, Order>
  const order = orders[orderId]
  const target = orderPoint(order)
  const donor = plan.routes.find((r) => r.stops.some((s) => s.order_id === orderId))
  const pointsOf = (engineerId: string, ids: string[]) => {
    const start = startPoint(scenario.engineers.find((e) => e.id === engineerId), scenario)
    return [start, ...ids.map((id) => orderPoint(orders[id]))].filter(Boolean) as LatLon[]
  }

  let donorRemoved = 0
  let donorAfter: string[] = []
  if (donor) {
    const ids = donor.stops.map((s) => s.order_id)
    donorAfter = ids.filter((id) => id !== orderId)
    donorRemoved = pathKm(pointsOf(donor.engineer_id, ids)) - pathKm(pointsOf(donor.engineer_id, donorAfter))
  }

  const rows: EstimatedCandidate[] = []
  for (const engineer of scenario.engineers) {
    if (engineer.id === donor?.engineer_id) continue
    const blank: EstimatedCandidate = {
      estimated: true,
      engineer_id: engineer.id,
      feasible: false,
      reason_code: null,
      reason: null,
      position: null,
      arrival: null,
      start: null,
      added_km: null,
      donor_removed_km: null,
      total_delta_km: null,
      shifted: [],
      preview_routes: {},
    }
    const mismatch = order ? staticMismatch(order, engineer) : 'нет данных о заявке'
    if (mismatch || !target) {
      rows.push({ ...blank, reason_code: mismatch ? 'NO_SKILL' : 'NO_COORDS', reason: mismatch || 'нет координат' })
      continue
    }
    const current = plan.routes.find((r) => r.engineer_id === engineer.id)?.stops.map((s) => s.order_id) ?? []
    const base = pathKm(pointsOf(engineer.id, current))
    let best = { position: current.length, added: Infinity }
    for (let i = 0; i <= current.length; i += 1) {
      const trial = [...current.slice(0, i), orderId, ...current.slice(i)]
      const added = pathKm(pointsOf(engineer.id, trial)) - base
      if (added < best.added) best = { position: i, added }
    }
    const next = [...current.slice(0, best.position), orderId, ...current.slice(best.position)]
    rows.push({
      ...blank,
      feasible: true,
      position: best.position,
      added_km: best.added,
      donor_removed_km: donor ? donorRemoved : 0,
      total_delta_km: best.added - (donor ? donorRemoved : 0),
      preview_routes: donor ? { [engineer.id]: next, [donor.engineer_id]: donorAfter } : { [engineer.id]: next },
    })
  }
  return rows.sort(
    (a, b) => Number(b.feasible) - Number(a.feasible) || (a.total_delta_km ?? 0) - (b.total_delta_km ?? 0),
  )
}
