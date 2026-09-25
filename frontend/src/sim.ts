import { minutes } from './colors'
import { orderPoint, pointAlong, startPoint, type LatLon } from './geo'
import type { Engineer, Order, PlanEvent, Route, Scenario } from './types'

export type SimStatus =
  | 'moving'
  | 'onsite'
  | 'waiting'
  | 'lunch'
  | 'idle'
  | 'done'
  | 'unavailable'
  | 'delayed'

export const STATUS_RU: Record<SimStatus, string> = {
  moving: 'в пути',
  onsite: 'на объекте',
  waiting: 'ждёт окна',
  lunch: 'обед',
  idle: 'свободен',
  done: 'смена окончена',
  unavailable: 'недоступен',
  delayed: 'задержка',
}

export interface EngineerState {
  engineerId: string
  status: SimStatus
  position: LatLon | null
  orderId: string | null
  until: number | null
  done: number
  total: number
}

export interface EngineerMarks {
  unavailableFrom?: number
  delays: { from: number; to: number }[]
}

export function marksFromEvents(events: PlanEvent[]): Record<string, EngineerMarks> {
  const marks: Record<string, EngineerMarks> = {}
  const get = (id: string) => (marks[id] ??= { delays: [] })
  for (const event of events) {
    if (event.type === 'engineer_unavailable') {
      const m = get(event.engineer_id)
      const at = minutes(event.time)
      m.unavailableFrom = Math.min(m.unavailableFrom ?? Infinity, at)
    } else if (event.type === 'engineer_delayed') {
      const at = minutes(event.time)
      get(event.engineer_id).delays.push({ from: at, to: at + event.minutes })
    }
  }
  return marks
}

export function engineerState(
  clock: number,
  engineer: Engineer,
  route: Route | undefined,
  legs: LatLon[][],
  scenario: Scenario,
  orders: Record<string, Order>,
  marks: EngineerMarks | undefined,
): EngineerState {
  const stops = route?.stops ?? []
  const baseState: EngineerState = {
    engineerId: engineer.id,
    status: 'idle',
    position: startPoint(engineer, scenario),
    orderId: stops[0]?.order_id ?? null,
    until: stops.length ? (stops[0].departure ? minutes(stops[0].departure) : minutes(stops[0].arrival) - stops[0].travel_min) : null,
    done: stops.filter((stop) => minutes(stop.finish) <= clock).length,
    total: stops.length,
  }

  const lunch = route?.break
  const lunchFrom = lunch ? minutes(lunch.start) : 0
  const lunchTo = lunch ? minutes(lunch.finish) : 0
  const lunchMinutesWithin = (from: number, to: number) =>
    lunch ? Math.max(0, Math.min(to, lunchTo) - Math.max(from, lunchFrom)) : 0

  let state: EngineerState = baseState
  for (let i = 0; i < stops.length; i += 1) {
    const stop = stops[i]
    const arrival = minutes(stop.arrival)
    const departure = stop.departure ? minutes(stop.departure) : arrival - stop.travel_min
    const start = minutes(stop.start)
    const finish = minutes(stop.finish)
    const stopPoint = orderPoint(orders[stop.order_id])
    if (clock < departure) break
    if (clock < arrival) {
      const drivingMinutes = arrival - departure - lunchMinutesWithin(departure, arrival)
      const travelShare = drivingMinutes > 0 ? (clock - departure - lunchMinutesWithin(departure, clock)) / drivingMinutes : 1
      state = { ...baseState, status: 'moving', position: pointAlong(legs[i] ?? [], travelShare) ?? stopPoint, orderId: stop.order_id, until: arrival }
      break
    }
    if (clock < start) {
      state = { ...baseState, status: 'waiting', position: stopPoint, orderId: stop.order_id, until: start }
      break
    }
    if (clock < finish) {
      state = { ...baseState, status: 'onsite', position: stopPoint, orderId: stop.order_id, until: finish }
      break
    }
    const next = stops[i + 1]
    state = {
      ...baseState,
      status: 'idle',
      position: stopPoint,
      orderId: next?.order_id ?? null,
      until: next ? (next.departure ? minutes(next.departure) : minutes(next.arrival) - next.travel_min) : null,
    }
  }

  if (!stops.length || clock >= minutes(stops[stops.length - 1].finish)) {
    if (clock >= minutes(engineer.shift_end)) state = { ...state, status: 'done', orderId: null, until: null }
  }

  if (lunch && clock >= lunchFrom && clock < lunchTo && state.status !== 'onsite') {
    state = { ...state, status: 'lunch', until: lunchTo }
  }

  if (marks) {
    const delay = marks.delays.find((period) => clock >= period.from && clock < period.to)
    if (delay && state.status !== 'onsite') state = { ...state, status: 'delayed', until: delay.to }
    if (marks.unavailableFrom !== undefined && clock >= marks.unavailableFrom && state.status !== 'onsite') {
      state = { ...state, status: 'unavailable', until: null }
    }
  }
  return state
}

export function dayRange(scenario: Scenario, routes: Route[]): [number, number] {
  const starts = scenario.engineers.map((e) => minutes(e.shift_start))
  const ends = scenario.engineers.map((e) => minutes(e.shift_end))
  const finishes = routes.flatMap((r) => r.stops.map((s) => minutes(s.finish)))
  const from = Math.min(...starts, 9 * 60)
  const to = Math.max(...ends, ...finishes, 18 * 60)
  return [Math.floor(from / 30) * 30, Math.ceil(to / 30) * 30]
}
