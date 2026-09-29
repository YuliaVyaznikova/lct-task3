import { describe, expect, it } from 'vitest'

import { routeSequenceKey } from '../src/derive'
import { geometryFor, routePieces, straightPath, type LatLon, type RoadLegLookup } from '../src/geo'
import type { Order, Plan, PlanGeometry, Scenario } from '../src/types'

const office: LatLon = [55.7, 37.6]
const a: LatLon = [55.71, 37.61]
const b: LatLon = [55.72, 37.62]

const scenario = {
  office: { lat: office[0], lon: office[1], address: 'Офис' },
  engineers: [{ id: 'E1', name: 'Инженер 01', start: { lat: office[0], lon: office[1], address: 'Офис' } }],
} as unknown as Scenario

const orders = {
  A: { id: 'A', lat: a[0], lon: a[1] },
  B: { id: 'B', lat: b[0], lon: b[1] },
} as unknown as Record<string, Order>

const plan = (id: string, stops: string[]) =>
  ({ id, routes: [{ engineer_id: 'E1', stops: stops.map((order_id) => ({ order_id })) }] }) as unknown as Plan

const roadOfficeA: LatLon[] = [office, [55.705, 37.6], a]
const roadAB: LatLon[] = [a, [55.715, 37.615], b]
const roadRoute: LatLon[] = [...roadOfficeA, ...roadAB.slice(1)]

const geometry = (routes: Record<string, LatLon[]>, available = true): PlanGeometry => ({
  available,
  source: 'osrm',
  profile: 'driving',
  routes,
  errors: [],
})

const lookup = (legs: (LatLon[] | null | undefined)[]): RoadLegLookup => (_engineer, _orders, index) => legs[index]

const stopPoints = [office, a, b]

const hasStraightLeg = (pieces: LatLon[][]) =>
  pieces.some((piece) => piece.some((point, i) => i > 0 && stopPoints.includes(piece[i - 1]) && stopPoints.includes(point)))

const straight = straightPath('E1', ['A', 'B'], scenario, orders)

describe('маршрут плана', () => {
  it('пока геометрия грузится, линия не рисуется', () => {
    expect(routePieces('E1', ['A', 'B'], straight, { geometry: null })).toEqual([])
  })

  it('с геометрией рисуется дорогой', () => {
    const pieces = routePieces('E1', ['A', 'B'], straight, { geometry: geometry({ E1: roadRoute }) })
    expect(pieces).toEqual([roadRoute])
    expect(hasStraightLeg(pieces)).toBe(false)
  })

  it('прямая только если сервер ответил, что дороги нет', () => {
    expect(routePieces('E1', ['A', 'B'], straight, { geometry: geometry({}, false) })).toEqual([straight])
  })
})

describe('переключение плана', () => {
  it('новый план не берёт чужую геометрию и не рисует прямые до её прихода', () => {
    const before = plan('p1', ['A', 'B'])
    const after = plan('p2', ['B', 'A'])
    const known = { [routeSequenceKey(before)]: geometry({ E1: roadRoute }) }
    const shown = geometryFor(known, after)
    expect(shown).toBeNull()
    const pieces = routePieces('E1', ['B', 'A'], straightPath('E1', ['B', 'A'], scenario, orders), { geometry: shown })
    expect(pieces).toEqual([])
  })

  it('та же последовательность под другим id считается другим планом', () => {
    expect(routeSequenceKey(plan('p1', ['A']))).not.toBe(routeSequenceKey(plan('p2', ['A'])))
  })
})

describe('живые маршруты и превью', () => {
  it('без поиска дорог линия не рисуется', () => {
    expect(routePieces('E1', ['A', 'B'], straight, { roadLegs: null })).toEqual([])
  })

  it('загружающийся отрезок пропускается, а не заменяется прямой', () => {
    const pieces = routePieces('E1', ['A', 'B'], straight, { roadLegs: lookup([roadOfficeA, undefined]) })
    expect(pieces).toEqual([roadOfficeA])
    expect(pieces.flat()).not.toContain(b)
  })

  it('соседние дорожные отрезки склеиваются в одну линию', () => {
    expect(routePieces('E1', ['A', 'B'], straight, { roadLegs: lookup([roadOfficeA, roadAB]) })).toEqual([roadRoute])
  })

  it('прямой отрезок только там, где сервер сказал, что дороги нет', () => {
    const pieces = routePieces('E1', ['A', 'B'], straight, { roadLegs: lookup([roadOfficeA, null]) })
    expect(pieces).toEqual([[...roadOfficeA, b]])
  })

  it('ни один отрезок не рисуется прямой, пока все дороги грузятся', () => {
    const pieces = routePieces('E1', ['A', 'B'], straight, { roadLegs: lookup([undefined, undefined]) })
    expect(pieces).toEqual([])
    expect(hasStraightLeg(pieces)).toBe(false)
  })
})
