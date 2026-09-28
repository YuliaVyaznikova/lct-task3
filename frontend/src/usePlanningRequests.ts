import { useCallback, useRef, useState } from 'react'

import { api, ApiError, isMissing, streamJob, type PlanRequest } from './api'
import type { RunningJob } from './components/VariantBar'
import type { JobProgress, Plan, PlanEvent, PlanResponse, ReplanResponse } from './types'

const BALANCE_PHASE_S = 6

function parseReplan(data: unknown): ReplanResponse {
  const body = data as Partial<ReplanResponse> & { optimized?: ReplanResponse['plan'] }
  const plan = body.plan ?? body.optimized
  if (!plan || !body.scenario) throw new ApiError('Сервис прислал неполный итог перепланирования.', 0)
  return { plan, diff: body.diff as ReplanResponse['diff'], scenario: body.scenario }
}

export async function loadSelectedVariant(planId: string): Promise<PlanResponse> {
  try {
    const body = await api.select(planId)
    if (body && 'optimized' in body) return body as PlanResponse
  } catch (error) {
    if (!isMissing(error)) throw error
  }
  return api.getPlan(planId)
}

export function usePlanningRequests() {
  const [job, setJob] = useState<RunningJob | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const onProgress = useCallback((progress: JobProgress) => {
    setJob((current) =>
      current
        ? {
            ...current,
            last: progress,
            byVariant: { ...current.byVariant, [progress.variant || 'plan']: progress },
            improvements: current.improvements + 1,
          }
        : current,
    )
  }, [])

  const cancelPlan = useCallback(() => abortRef.current?.abort(), [])

  const requestPlan = useCallback(async (request: PlanRequest): Promise<PlanResponse | null> => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setJob({
      kind: 'plan',
      label: 'Идёт расчёт',
      startedAt: Date.now(),
      budgetS: request.objective === 'auto' || request.objective === 'balanced' ? request.timeLimit + BALANCE_PHASE_S : request.timeLimit,
      streaming: true,
      last: null,
      byVariant: {},
      improvements: 0,
      expected: request.objective === 'auto' ? ['min_engineers', 'min_distance', 'balanced'] : [request.objective],
    })
    try {
      let response: PlanResponse
      try {
        const { job_id } = await api.planJob(request, controller.signal)
        response = await streamJob<PlanResponse>(job_id, { onProgress, signal: controller.signal })
      } catch (error) {
        if (!isMissing(error)) throw error
        setJob((current) => (current ? { ...current, streaming: false } : current))
        response = await api.plan(request, controller.signal)
      }
      return abortRef.current === controller ? response : null
    } finally {
      if (abortRef.current === controller) setJob(null)
    }
  }, [onProgress])

  const requestEvent = useCallback(async (before: Plan, event: PlanEvent): Promise<ReplanResponse> => {
    setJob({
      kind: 'event',
      label: 'Перестраиваем план',
      startedAt: Date.now(),
      budgetS: before.params.time_limit_s,
      streaming: true,
      last: null,
      byVariant: {},
      improvements: 0,
      expected: [],
    })
    try {
      try {
        const { job_id } = await api.eventJob(before.id, event)
        return await streamJob<ReplanResponse>(job_id, { onProgress, parse: parseReplan })
      } catch (error) {
        if (!isMissing(error)) throw error
        setJob((current) => (current ? { ...current, streaming: false } : current))
        return await api.event(before.id, event)
      }
    } finally {
      setJob(null)
    }
  }, [onProgress])

  return { job, cancelPlan, requestPlan, requestEvent }
}
