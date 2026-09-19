/** Цвет инженера фиксирован по его позиции в справочнике.
 *  Это нужно, чтобы при сравнении «до / после» маршруты не меняли цвет
 *  и диспетчер видел именно изменение плана, а не перекраску карты. */

const PALETTE = [
  '#3f76c4',
  '#c9513e',
  '#4c9f70',
  '#b4762c',
  '#7a5ea8',
  '#2b8a9e',
  '#c2537f',
  '#6b8f2f',
  '#8a6a4a',
  '#4a6fa5',
  '#a4483f',
  '#2f7d5c',
  '#8c6d1f',
  '#5d5f9c',
  '#3f8a8a',
]

export function engineerColor(engineerIds: string[], engineerId: string): string {
  const index = engineerIds.indexOf(engineerId)
  return PALETTE[(index < 0 ? 0 : index) % PALETTE.length]
}

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
  if (value < 60) return `${value} мин`
  const h = Math.floor(value / 60)
  const m = value % 60
  return m === 0 ? `${h} ч` : `${h} ч ${m} мин`
}
