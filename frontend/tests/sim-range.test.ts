import { describe, expect, it } from 'vitest'

import { dayRange } from '../src/sim'
import type { Route, Scenario } from '../src/types'

const scenario = (shifts: [string, string][]) =>
  ({ engineers: shifts.map(([shift_start, shift_end], i) => ({ id: `E${i}`, shift_start, shift_end })) }) as unknown as Scenario

describe('границы дня симуляции', () => {
  it('начинает день с самой ранней смены', () => {
    expect(dayRange(scenario([['10:00', '22:00']]), [])).toEqual([600, 1320])
    expect(dayRange(scenario([['10:00', '22:00'], ['08:30', '17:30']]), [])).toEqual([510, 1320])
  })

  it('продлевает день до последнего визита', () => {
    const routes = [{ stops: [{ finish: '22:40' }] }] as unknown as Route[]
    expect(dayRange(scenario([['10:00', '22:00']]), routes)).toEqual([600, 1380])
  })
})
