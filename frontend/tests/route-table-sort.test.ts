import { describe, expect, it } from 'vitest'

import { isGrouped, nextSort, sortGroups, sortStops } from '../src/components/RouteTable'
import type { Order, Route, Stop } from '../src/types'

const stop = (order_id: string, start: string) => ({ order_id, start }) as unknown as Stop
const orders = {
  A: { work_type: 'Ремонт' },
  B: { work_type: 'Аудит' },
  C: { work_type: 'Монтаж' },
} as unknown as Record<string, Order>
const group = (name: string, stops: Stop[]) => ({
  engineer: { id: name, name } as never,
  route: { stops } as unknown as Route,
})
const groups = [group('Яна', [stop('A', '10:00'), stop('B', '09:00')]), group('Аня', [stop('C', '08:00')])]

describe('nextSort', () => {
  it('cycles ascending, descending, off', () => {
    const asc = nextSort(null, 'time')
    expect(asc).toEqual({ key: 'time', descending: false })
    const desc = nextSort(asc, 'time')
    expect(desc).toEqual({ key: 'time', descending: true })
    expect(nextSort(desc, 'time')).toBeNull()
    expect(nextSort(desc, 'order')).toEqual({ key: 'order', descending: false })
  })
})

describe('isGrouped', () => {
  it('groups by engineer without a sort or with the engineer sort', () => {
    expect(isGrouped(null)).toBe(true)
    expect(isGrouped({ key: 'engineer', descending: true })).toBe(true)
    expect(isGrouped({ key: 'time', descending: false })).toBe(false)
  })
})

describe('sortGroups', () => {
  it('keeps natural order without a sort', () => {
    const result = sortGroups(groups, null)
    expect(result.map((g) => g.engineer.name)).toEqual(['Яна', 'Аня'])
    expect(result[0].stops.map((s) => s.index)).toEqual([0, 1])
  })

  it('orders engineers by name and reverses', () => {
    expect(sortGroups(groups, { key: 'engineer', descending: false }).map((g) => g.engineer.name)).toEqual(['Аня', 'Яна'])
    expect(sortGroups(groups, { key: 'engineer', descending: true }).map((g) => g.engineer.name)).toEqual(['Яна', 'Аня'])
  })
})

describe('sortStops', () => {
  const ids = (sort: Parameters<typeof sortStops>[1]) => sortStops(groups, sort, orders).map((s) => s.stop.order_id)

  it('sorts all stops by time across engineers and keeps visit numbers', () => {
    const result = sortStops(groups, { key: 'time', descending: false }, orders)
    expect(result.map((s) => s.stop.order_id)).toEqual(['C', 'B', 'A'])
    expect(result.map((s) => s.engineer.name)).toEqual(['Аня', 'Яна', 'Яна'])
    expect(result.map((s) => s.index)).toEqual([0, 1, 0])
  })

  it('sorts all stops by work type', () => {
    expect(ids({ key: 'workType', descending: false })).toEqual(['B', 'C', 'A'])
  })

  it('sorts all stops by order number descending', () => {
    expect(ids({ key: 'order', descending: true })).toEqual(['C', 'B', 'A'])
  })
})
