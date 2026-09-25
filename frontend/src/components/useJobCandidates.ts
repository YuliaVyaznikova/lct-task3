import { useEffect, useMemo, useState } from 'react'

import { api, isMissing } from '../api'
import { estimateCandidates } from '../candidates'
import type { Candidate, Plan, Scenario } from '../types'
import type { CandidatePreview } from './MapView'

export type AssignResult = { ok: boolean; text: string }

type CandidateRows =
  | { state: 'loading' }
  | { state: 'ready'; rows: (Candidate & { estimated?: true })[] }
  | { state: 'error'; text: string }

interface Options {
  plan: Plan
  scenario: Scenario
  orderId: string
  enabled: boolean
  locked: boolean
  assignedEngineerId: string | undefined
  onPreview: (preview: CandidatePreview | null) => void
  onAssign: (orderId: string, engineerId: string | null, position: number | 'best') => Promise<AssignResult>
}

const routeSequenceKey = (plan: Plan) =>
  plan.id + '|' + plan.routes.map((route) => route.engineer_id + ':' + route.stops.map((stop) => stop.order_id).join(',')).join(';')

export function useJobCandidates({ plan, scenario, orderId, enabled, locked, assignedEngineerId, onPreview, onAssign }: Options) {
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
    if (!enabled || locked) return
    const controller = new AbortController()
    setRows({ state: 'loading' })
    api
      .candidates(plan.id, orderId, controller.signal)
      .then((list) => setRows({ state: 'ready', rows: list.filter((row) => row.engineer_id !== assignedEngineerId) }))
      .catch((error) => {
        if ((error as Error).name === 'AbortError') return
        if (isMissing(error)) setRows({ state: 'ready', rows: estimateCandidates(plan, scenario, orderId) })
        else setRows({ state: 'error', text: (error as Error).message })
      })
    return () => controller.abort()
  }, [enabled, locked, plan, scenario, orderId, assignedEngineerId, key])

  const list = rows.state === 'ready' ? rows.rows : []
  const active = list.find((row) => row.engineer_id === (hover ?? picked)) ?? null

  useEffect(() => {
    if (active && active.feasible && Object.keys(active.preview_routes ?? {}).length) {
      onPreview({ orderId, engineerId: active.engineer_id, routes: active.preview_routes })
    } else onPreview(null)
  }, [active, onPreview, orderId, key])
  useEffect(() => () => onPreview(null), [onPreview])

  const feasible = useMemo(() => list.filter((row) => row.feasible), [list])
  const blocked = useMemo(() => list.filter((row) => !row.feasible), [list])
  const estimated = list.some((row) => row.estimated)

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
    } else if (engineerId) setRowError({ id: engineerId, text: outcome.text })
    else setResult(outcome)
  }

  return { rows, setHover, picked, setPicked, pending, result, rowError, list, active, feasible, blocked, estimated, assign }
}
