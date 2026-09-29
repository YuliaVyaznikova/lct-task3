import { departureMin, hhmm, minutes } from './time'
import type { Stop } from './types'

export type StepState = 'done' | 'current' | 'todo'

export interface VisitStep {
  key: 'assigned' | 'departed' | 'arrived' | 'waiting' | 'started' | 'finished'
  label: string
  time: string | null
  at: number
  state: StepState
  note: string | null
}

type StepDraft = Omit<VisitStep, 'state' | 'note'>

function draftSteps(stop: Stop): StepDraft[] {
  const steps: StepDraft[] = [
    { key: 'assigned', label: 'Назначена', time: null, at: -Infinity },
    { key: 'departed', label: 'Выехал', time: hhmm(departureMin(stop)), at: departureMin(stop) },
    { key: 'arrived', label: 'Прибыл', time: stop.arrival, at: minutes(stop.arrival) },
  ]
  if (stop.wait_min > 0) {
    steps.push({ key: 'waiting', label: 'Ожидание окна', time: `до ${stop.start}`, at: minutes(stop.arrival) })
  }
  steps.push(
    { key: 'started', label: 'Начал работу', time: stop.start, at: minutes(stop.start) },
    { key: 'finished', label: 'Завершил', time: stop.finish, at: minutes(stop.finish) },
  )
  return steps
}

function liveNote(key: VisitStep['key'], stop: Stop): string | null {
  switch (key) {
    case 'assigned':
      return `выедет в ${hhmm(departureMin(stop))}`
    case 'departed':
      return `в пути, приедет в ${stop.arrival}`
    case 'waiting':
      return `ждёт окна до ${stop.start}`
    case 'arrived':
    case 'started':
      return `на объекте до ${stop.finish}`
    default:
      return null
  }
}

function currentIndex(steps: StepDraft[], now: number): number {
  let index = 0
  steps.forEach((step, i) => {
    if (step.at <= now) {
      index = i
    }
  })
  return index
}

export function visitSteps(stop: Stop, now: number | null): VisitStep[] {
  const drafts = draftSteps(stop)
  if (now === null) {
    return drafts.map((step) => ({ ...step, state: 'todo', note: null }))
  }
  const current = currentIndex(drafts, now)
  const finished = drafts[current].key === 'finished'
  return drafts.map((step, i) => {
    if (i < current || (finished && i === current)) {
      return { ...step, state: 'done', note: null }
    }
    if (i === current) {
      return { ...step, state: 'current', note: liveNote(step.key, stop) }
    }
    return { ...step, state: 'todo', note: null }
  })
}
