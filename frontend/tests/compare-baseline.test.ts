import { describe, expect, it } from 'vitest'

import { compareWithBaseline } from '../src/derive'
import { km, signed } from '../src/labels'

describe('compareWithBaseline', () => {
  it('handles higher-is-better metrics', () => {
    expect(compareWithBaseline(58, 51, true)).toEqual({ delta: 7, better: true })
    expect(compareWithBaseline(45, 51, true)).toEqual({ delta: -6, better: false })
    expect(compareWithBaseline(51, 51, true)).toEqual({ delta: 0, better: null })
  })

  it('handles lower-is-better metrics', () => {
    expect(compareWithBaseline(8, 10, false)).toEqual({ delta: -2, better: true })
    expect(compareWithBaseline(12, 10, false)).toEqual({ delta: 2, better: false })
    expect(compareWithBaseline(10, 10, false)).toEqual({ delta: 0, better: null })
  })

  it('handles floating point values and formats with km and signed', () => {
    const { delta, better } = compareWithBaseline(130.6, 143.0, false)
    expect(better).toBe(true)
    expect(delta).toBeCloseTo(-12.4)
    expect(`база ${km(143.0, 1)} км · ${signed(delta, 1)}`).toBe('база 143,0 км · −12,4')
  })

  it('formats integer baseline comparison correctly', () => {
    const { delta } = compareWithBaseline(58, 51, true)
    expect(`база ${km(51, 0)} · ${signed(delta, 0)}`).toBe('база 51 · +7')
  })
})
