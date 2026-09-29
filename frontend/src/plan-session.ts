import { api } from './api'
import { kpiFromPlan, kpiFromProgress, makeRecord, stopsByOrder, type EventRecord, type KpiView } from './derive'
import { engineerName } from './labels'
import type { JobProgress, Plan, PlanEvent, ReplanResponse, Scenario } from './types'

export const stripStatus = (message: string) => message.replace(/^\d{3}:\s*/, '')

export const isAbort = (error: unknown) => (error as Error).name === 'AbortError'

export function describeAssignment(orderId: string, engineerId: string | null, after: Plan, engineers: Scenario['engineers']): string {
  if (!engineerId) {
    return `${orderId} снята с маршрута.`
  }
  const ref = stopsByOrder(after)[orderId]
  if (!ref) {
    return `${orderId} передана ${engineerName(engineers, engineerId)}.`
  }
  return `${orderId} у ${engineerName(engineers, ref.engineerId)}: визит ${ref.position}, начало ${ref.stop.start}.`
}

export async function collectEventRecords(event: PlanEvent, before: Plan, response: ReplanResponse): Promise<Record<string, EventRecord>> {
  const recommended = response.plan
  const records: Record<string, EventRecord> = { [recommended.id]: makeRecord(event, response.diff, before, recommended) }
  const others = response.variants.filter((v) => v.plan_id !== recommended.id)
  const fetched = await Promise.all(others.map((v) => api.getPlan(v.plan_id).catch(() => null)))
  others.forEach((v, index) => {
    const other = fetched[index]
    if (other?.diff) {
      records[v.plan_id] = makeRecord(event, other.diff, before, other.optimized)
    }
  })
  return records
}

export function currentKpi(progress: JobProgress | null, plan: Plan | null, scenario: Scenario | null): KpiView | null {
  if (!scenario) {
    return null
  }
  if (progress) {
    return kpiFromProgress(progress, scenario)
  }
  return plan ? kpiFromPlan(plan, scenario) : null
}

export function planEventMessage(error: unknown): string {
  const message = stripStatus((error as Error).message)
  if (/Input should be|Field required|Extra inputs/.test(message)) {
    return 'сервис не принимает такое событие'
  }
  return message
}
