import { changesFromDiff, stopsByOrder, type EventChanges } from './derive'
import { km, plural } from './labels'
import type { Change, Metrics, Plan } from './types'

export type DiffKey = 'assigned' | 'engineers' | 'distance' | 'late' | 'moved'

export const metricValue = (m: Metrics, key: DiffKey): number =>
  ({
    assigned: m.assigned,
    engineers: m.engineers_used,
    distance: Math.round(m.distance_total_km),
    late: m.late_risk,
    moved: m.rescheduled,
  })[key]

export interface Verdict {
  pros: string[]
  cons: string[]
}

const orderWord = (n: number) => plural(n, 'заявку', 'заявки', 'заявок')

const engineerWord = (n: number) => plural(n, 'инженер', 'инженера', 'инженеров')

const NO_VERDICT: Verdict = { pros: [], cons: [] }

const pro = (text: string): Verdict => ({ pros: [text], cons: [] })

const con = (text: string): Verdict => ({ pros: [], cons: [text] })

function coveragePhrase(delta: number): Verdict {
  const count = Math.abs(delta)
  if (delta > 0) {
    return pro(`на ${count} ${orderWord(count)} больше`)
  }
  return con(`на ${count} ${orderWord(count)} меньше`)
}

function engineersPhrase(delta: number, coverageHeld: boolean): Verdict {
  const count = Math.abs(delta)
  if (delta > 0) {
    return con(count === 1 ? 'занят ещё один инженер' : `заняты ещё ${count} ${engineerWord(count)}`)
  }
  if (!coverageHeld) {
    return NO_VERDICT
  }
  return pro(count === 1 ? 'освобождён один инженер' : `освобождены ${count} ${engineerWord(count)}`)
}

function distancePhrase(delta: number, objectiveHeld: boolean): Verdict {
  const distance = km(Math.abs(delta), 0)
  if (delta > 0) {
    return con(`на ${distance} км длиннее`)
  }
  return objectiveHeld ? pro(`на ${distance} км короче`) : NO_VERDICT
}

function latePhrase(delta: number, coverageHeld: boolean): Verdict {
  const count = Math.abs(delta)
  const word = plural(count, 'опоздание', 'опоздания', 'опозданий')
  if (delta > 0) {
    return con(`на ${count} ${word} больше`)
  }
  return coverageHeld ? pro(`на ${count} ${word} меньше`) : NO_VERDICT
}

function movedPhrase(delta: number, coverageHeld: boolean): Verdict {
  const count = Math.abs(delta)
  if (delta > 0) {
    return con(`переносит ещё ${count} ${orderWord(count)}`)
  }
  return coverageHeld ? pro(`переносит на ${count} ${orderWord(count)} меньше`) : NO_VERDICT
}

export function verdictAgainst(m: Metrics, reference: Metrics): Verdict {
  const delta = (key: DiffKey) => metricValue(m, key) - metricValue(reference, key)
  const coverageHeld = delta('assigned') >= 0
  const objectiveHeld = coverageHeld && delta('engineers') <= 0
  const parts: Verdict[] = []
  if (delta('assigned') !== 0) {
    parts.push(coveragePhrase(delta('assigned')))
  }
  if (delta('engineers') !== 0) {
    parts.push(engineersPhrase(delta('engineers'), coverageHeld))
  }
  if (delta('distance') !== 0) {
    parts.push(distancePhrase(delta('distance'), objectiveHeld))
  }
  if (delta('late') !== 0) {
    parts.push(latePhrase(delta('late'), coverageHeld))
  }
  if (delta('moved') !== 0) {
    parts.push(movedPhrase(delta('moved'), coverageHeld))
  }
  return {
    pros: parts.flatMap((part) => part.pros),
    cons: parts.flatMap((part) => part.cons),
  }
}

const routeSequences = (plan: Plan) => new Map(plan.routes.map((route) => [route.engineer_id, route.stops.map((stop) => stop.order_id).join(',')]))

function visitChanges(before: Plan, after: Plan): Change[] {
  const stopsBefore = stopsByOrder(before)
  const stopsAfter = stopsByOrder(after)
  return Object.keys(stopsAfter)
    .filter((id) => stopsBefore[id])
    .map((id) => ({
      order_id: id,
      from_engineer: stopsBefore[id].engineerId,
      to_engineer: stopsAfter[id].engineerId,
      from_seq: stopsBefore[id].position,
      to_seq: stopsAfter[id].position,
      from_start: stopsBefore[id].stop.start,
      to_start: stopsAfter[id].stop.start,
    }))
    .filter((c) => c.from_engineer !== c.to_engineer || c.from_seq !== c.to_seq || c.from_start !== c.to_start)
}

export function changesBetween(before: Plan, after: Plan): EventChanges {
  const stopsBefore = stopsByOrder(before)
  const stopsAfter = stopsByOrder(after)
  const sequencesBefore = routeSequences(before)
  const sequencesAfter = routeSequences(after)
  const engineers = new Set([...sequencesBefore.keys(), ...sequencesAfter.keys()])
  return changesFromDiff(
    {
      changed: visitChanges(before, after),
      added: Object.keys(stopsAfter).filter((id) => !stopsBefore[id]),
      removed: [],
      newly_unassigned: Object.keys(stopsBefore).filter((id) => !stopsAfter[id]),
      routes_changed: [...engineers].filter((id) => (sequencesBefore.get(id) ?? '') !== (sequencesAfter.get(id) ?? '')),
    },
    before,
    after,
  )
}
