import { formatMinutes, minutes } from '../time'
import type { Engineer, Route } from '../types'

interface MiniScheduleProps {
  engineer: Engineer
  route: Route | undefined
  range: [number, number]
  color: string
}

interface Piece {
  kind: 'travel' | 'work' | 'lunch'
  from: number
  to: number
}

function pieces(route: Route): Piece[] {
  const parts: Piece[] = route.stops.flatMap((stop) => {
    const arrival = minutes(stop.arrival)
    const departure = stop.departure ? minutes(stop.departure) : arrival - stop.travel_min
    return [
      { kind: 'travel' as const, from: departure, to: arrival },
      { kind: 'work' as const, from: minutes(stop.start), to: minutes(stop.finish) },
    ]
  })
  if (route.break) {
    parts.push({ kind: 'lunch', from: minutes(route.break.start), to: minutes(route.break.finish) })
  }
  return parts
}

function summary(route: Route | undefined): string {
  if (!route?.stops.length) {
    return 'Нет визитов'
  }
  const lunch = route.break ? `, обед ${route.break.start}–${route.break.finish}` : ''
  return `Работа ${formatMinutes(route.work_min)}, в пути ${formatMinutes(route.travel_min)}, ожидание ${formatMinutes(route.wait_min)}${lunch}`
}

export function MiniSchedule({ engineer, route, range, color }: MiniScheduleProps) {
  const [from, to] = range
  const span = Math.max(to - from, 1)
  const left = (value: number) => `${((value - from) / span) * 100}%`
  const width = (a: number, b: number) => `${(Math.max(b - a, 0) / span) * 100}%`
  const shiftStart = minutes(engineer.shift_start)
  const shiftEnd = minutes(engineer.shift_end)
  return (
    <span className="mini" title={summary(route)}>
      <i className="mini-shift" style={{ left: left(shiftStart), width: width(shiftStart, shiftEnd) }} />
      {route &&
        pieces(route).map((piece, index) => (
          <i
            key={index}
            className={`mini-${piece.kind}`}
            style={{ left: left(piece.from), width: width(piece.from, piece.to), ...(piece.kind === 'work' ? { background: color } : {}) }}
          />
        ))}
    </span>
  )
}
