import { describe, expect, it } from 'vitest'

import { startPlaces } from '../src/geo'
import type { Scenario } from '../src/types'

const engineer = (id: string, lat: number | null, lon: number | null, address = 'Офис') => ({
  id,
  name: id,
  start: { lat, lon, address },
})

const scenario = (engineers: ReturnType<typeof engineer>[]) =>
  ({ office: { lat: 55.7, lon: 37.6, address: 'Офис' }, engineers }) as unknown as Scenario

describe('точки выезда', () => {
  it('инженеры без своей точки выезжают из офиса', () => {
    const places = startPlaces(scenario([engineer('E1', null, null), engineer('E2', 55.7, 37.6)]))
    expect(places).toHaveLength(1)
    expect(places[0].kind).toBe('office')
    expect(places[0].engineers.map((e) => e.id)).toEqual(['E1', 'E2'])
  })

  it('разные базы не сливаются с офисом и друг с другом', () => {
    const places = startPlaces(
      scenario([engineer('E1', 55.7, 37.6), engineer('E2', 55.4, 37.8, 'Домодедово'), engineer('E3', 55.9, 37.4, 'Химки'), engineer('E4', 55.4, 37.8, 'Домодедово')]),
    )
    expect(places.map((p) => [p.kind, p.address, p.engineers.map((e) => e.id)])).toEqual([
      ['office', 'Офис', ['E1']],
      ['base', 'Домодедово', ['E2', 'E4']],
      ['base', 'Химки', ['E3']],
    ])
    expect(places[1].point).toEqual([55.4, 37.8])
  })
})
