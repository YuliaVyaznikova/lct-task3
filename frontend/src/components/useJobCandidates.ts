import { useEffect, useMemo, useState } from 'react'

import { api } from '../api'
import { routeSequenceKey } from '../derive'
import type { Candidate, Plan } from '../types'
import type { CandidatePreview } from './MapView'

export type AssignResult = { ok: boolean; text: string }

export function canTake(rows: Candidate[], engineerId: string): boolean {
  return rows.find((r) => r.engineer_id === engineerId)?.feasible ?? false
}

export function takeReason(rows: Candidate[], engineerId: string): string | null {
  return rows.find((r) => r.engineer_id === engineerId)?.reason ?? null
}

type CandidateRows = { state: 'loading' } | Loaded

type Loaded = { state: 'ready'; rows: Candidate[] } | { state: 'error'; text: string }

export async function fetchCandidates(planId: string, orderId: string, signal?: AbortSignal): Promise<Loaded> {
  try {
    return { state: 'ready', rows: await api.candidates(planId, orderId, signal) }
  } catch (error) {
    return { state: 'error', text: (error as Error).message }
  }
}

interface Options {
  plan: Plan
  orderId: string
  enabled: boolean
  locked: boolean
  assignedEngineerId: string | undefined
  onPreview: (preview: CandidatePreview | null) => void
  onAssign: (orderId: string, engineerId: string | null, position: number | 'best') => Promise<AssignResult>
}

export function useJobCandidates({ plan, orderId, enabled, locked, assignedEngineerId, onPreview, onAssign }: Options) {
  const [rows, setRows] = useState<CandidateRows>({ state: 'loading' })
  const [hover, setHover] = useState<string | null>(null)
  const [picked, setPicked] = useState<string | null>(null)
  const [pending, setPending] = useState<string | null>(null)
  const [result, setResult] = useState<AssignResult | null>(null)
  const [rowError, setRowError] = useState<{ id: string; text: string } | null>(null)
  const key = routeSequenceKey(plan)

  useEffect(() => {
    setHover(null)
    setPicked(null)
    setRowError(null)
  }, [orderId, key])
  useEffect(() => setResult(null), [orderId])

  useEffect(() => {
    if (!enabled || locked) {
      return
    }
    const controller = new AbortController()
    setRows({ state: 'loading' })
    void fetchCandidates(plan.id, orderId, controller.signal).then((loaded) => {
      if (controller.signal.aborted) {
        return
      }
      setRows(loaded.state === 'ready' ? { state: 'ready', rows: loaded.rows.filter((row) => row.engineer_id !== assignedEngineerId) } : loaded)
    })
    return () => controller.abort()
  }, [enabled, locked, plan, orderId, assignedEngineerId, key])

  const list = rows.state === 'ready' ? rows.rows : []
  const active = list.find((row) => row.engineer_id === (hover ?? picked)) ?? null

  useEffect(() => {
    if (active && active.feasible && Object.keys(active.preview_routes).length) {
      onPreview({ orderId, engineerId: active.engineer_id, routes: active.preview_routes })
    } else {
      onPreview(null)
    }
  }, [active, onPreview, orderId, key])
  useEffect(() => () => onPreview(null), [onPreview])

  const feasible = useMemo(() => list.filter((row) => row.feasible), [list])
  const blocked = useMemo(() => list.filter((row) => !row.feasible), [list])

  async function assign(row: Candidate | null) {
    const engineerId = row ? row.engineer_id : null
    setPending(engineerId ?? '__none__')
    setRowError(null)
    const outcome = await onAssign(orderId, engineerId, row && row.position !== null ? row.position : 'best')
    setPending(null)
    if (outcome.ok) {
      setResult(outcome)
      setPicked(null)
      setHover(null)
    } else if (engineerId) {
      setRowError({ id: engineerId, text: outcome.text })
    } else {
      setResult(outcome)
    }
  }

  return { rows, setHover, picked, setPicked, pending, result, rowError, list, active, feasible, blocked, assign }
}
