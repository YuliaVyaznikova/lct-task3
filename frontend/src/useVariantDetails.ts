import { useCallback, useEffect, useState, type Dispatch, type SetStateAction } from 'react'

import { api } from './api'
import type { Plan } from './types'

const keepMetricsOnly = () => undefined

export function useVariantDetails(variantPlans: Record<string, Plan>, setVariantPlans: Dispatch<SetStateAction<Record<string, Plan>>>) {
  const [otherId, setOtherId] = useState<string | null>(null)

  useEffect(() => {
    if (!otherId || variantPlans[otherId]) {
      return
    }
    api
      .getPlan(otherId)
      .then((response) => setVariantPlans((cache) => ({ ...cache, [otherId]: response.optimized })))
      .catch(keepMetricsOnly)
  }, [otherId, variantPlans, setVariantPlans])

  const close = useCallback(() => setOtherId(null), [])
  const toggle = useCallback((planId: string) => setOtherId((current) => (current === planId ? null : planId)), [])
  const other = otherId ? variantPlans[otherId] ?? null : null

  return { otherId, other, open: setOtherId, close, toggle }
}
