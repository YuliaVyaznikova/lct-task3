import { useCallback, useRef, useState } from 'react'

import { api, ApiError, streamJob, type PlanRequest } from './api'
import { VARIANT_ORDER } from './labels'
import type { JobProgress, Plan, PlanEvent, PlanResponse, ReplanResponse, RunningJob } from './types'

const BALANCE_PHASE_S = 6

function parseReplan(data: unknown): ReplanResponse {
  const body = data as Partial<ReplanResponse>
  if (!body.plan || !body.diff || !body.scenario) {
    throw new ApiError('Сервис прислал неполный итог перепланирования.', 0)
  }
  return body as ReplanResponse
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
      last: null,
      byVariant: {},
      expected: request.objective === 'auto' ? VARIANT_ORDER : [request.objective],
    })
    try {
      const { job_id } = await api.planJob(request, controller.signal)
      const response = await streamJob<PlanResponse>(job_id, { onProgress, signal: controller.signal })
      return abortRef.current === controller ? response : null
    } finally {
      if (abortRef.current === controller) {
        setJob(null)
      }
    }
  }, [onProgress])

  const requestEvent = useCallback(async (before: Plan, event: PlanEvent): Promise<ReplanResponse> => {
    setJob({
      kind: 'event',
      label: 'Перестраиваем план',
      startedAt: Date.now(),
      budgetS: before.params.time_limit_s,
      last: null,
      byVariant: {},
      expected: [],
    })
    try {
      const { job_id } = await api.eventJob(before.id, event)
      return await streamJob<ReplanResponse>(job_id, { onProgress, parse: parseReplan })
    } finally {
      setJob(null)
    }
  }, [onProgress])

  return { job, cancelPlan, requestPlan, requestEvent }
}
