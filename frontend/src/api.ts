import { humanizeCodes } from './labels'
import type {
  Candidate,
  JobProgress,
  NearestWindow,
  Objective,
  OrderExplanation,
  PlanEvent,
  PlanGeometry,
  PlanResponse,
  ReplanResponse,
  Scenario,
  ScenarioBrief,
  WorkType,
} from './types'

const BASE = '/api'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
  }
}

export const isMissing = (e: unknown) =>
  e instanceof ApiError && (e.status === 404 || e.status === 405) && /Not Found|Method Not Allowed|Нет такого метода/i.test(e.message)

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(BASE + path, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError('Сервис планирования не отвечает.', 0)
  }
  if (!response.ok) {
    let message = `Ошибка сервиса (${response.status})`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail)) message = body.detail.map((d: any) => d.msg).join('; ')
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
}

const planRequestBody = (r: PlanRequest) =>
  JSON.stringify({
    scenario_id: r.scenarioId,
    params: {
      objective: r.objective,
      time_limit_s: r.timeLimit,
      lunch: r.lunch,
      allow_reschedule: r.allowReschedule,
    },
    engineer_count: r.engineerCount,
  })

export interface JobHandlers<T> {
  onProgress: (progress: JobProgress) => void
  signal?: AbortSignal
  parse?: (data: unknown) => T
}

export function streamJob<T>(jobId: string, handlers: JobHandlers<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const source = new EventSource(`${BASE}/plans/jobs/${encodeURIComponent(jobId)}/events`)
    let settled = false
    const settleAndClose = (fn: () => void) => {
      if (settled) return
      settled = true
      source.close()
      fn()
    }
    handlers.signal?.addEventListener('abort', () =>
      settleAndClose(() => reject(new DOMException('aborted', 'AbortError'))),
    )
    source.addEventListener('progress', (e) => {
      try {
        handlers.onProgress(JSON.parse((e as MessageEvent).data))
      } catch {}
    })
    source.addEventListener('done', (e) => {
      settleAndClose(() => {
        try {
          const data = JSON.parse((e as MessageEvent).data)
          resolve(handlers.parse ? handlers.parse(data) : (data as T))
        } catch (err) {
          reject(new ApiError('Сервис прислал неполный итог расчёта.', 0))
        }
      })
    })
    source.addEventListener('error', (e) => {
      const data = (e as MessageEvent).data
      if (typeof data === 'string' && data) {
        let message = data
        try {
          const body = JSON.parse(data)
          message = body.detail ?? body.message ?? body.error ?? data
        } catch {}
        settleAndClose(() => reject(new ApiError(humanizeCodes(String(message)), 422)))
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

  workTypes: () => request<{ work_types?: WorkType[] }>('/reference').then((r) => r.work_types ?? []),

  upload: async (file: File) => {
    const form = new FormData()
    form.append('synthetic', file)
    let response: Response
    try {
      response = await fetch(`${BASE}/scenarios/upload`, { method: 'POST', body: form })
    } catch {
      throw new ApiError('Сервис планирования не отвечает.', 0)
    }
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      const detail = typeof body?.detail === 'string' ? body.detail : `Ошибка сервиса (${response.status})`
      throw new ApiError(humanizeCodes(detail), response.status)
    }
    return (await response.json()) as Scenario
  },

  plan: (r: PlanRequest, signal?: AbortSignal) =>
    request<PlanResponse>('/plans', { method: 'POST', signal, body: planRequestBody(r) }),

  planJob: (r: PlanRequest, signal?: AbortSignal) =>
    request<{ job_id: string }>('/plans/jobs', { method: 'POST', signal, body: planRequestBody(r) }),

  getPlan: (planId: string) => request<PlanResponse>(`/plans/${planId}`),

  select: (planId: string) =>
    request<PlanResponse | Record<string, unknown>>(`/plans/${planId}/select`, { method: 'POST' }),

  event: (planId: string, event: PlanEvent) =>
    request<ReplanResponse>(`/plans/${planId}/events`, {
      method: 'POST',
      body: JSON.stringify(event),
    }),

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

  candidates: async (planId: string, orderId: string, signal?: AbortSignal) => {
    const body = await request<Candidate[] | { candidates: Candidate[] }>(
      `/plans/${planId}/candidates/${encodeURIComponent(orderId)}`,
      { signal },
    )
    return Array.isArray(body) ? body : body.candidates
  },

  nearest: (planId: string, orderId: string, signal?: AbortSignal) =>
    request<NearestWindow>(`/plans/${planId}/nearest/${encodeURIComponent(orderId)}`, { signal }),

  geometry: (planId: string) => request<PlanGeometry>(`/plans/${planId}/geometry`),

  explain: (planId: string, orderId: string) =>
    request<OrderExplanation & { assigned: boolean; reason?: string; reason_code?: string }>(
      `/plans/${planId}/explain/${orderId}`,
    ),

  exportUrl: (planId: string) => `${BASE}/plans/${planId}/export`,
}
