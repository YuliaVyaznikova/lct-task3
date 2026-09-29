import { useEffect, useState } from 'react'

import { api } from './api'
import type { Metrics } from './types'

export function useScenarioBaseline(scenarioId: string, engineerCount: number | null, version: number): Metrics | null {
  const [baseline, setBaseline] = useState<Metrics | null>(null)
  useEffect(() => {
    setBaseline(null)
    if (!scenarioId) {
      return
    }
    const controller = new AbortController()
    api
      .scenarioBaseline(scenarioId, engineerCount, controller.signal)
      .then(setBaseline)
      .catch(() => setBaseline(null))
    return () => controller.abort()
  }, [scenarioId, engineerCount, version])
  return baseline
}
