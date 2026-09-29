import { useEffect, useMemo, useState } from 'react'

import { api } from './api'
import type { Plan } from './types'

const keepMetricsOnly = () => undefined

export function useVariantPreviews(currentPlanId: string | null) {
  const [hoverVariant, setHoverVariant] = useState<string | null>(null)
  const [variantPlans, setVariantPlans] = useState<Record<string, Plan>>({})

  useEffect(() => {
    if (!hoverVariant || variantPlans[hoverVariant]) {
      return
    }
    api
      .getPlan(hoverVariant)
      .then((response) => setVariantPlans((cache) => ({ ...cache, [hoverVariant]: response.optimized })))
      .catch(keepMetricsOnly)
  }, [hoverVariant, variantPlans])

  const hovered = hoverVariant && hoverVariant !== currentPlanId ? variantPlans[hoverVariant] ?? null : null
  const hoveredRoutes = useMemo(
    () => (hovered ? Object.fromEntries(hovered.routes.map((route) => [route.engineer_id, route.stops.map((stop) => stop.order_id)])) : null),
    [hovered],
  )

  return { hoverVariant, setHoverVariant, variantPlans, setVariantPlans, hovered, hoveredRoutes }
}
