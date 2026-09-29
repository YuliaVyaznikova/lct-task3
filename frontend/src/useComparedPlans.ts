import { useCallback, useEffect, useState } from 'react'

import { api } from './api'
import { matchedFrom } from './derive'
import type { Matched, Plan, PlanResponse, Tab } from './types'

interface ComparedPlansInput {
  tab: Tab
  targetId: string | null
  plan: Plan | null
  onError: (message: string) => void
}

export function useComparedPlans({ tab, targetId, plan, onError }: ComparedPlansInput) {
  const [byId, setById] = useState<Record<string, Matched>>({})

  useEffect(() => {
    if (tab !== 'compare' || !targetId || byId[targetId]) {
      return
    }
    api
      .getPlan(targetId)
      .then((response: PlanResponse) => setById((cache) => ({ ...cache, [targetId]: matchedFrom(response) })))
      .catch((e) => onError(`Сравнение не построено: ${(e as Error).message}`))
  }, [tab, targetId, byId, onError])

  const shown = (targetId && byId[targetId]) || (plan && byId[plan.id]) || null
  const clear = useCallback(() => setById({}), [])

  return { shown, clear }
}
