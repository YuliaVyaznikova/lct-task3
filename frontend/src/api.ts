import { humanizeCodes } from './labels'
import type {
  Candidate,
  JobProgress,
  Metrics,
  NearestWindow,
  Objective,
  PlanEvent,
  PlanGeometry,
  PlanResponse,
  SavedPlan,
  Scenario,
  ScenarioBrief,
  WorkType,
} from './types'

const BASE = '/api'

export interface LegScope {
  planId?: string | null
  scenarioId?: string | null
  engineerCount?: number | null
}

export interface RoadLegs {
  available: boolean
  legs: Record<string, ([number, number][] | null)[]>
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(BASE + path, {
      headers: init?.body instanceof FormData ? undefined : { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') {
      throw e
    }
    throw new ApiError('Сервис планирования не отвечает.', 0)
  }
  if (!response.ok) {
    let message = `Ошибка сервиса (${response.status})`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') {
        message = body.detail
      } else if (Array.isArray(body.detail)) {
        message = body.detail.map((d: any) => d.msg).join('; ')
      }
    } catch {}
    throw new ApiError(humanizeCodes(message), response.status)
  }
  return response.json() as Promise<T>
}

export interface PlanRequest {
  scenarioId: string
  objective: Objective
  timeLimit: number
  lunch: boolean
  engineerCount: number | null
  allowReschedule: boolean
  requiredOrders: string[]
}

const planRequestBody = (r: PlanRequest) =>
  JSON.stringify({
    scenario_id: r.scenarioId,
    params: {
      objective: r.objective,
      time_limit_s: r.timeLimit,
      lunch: r.lunch,
      allow_reschedule: r.allowReschedule,
      required_orders: r.requiredOrders,
    },
    engineer_count: r.engineerCount,
  })

export interface JobHandlers<T, P = JobProgress> {
  onProgress: (progress: P) => void
  signal?: AbortSignal
  parse?: (data: unknown) => T
}

export function streamJob<T, P = JobProgress>(jobId: string, handlers: JobHandlers<T, P>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const source = new EventSource(`${BASE}/plans/jobs/${encodeURIComponent(jobId)}/events`)
    let settled = false
    const settleAndClose = (fn: () => void) => {
      if (settled) {
        return
      }
      settled = true
      source.close()
      fn()
    }
    handlers.signal?.addEventListener('abort', () =>
      settleAndClose(() => reject(new DOMException('aborted', 'AbortError'))),
    )
    source.addEventListener('progress', (e) => {
      let progress: P
      try {
        progress = JSON.parse(e.data)
      } catch {
        return
      }
      handlers.onProgress(progress)
    })
    source.addEventListener('cancelled', () => settleAndClose(() => reject(new DOMException('cancelled', 'AbortError'))))
    source.addEventListener('done', (e) => {
      settleAndClose(() => {
        try {
          const data = JSON.parse(e.data)
          resolve(handlers.parse ? handlers.parse(data) : (data as T))
        } catch (err) {
          reject(new ApiError('Сервис прислал неполный итог расчёта.', 0))
        }
      })
    })
    source.addEventListener('error', (e) => {
      if (e instanceof MessageEvent) {
        let message = String(e.data)
        try {
          message = JSON.parse(e.data).detail
        } catch {}
        settleAndClose(() => reject(new ApiError(humanizeCodes(message), 0)))
        return
      }
      if (source.readyState === EventSource.CLOSED) {
        settleAndClose(() => reject(new ApiError('Связь с расчётом потеряна.', 0)))
      }
    })
  })
}

export const api = {
  scenarios: () => request<ScenarioBrief[]>('/scenarios'),

  scenario: (id: string) => request<Scenario>(`/scenarios/${id}`),
  scenarioBaseline: (id: string, engineerCount: number | null, signal?: AbortSignal) =>
    request<Metrics>(`/scenarios/${id}/baseline${engineerCount ? `?engineer_count=${engineerCount}` : ''}`, { signal }),

  workTypes: () => request<{ work_types: WorkType[] }>('/reference').then((r) => r.work_types),

  upload: (file: File) => {
    const form = new FormData()
    form.append('synthetic', file)
    return request<Scenario>('/scenarios/upload', { method: 'POST', body: form })
  },

  uploadJob: (file: File, signal?: AbortSignal) => {
    const form = new FormData()
    form.append('synthetic', file)
    return request<{ job_id: string }>('/scenarios/upload/jobs', { method: 'POST', body: form, signal })
  },

  planJob: (r: PlanRequest, signal?: AbortSignal) =>
    request<{ job_id: string }>('/plans/jobs', { method: 'POST', signal, body: planRequestBody(r) }),
  cancelJob: (jobId: string) => request<{ status: string }>(`/plans/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' }),

  getPlan: (planId: string) => request<PlanResponse>(`/plans/${planId}`),

  select: (planId: string) => request<PlanResponse>(`/plans/${planId}/select`, { method: 'POST' }),

  eventJob: (planId: string, event: PlanEvent) =>
    request<{ job_id: string }>(`/plans/${planId}/events/jobs`, {
      method: 'POST',
      body: JSON.stringify(event),
    }),

  manual: (planId: string, orderId: string, engineerId: string | null, position: number | 'best' = 'best') =>
    request<PlanResponse>(`/plans/${planId}/manual`, {
      method: 'POST',
      body: JSON.stringify({ order_id: orderId, engineer_id: engineerId, position }),
    }),

  candidates: (planId: string, orderId: string, signal?: AbortSignal) =>
    request<Candidate[]>(`/plans/${planId}/candidates/${encodeURIComponent(orderId)}`, { signal }),

  nearest: (planId: string, orderId: string, signal?: AbortSignal) =>
    request<NearestWindow>(`/plans/${planId}/nearest/${encodeURIComponent(orderId)}`, { signal }),

  geometry: (planId: string) => request<PlanGeometry>(`/plans/${planId}/geometry`),

  geometryLegs: (body: LegScope & { routes: Record<string, string[]> }) =>
    request<RoadLegs>('/geometry/legs', {
      method: 'POST',
      body: JSON.stringify({
        plan_id: body.planId ?? null,
        scenario_id: body.scenarioId ?? null,
        engineer_count: body.engineerCount ?? null,
        routes: body.routes,
      }),
    }),

  savePlan: (planId: string, name: string) =>
    request<SavedPlan>('/saved', { method: 'POST', body: JSON.stringify({ plan_id: planId, name }) }),

  savedPlans: (scenarioId: string) => request<SavedPlan[]>(`/saved?scenario_id=${encodeURIComponent(scenarioId)}`),

  loadSaved: (savedId: string, ontoPlanId?: string) =>
    request<PlanResponse>(`/saved/${savedId}/load${ontoPlanId ? `?onto=${encodeURIComponent(ontoPlanId)}` : ''}`, { method: 'POST' }),

  deleteSaved: (savedId: string) => request<{ deleted: string }>(`/saved/${savedId}`, { method: 'DELETE' }),

  exportUrl: (planId: string) => `${BASE}/plans/${planId}/export`,
}
