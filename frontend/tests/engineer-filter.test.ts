import { describe, expect, it } from 'vitest'

import { colorResolver } from '../src/colors'
import { dimmedEngineerIds, NO_FILTER, toggled } from '../src/engineer-filter'
import type { Engineer, Scenario } from '../src/types'

const engineer = (id: string, transport: Engineer['transport'], skills: Engineer['skills'], lat: number): Engineer =>
  ({ id, name: id, transport, skills, start: { lat, lon: 37, address: id } }) as unknown as Engineer

const engineers = [
  engineer('E1', 'car', ['local'], 55.7),
  engineer('E2', 'foot', ['local', 'emergency'], 55.7),
  engineer('E3', 'car', ['connection'], 55.8),
]
const scenario = { office: { lat: 55.7, lon: 37, address: 'Офис' }, engineers } as unknown as Scenario

describe('engineer filter', () => {
  it('dims nobody without a filter', () => {
    expect(dimmedEngineerIds(engineers, NO_FILTER).size).toBe(0)
  })

  it('combines skill and transport groups', () => {
    const dimmed = dimmedEngineerIds(engineers, { skills: ['local'], transports: ['car'] })
    expect([...dimmed].sort()).toEqual(['E2', 'E3'])
  })

  it('toggles items', () => {
    expect(toggled(['a'], 'b')).toEqual(['a', 'b'])
    expect(toggled(['a', 'b'], 'a')).toEqual(['b'])
  })
})

describe('color modes', () => {
  it('gives one color to engineers of one start place', () => {
    const colorOf = colorResolver('office', scenario)
    expect(colorOf('E1')).toBe(colorOf('E2'))
    expect(colorOf('E1')).not.toBe(colorOf('E3'))
  })

  it('gives one color to one transport', () => {
    const colorOf = colorResolver('transport', scenario)
    expect(colorOf('E1')).toBe(colorOf('E3'))
    expect(colorOf('E1')).not.toBe(colorOf('E2'))
  })

  it('keeps engineer colors distinct', () => {
    const colorOf = colorResolver('engineer', scenario)
    expect(new Set(['E1', 'E2', 'E3'].map(colorOf)).size).toBe(3)
  })
})
