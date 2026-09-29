import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api, type LegScope } from './api'
import type { LatLon, RoadLegLookup } from './geo'

const THROTTLE_MS = 700
const RETRY_AFTER_MS = 30000
const MAX_CACHED_LEGS = 5000

const scopeKey = (scope: LegScope) => `${scope.planId ?? ''}|${scope.scenarioId ?? ''}|${scope.engineerCount ?? ''}`

const legKey = (scope: string, engineerId: string, orderIds: string[], index: number) =>
  `${scope}|${index === 0 ? `@${engineerId}` : orderIds[index - 1]}>${orderIds[index]}`

export function useRoadLegs(scope: LegScope | null, routes: Record<string, string[]> | null): RoadLegLookup | null {
  const cache = useRef(new Map<string, LatLon[]>())
  const missed = useRef(new Map<string, number>())
  const inFlight = useRef(false)
  const timer = useRef<number | null>(null)
  const latest = useRef({ scope, routes })
  const [version, setVersion] = useState(0)

  latest.current = { scope, routes }
  const key = scope ? scopeKey(scope) : ''

  const sync = useCallback(async () => {
    if (inFlight.current) {
      return
    }
    const { scope: currentScope, routes: currentRoutes } = latest.current
    if (!currentScope || !currentRoutes) {
      return
    }
    const currentKey = scopeKey(currentScope)
    const now = Date.now()
    const wanted: Record<string, string[]> = {}
    for (const [engineerId, orderIds] of Object.entries(currentRoutes)) {
      const absent = orderIds.some((_, index) => {
        const leg = legKey(currentKey, engineerId, orderIds, index)
        return !cache.current.has(leg) && now - (missed.current.get(leg) ?? 0) > RETRY_AFTER_MS
      })
      if (absent) {
        wanted[engineerId] = orderIds
      }
    }
    if (!Object.keys(wanted).length) {
      return
    }
    inFlight.current = true
    try {
      const response = await api.geometryLegs({ ...currentScope, routes: wanted })
      if (cache.current.size > MAX_CACHED_LEGS) {
        cache.current.clear()
      }
      for (const [engineerId, legs] of Object.entries(response.legs)) {
        legs.forEach((line, index) => {
          const leg = legKey(currentKey, engineerId, wanted[engineerId], index)
          if (line && line.length >= 2) {
            cache.current.set(leg, line)
          } else {
            missed.current.set(leg, Date.now())
          }
        })
      }
      setVersion((v) => v + 1)
    } catch {
      for (const [engineerId, orderIds] of Object.entries(wanted)) {
        orderIds.forEach((_, index) => missed.current.set(legKey(currentKey, engineerId, orderIds, index), Date.now()))
      }
    } finally {
      inFlight.current = false
    }
    const after = latest.current
    if (after.routes !== currentRoutes || after.scope !== currentScope) {
      void sync()
    }
  }, [])

  useEffect(() => {
    cache.current.clear()
    missed.current.clear()
  }, [key])

  useEffect(() => {
    if (!key || !routes || timer.current !== null) {
      return
    }
    timer.current = window.setTimeout(
      () => {
        timer.current = null
        void sync()
      },
      cache.current.size || missed.current.size ? THROTTLE_MS : 0,
    )
  }, [routes, key, sync])

  useEffect(
    () => () => {
      if (timer.current !== null) {
        window.clearTimeout(timer.current)
      }
      timer.current = null
    },
    [],
  )

  return useMemo<RoadLegLookup | null>(
    () =>
      key
        ? (engineerId, orderIds, index) => {
            const leg = legKey(key, engineerId, orderIds, index)
            return cache.current.get(leg) ?? (missed.current.has(leg) ? null : undefined)
          }
        : null,
    [key, version],
  )
}
