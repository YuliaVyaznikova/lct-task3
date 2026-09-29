import { describe, expect, it } from 'vitest'

import { changesBetween, verdictAgainst } from '../src/variant-diff'
import type { Metrics, Plan } from '../src/types'

const metrics = (over: Partial<Metrics>): Metrics =>
  ({ assigned: 10, engineers_used: 4, distance_total_km: 100, late_risk: 0, rescheduled: 0, ...over }) as Metrics

const plan = (routes: Record<string, string[]>): Plan =>
  ({
    id: 'p',
    metrics: { distance_by_engineer: {} },
    routes: Object.entries(routes).map(([engineer_id, ids]) => ({
      engineer_id,
      stops: ids.map((order_id) => ({ order_id })),
    })),
  }) as unknown as Plan

describe('verdictAgainst', () => {
  it('writes coverage, engineers and km phrases', () => {
    const verdict = verdictAgainst(metrics({ assigned: 12, engineers_used: 5, distance_total_km: 118 }), metrics({}))
    expect(verdict.pros).toEqual(['на 2 заявки больше'])
    expect(verdict.cons).toEqual(['занят ещё один инженер', 'на 18 км длиннее'])
  })

  it('does not praise fewer km or engineers when coverage drops', () => {
    const verdict = verdictAgainst(metrics({ assigned: 8, engineers_used: 3, distance_total_km: 60 }), metrics({}))
    expect(verdict.pros).toEqual([])
    expect(verdict.cons).toEqual(['на 2 заявки меньше'])
  })

  it('praises shorter km when coverage is kept', () => {
    expect(verdictAgainst(metrics({ distance_total_km: 80 }), metrics({})).pros).toEqual(['на 20 км короче'])
  })
})

describe('changesBetween', () => {
  it('finds visits and routes that differ between plans', () => {
    const reference = plan({ E1: ['A', 'B'], E2: ['C'] })
    const other = plan({ E1: ['A', 'C', 'D'], E2: [] })
    const changes = changesBetween(reference, other)
    expect(changes.added.map((ref) => ref.stop.order_id)).toEqual(['D'])
    expect(changes.removed.map((ref) => ref.stop.order_id)).toEqual(['B'])
    expect(changes.changed.map((c) => [c.orderId, c.kinds])).toEqual([['C', ['engineer']]])
    expect(changes.routes.map((route) => route.engineerId)).toEqual(['E1', 'E2'])
  })
})
