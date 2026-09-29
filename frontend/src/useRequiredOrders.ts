import { useCallback, useEffect, useState } from 'react'

const storageKey = (scenarioId: string) => `required-orders:${scenarioId}`

function readRequired(scenarioId: string): Set<string> {
  try {
    const stored = JSON.parse(localStorage.getItem(storageKey(scenarioId)) ?? '[]')
    return new Set(Array.isArray(stored) ? stored.filter((id): id is string => typeof id === 'string') : [])
  } catch {
    return new Set()
  }
}

function writeRequired(scenarioId: string, required: Set<string>) {
  try {
    localStorage.setItem(storageKey(scenarioId), JSON.stringify([...required]))
  } catch {
    return
  }
}

export function useRequiredOrders(scenarioId: string) {
  const [state, setState] = useState(() => ({ scenarioId, required: readRequired(scenarioId) }))
  const required = state.scenarioId === scenarioId ? state.required : readRequired(scenarioId)

  useEffect(() => {
    if (state.scenarioId !== scenarioId) {
      setState({ scenarioId, required: readRequired(scenarioId) })
    }
  }, [scenarioId, state.scenarioId])

  const toggle = useCallback(
    (orderId: string) =>
      setState((current) => {
        const next = new Set(current.required)
        if (next.has(orderId)) {
          next.delete(orderId)
        } else {
          next.add(orderId)
        }
        writeRequired(current.scenarioId, next)
        return { ...current, required: next }
      }),
    [],
  )

  return [required, toggle] as const
}
