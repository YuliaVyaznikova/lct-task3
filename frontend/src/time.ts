import type { Stop } from './types'

export function minutes(value: string): number {
  const [h, m] = value.split(':').map(Number)
  return h * 60 + m
}

export function hhmm(value: number): string {
  const h = Math.floor(value / 60)
  const m = Math.round(value % 60)
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

export function formatMinutes(value: number): string {
  if (value < 60) {
    return `${value} мин`
  }
  const h = Math.floor(value / 60)
  const m = value % 60
  return m === 0 ? `${h} ч` : `${h} ч ${m} мин`
}

export const departureMin = (stop: Stop) => (stop.departure ? minutes(stop.departure) : minutes(stop.arrival) - stop.travel_min)
