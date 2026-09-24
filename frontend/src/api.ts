import type {
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    let message = `Ошибка ${response.status}`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail)) message = body.detail.map((d: any) => d.msg).join('; ')
    } catch {
      /* тело не разобралось — показываем код */
    }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export const api = {
  scenarios: () => request<ScenarioBrief[]>('/scenarios'),

  scenario: (id: string) => request<Scenario>(`/scenarios/${id}`),

  workTypes: () => request<{ work_types: WorkType[] }>('/reference').then((r) => r.work_types),

  upload: async (file: File): Promise<Scenario> => {
    const form = new FormData()
    form.append('synthetic', file)
    const response = await fetch(`${BASE}/scenarios/upload`, { method: 'POST', body: form })
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      throw new Error(body?.detail ?? `Не удалось загрузить файл (${response.status})`)
    }
    return response.json()
  },

  plan: (
    scenarioId: string,
    objective: Objective,
    timeLimit: number,
    lunch: boolean,
    engineerCount: number | null,
    allowReschedule: boolean,
  ) =>
    request<PlanResponse>('/plans', {
      method: 'POST',
      body: JSON.stringify({
        scenario_id: scenarioId,
        params: {
          objective,
          time_limit_s: timeLimit,
          lunch,
          allow_reschedule: allowReschedule,
        },
        engineer_count: engineerCount,
      }),
    }),

  event: (planId: string, event: PlanEvent) =>
    request<ReplanResponse>(`/plans/${planId}/events`, {
      method: 'POST',
      body: JSON.stringify(event),
    }),

  manual: (planId: string, orderId: string, engineerId: string | null) =>
    request<PlanResponse>(`/plans/${planId}/manual`, {
      method: 'POST',
      body: JSON.stringify({ order_id: orderId, engineer_id: engineerId, position: 'best' }),
    }),

  geometry: (planId: string) => request<PlanGeometry>(`/plans/${planId}/geometry`),

  explain: (planId: string, orderId: string) =>
    request<OrderExplanation & { assigned: boolean; reason?: string; reason_code?: string }>(
      `/plans/${planId}/explain/${orderId}`,
    ),

  exportUrl: (planId: string) => `${BASE}/plans/${planId}/export`,
}
