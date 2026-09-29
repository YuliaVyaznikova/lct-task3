import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from './api'
import { routeSequenceKey } from './derive'
import { geometryFor } from './geo'
import type { Plan, PlanGeometry } from './types'

const NO_ROADS: PlanGeometry = { available: false, source: '', profile: '', routes: {}, legs: {}, errors: [] }

export function useRoads(geometryPlan: Plan | null, variantPlans: Record<string, Plan>) {
  const [roads, setRoads] = useState<Record<string, PlanGeometry>>({})
  const loading = useRef(new Set<string>())

  useEffect(() => {
    const wanted = [geometryPlan, ...Object.values(variantPlans)].filter((plan): plan is Plan => plan !== null)
    for (const target of wanted) {
      const key = routeSequenceKey(target)
      if (key in roads || loading.current.has(key)) {
        continue
      }
      loading.current.add(key)
      api
        .geometry(target.id)
        .catch(() => NO_ROADS)
        .then((result) => setRoads((known) => ({ ...known, [key]: result })))
        .finally(() => loading.current.delete(key))
    }
  }, [geometryPlan, variantPlans, roads])

  const roadsFor = (plan: Plan | null) => geometryFor(roads, plan)
  const resetRoads = useCallback(() => setRoads({}), [])

  return { roadsFor, resetRoads }
}
