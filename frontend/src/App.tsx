import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api, ApiError, type PlanRequest } from './api'
import { hhmm } from './colors'
import { Comparison, type Matched } from './components/Comparison'
import { EngineerList } from './components/EngineerList'
import { JobPanel, type AssignResult } from './components/JobPanel'
import { JobQueue, type QueueFilter } from './components/JobQueue'
import { kpiFromPlan, kpiFromProgress, KpiStrip } from './components/KpiStrip'
import { MapView, type CandidatePreview } from './components/MapView'
import { Schedule } from './components/Schedule'
import { SimulationView } from './components/Simulation'
import { DEFAULT_PARAMS, Topbar, type PlanParamsUi, type Tab } from './components/Topbar'
import { VariantBar } from './components/VariantBar'
import { eventChanges, stopsByOrder, type EventRecord } from './derive'
import { km, plural } from './labels'
import { dayRange } from './sim'
import type { Plan, PlanEvent, PlanGeometry, PlanResponse, Scenario, ScenarioBrief, Variant } from './types'
import { loadSelectedVariant, usePlanningRequests } from './usePlanningRequests'
import { useSimulation } from './useSimulation'

type Selection = { kind: 'order'; id: string } | { kind: 'engineer'; id: string } | null

const routeSignature = (plan: Plan | null) =>
  plan ? plan.id + '|' + plan.routes.map((r) => r.engineer_id + ':' + r.stops.map((s) => s.order_id).join(',')).join(';') : ''

const wallClock = () => {
  const d = new Date()
  return d.getHours() * 60 + d.getMinutes()
}

const stripStatus = (message: string) => message.replace(/^\d{3}:\s*/, '')

export default function App() {
  const [scenarios, setScenarios] = useState<ScenarioBrief[]>([])
  const [scenarioId, setScenarioId] = useState('demo')
  const [scenarioVersion, setScenarioVersion] = useState(0)
  const [uploading, setUploading] = useState(false)
  const [params, setParams] = useState<PlanParamsUi>(DEFAULT_PARAMS)
  const [preview, setPreview] = useState<Scenario | null>(null)

  const [initial, setInitial] = useState<Matched | null>(null)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [scenario, setScenario] = useState<Scenario | null>(null)
  const [history, setHistory] = useState<EventRecord[]>([])

  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('plan')
  const [selection, setSelection] = useState<Selection>(null)
  const [queueFilter, setQueueFilter] = useState<QueueFilter>('all')

  const [variants, setVariants] = useState<Variant[]>([])
  const [variantPlans, setVariantPlans] = useState<Record<string, Plan>>({})
  const [hoverVariant, setHoverVariant] = useState<string | null>(null)
  const [selecting, setSelecting] = useState<string | null>(null)
  const [candidate, setCandidate] = useState<CandidatePreview | null>(null)
  const [roads, setRoads] = useState<PlanGeometry | null>(null)
  const [clockNow, setClockNow] = useState(wallClock())

  const planRef = useRef<Plan | null>(null)
  planRef.current = plan
  const { job, cancelPlan, requestPlan, requestEvent } = usePlanningRequests()

  const loadScenarios = useCallback(() => {
    api
      .scenarios()
      .then((list) => {
        setScenarios(list)
        setScenarioId((current) => (list.length && !list.some((s) => s.id === current) ? list[0].id : current))
      })
      .catch((e) => setError((e as Error).message))
  }, [])
  useEffect(loadScenarios, [loadScenarios])

  const upload = useCallback(async (file: File) => {
    setUploading(true)
    setError(null)
    try {
      const loaded = await api.upload(file)
      setScenarios(await api.scenarios())
      setScenarioId(loaded.id)
      setScenarioVersion((v) => v + 1)
    } catch (e) {
      setError(`Файл не загружен: ${(e as Error).message}`)
    } finally {
      setUploading(false)
    }
  }, [])

  useEffect(() => {
    cancelPlan()
    setPreview(null)
    setInitial(null)
    setPlan(null)
    setScenario(null)
    setHistory([])
    setVariants([])
    setVariantPlans({})
    setRoads(null)
    setSelection(null)
    setTab('plan')
    setParams((p) => ({ ...p, engineerCount: null }))
    let cancelled = false
    api
      .scenario(scenarioId)
      .then((s) => !cancelled && setPreview(s))
      .catch((e) => !cancelled && setError((e as Error).message))
    return () => {
      cancelled = true
    }
  }, [scenarioId, scenarioVersion, cancelPlan])

  useEffect(() => {
    const timer = window.setInterval(() => setClockNow(wallClock()), 30000)
    return () => window.clearInterval(timer)
  }, [])

  const accept = useCallback((response: PlanResponse) => {
    setInitial({
      optimized: response.optimized,
      baseline: response.baseline,
      control: response.control,
      scenario: response.scenario,
      manualEdits: 0,
    })
    setPlan(response.optimized)
    setScenario(response.scenario)
    setHistory([])
    setVariants(response.variants ?? [])
    setVariantPlans({ [response.optimized.id]: response.optimized })
  }, [])

  const run = useCallback(async () => {
    const request: PlanRequest = {
      scenarioId,
      objective: params.objective,
      timeLimit: params.timeLimit,
      lunch: params.lunch,
      engineerCount: params.engineerCount,
      allowReschedule: params.allowReschedule,
    }
    setError(null)
    setSelection(null)
    setCandidate(null)
    setVariants([])
    setHoverVariant(null)
    setTab('plan')
    try {
      const response = await requestPlan(request)
      if (response) accept(response)
    } catch (e) {
      if ((e as Error).name === 'AbortError') return
      setError(`План не построен: ${stripStatus((e as Error).message)}`)
    }
  }, [scenarioId, params, requestPlan, accept])

  const fetchVariant = useCallback(
    async (planId: string): Promise<PlanResponse | null> => {
      try {
        const response = await api.getPlan(planId)
        setVariantPlans((cache) => ({ ...cache, [planId]: response.optimized }))
        return response
      } catch {
        return null
      }
    },
    [],
  )

  useEffect(() => {
    if (hoverVariant && !variantPlans[hoverVariant]) void fetchVariant(hoverVariant)
  }, [hoverVariant, variantPlans, fetchVariant])

  const selectVariant = useCallback(
    async (planId: string) => {
      if (planId === plan?.id) return
      setSelecting(planId)
      try {
        const response = await loadSelectedVariant(planId)
        setInitial({
          optimized: response.optimized,
          baseline: response.baseline,
          control: response.control,
          scenario: response.scenario,
          manualEdits: 0,
        })
        setPlan(response.optimized)
        setScenario(response.scenario)
        setHistory([])
        setVariantPlans((cache) => ({ ...cache, [planId]: response.optimized }))
        setSelection(null)
      } catch (e) {
        setError(`Вариант не выбран: ${(e as Error).message}`)
      } finally {
        setSelecting(null)
        setHoverVariant(null)
      }
    },
    [plan?.id],
  )

  const assign = useCallback(
    async (orderId: string, engineerId: string | null, position: number | 'best'): Promise<AssignResult> => {
      const current = planRef.current
      if (!current || !scenario) return { ok: false, text: 'Плана нет.' }
      const name = (id: string) => scenario.engineers.find((e) => e.id === id)?.name ?? id
      const before = current.metrics
      try {
        const response = await api.manual(current.id, orderId, engineerId, position)
        const after = response.optimized
        setPlan(after)
        setScenario(response.scenario)
        setVariantPlans((cache) => ({ ...cache, [after.id]: after }))
        setVariants((list) => list.map((v) => (v.plan_id === after.id ? { ...v, metrics: after.metrics } : v)))
        if (!history.length) {
          setInitial((m) => ({
            optimized: after,
            baseline: response.baseline,
            control: response.control,
            scenario: response.scenario,
            manualEdits: (m?.manualEdits ?? 0) + 1,
          }))
        }
        const ref = stopsByOrder(after)[orderId]
        const where = engineerId
          ? ref
            ? `${orderId} у ${name(ref.engineerId)}: визит ${ref.position}, начало ${ref.stop.start}.`
            : `${orderId} передана ${name(engineerId)}.`
          : `${orderId} снята с маршрута.`
        return {
          ok: true,
          text: `${where} Пробег ${km(before.distance_total_km)} → ${km(after.metrics.distance_total_km)} км.`,
        }
      } catch (e) {
        const message = (e as Error).message
        return { ok: false, text: e instanceof ApiError && e.status === 422 ? message : `Ошибка сервиса: ${message}` }
      }
    },
    [scenario, history.length],
  )

  const applyEvent = useCallback(
    async (event: PlanEvent) => {
      const before = planRef.current
      if (!before) throw new ApiError('Плана нет.', 0)
      const started = Date.now()
      try {
        const response = await requestEvent(before, event)
        const changes = eventChanges(before, response.plan, response.diff?.routes_changed ?? [])
        setHistory((items) => [...items, { event, diff: response.diff, before, after: response.plan, changes }])
        setPlan(response.plan)
        setScenario(response.scenario)
        let added: string | undefined
        if (event.type === 'urgent_order' || event.type === 'new_order') {
          const ref = stopsByOrder(response.plan)[event.order.id]
          const name = response.scenario.engineers.find((e) => e.id === ref?.engineerId)?.name
          added = ref ? `${event.order.id} → ${name}, начало ${ref.stop.start}` : `${event.order.id} не размещена`
        }
        return {
          moved: changes.changed.length,
          frozen: changes.frozen.length,
          planId: response.plan.id,
          seconds: Math.round((Date.now() - started) / 1000),
          added,
        }
      } catch (e) {
        let message = stripStatus((e as Error).message)
        if (/Input should be|Field required|Extra inputs/.test(message)) message = 'сервис не принимает такое событие'
        setError(`Событие не применено: ${message}`)
        throw new ApiError(message, 0)
      }
    },
    [requestEvent],
  )

  const range = useMemo<[number, number]>(
    () => (initial ? dayRange(initial.scenario, initial.optimized.routes) : [8 * 60, 22 * 60]),
    [initial],
  )
  const sim = useSimulation({ range, run: applyEvent })
  const simTouched = history.length > 0 || sim.clock > range[0] || sim.playing

  useEffect(() => {
    sim.reset(initial?.scenario.events ?? [], range[0])
  }, [initial, range, sim.reset])

  const resetToInitial = useCallback(() => {
    if (!initial) return
    setPlan(initial.optimized)
    setScenario(initial.scenario)
    setHistory([])
    setSelection(null)
    sim.reset(initial.scenario.events ?? [], range[0])
  }, [initial, range, sim])

  useEffect(() => {
    if (tab !== 'sim' && sim.playing) sim.toggle()
  }, [tab, sim.playing, sim.toggle])

  const signature = routeSignature(plan)
  const planId = plan?.id
  useEffect(() => {
    if (!planId) return
    let cancelled = false
    api
      .geometry(planId)
      .then((result) => !cancelled && setRoads(result))
      .catch(() => !cancelled && setRoads(null))
    return () => {
      cancelled = true
    }
  }, [signature, planId])

  const last = history[history.length - 1] ?? null
  const changed = useMemo(
    () => new Set(last ? [...last.changes.changed.map((c) => c.orderId), ...last.changes.added.map((a) => a.stop.order_id)] : []),
    [last],
  )
  const unavailable = useMemo(
    () => new Set(history.filter((h) => h.event.type === 'engineer_unavailable').map((h) => (h.event as { engineer_id: string }).engineer_id)),
    [history],
  )

  const liveRoutes = job?.streaming && job.last?.routes ? job.last.routes : null
  const hovered = hoverVariant && hoverVariant !== plan?.id ? variantPlans[hoverVariant] ?? null : null
  const displayPlan = hovered ?? plan
  const mapScenario = scenario ?? preview
  const selectedOrder = selection?.kind === 'order' ? selection.id : null
  const selectedEngineer = selection?.kind === 'engineer' ? selection.id : null
  const busy = job !== null || sim.busy

  const kpiScenario = scenario ?? preview
  const kpiView =
    kpiScenario && job?.last
      ? kpiFromProgress(job.last, kpiScenario)
      : displayPlan && scenario
        ? kpiFromPlan(displayPlan, scenario)
        : null

  const selectOrder = useCallback((id: string | null) => setSelection(id ? { kind: 'order', id } : null), [])
  const selectEngineer = useCallback((id: string | null) => setSelection(id ? { kind: 'engineer', id } : null), [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !(e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement)) setSelection(null)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (!selectedOrder) setCandidate(null)
  }, [selectedOrder])

  const now = simTouched ? sim.clock : clockNow
  const nowLabel = simTouched ? `симуляция ${hhmm(Math.floor(sim.clock))}` : `сейчас ${hhmm(clockNow)}`
  const showBar = tab === 'plan' ? job !== null || variants.length > 1 : tab === 'sim' && job !== null

  return (
    <div className="app">
      <Topbar
        scenarios={scenarios}
        scenarioId={scenarioId}
        onScenario={setScenarioId}
        onUpload={upload}
        uploading={uploading}
        params={params}
        onParams={setParams}
        plan={plan}
        busy={busy}
        onPlan={run}
        tab={tab}
        onTab={(t) => {
          setTab(t)
          setCandidate(null)
        }}
        lockedTabs={!plan}
      />

      {kpiView ? (
        <KpiStrip
          view={kpiView}
          live={Boolean(job?.last)}
          before={last ? last.diff?.metrics_before ?? last.before.metrics : null}
          baseline={!history.length && initial ? initial.baseline.metrics : null}
          onUnplaced={() => {
            setTab('plan')
            setSelection(null)
            setQueueFilter('unplaced')
          }}
          onCompare={() => setTab('compare')}
        />
      ) : (
        <section className="kpis empty" aria-label="Сводка участка">
          {preview ? (
            <>
              <div className="kpi">
                <div className="kpi-line">
                  <b className="kpi-value">{preview.orders.length}</b>
                  <span className="kpi-unit">заявок</span>
                </div>
              </div>
              <div className="kpi">
                <div className="kpi-line">
                  <b className="kpi-value">{params.engineerCount ?? preview.engineers.length}</b>
                  <span className="kpi-unit">инженеров на смене</span>
                </div>
              </div>
              <div className="kpi">
                <div className="kpi-line">
                  <b className="kpi-value">{preview.events.length}</b>
                  <span className="kpi-unit">{plural(preview.events.length, 'событие', 'события', 'событий')} на день</span>
                </div>
              </div>
              <div className="kpi">
                <div className="kpi-line">
                  <span className="kpi-unit">{job ? 'идёт расчёт' : 'план не построен'}</span>
                </div>
              </div>
            </>
          ) : (
            <div className="kpi">
              <span className="spinner" />
            </div>
          )}
        </section>
      )}

      {error && (
        <div className="toast error" role="alert">
          <span>{error}</span>
          {!scenarios.length && (
            <button type="button" className="ghost small" onClick={loadScenarios}>
              Повторить
            </button>
          )}
          <button type="button" className="icon" onClick={() => setError(null)} aria-label="Скрыть">
            ×
          </button>
        </div>
      )}

      <main className={`main tab-${tab} ${showBar ? 'with-bar' : ''}`}>
        {tab === 'plan' && mapScenario && (
          <div className={`plan-grid ${job ? 'is-busy' : ''}`}>
            <EngineerList
              scenario={mapScenario}
              plan={displayPlan}
              liveRoutes={liveRoutes}
              selected={selectedEngineer}
              selectedOrder={selectedOrder}
              onSelect={selectEngineer}
              onSelectOrder={selectOrder}
              unavailable={unavailable}
            />
            <div className="map-pane">
              <MapView
                scenario={mapScenario}
                plan={displayPlan}
                routesOverride={liveRoutes ?? (hovered ? Object.fromEntries(hovered.routes.map((r) => [r.engineer_id, r.stops.map((s) => s.order_id)])) : null)}
                geometry={roads && roads.available ? roads : null}
                selectedOrder={selectedOrder}
                selectedEngineer={selectedEngineer}
                changed={changed}
                preview={candidate}
                onSelectOrder={selectOrder}
                onSelectEngineer={selectEngineer}
              />
            </div>
            {plan && scenario && selectedOrder ? (
              <JobPanel
                plan={plan}
                scenario={scenario}
                orderId={selectedOrder}
                change={last?.changes.changed.find((c) => c.orderId === selectedOrder) ?? null}
                busy={busy}
                onClose={() => setSelection(null)}
                onSelectEngineer={selectEngineer}
                onPreview={setCandidate}
                onAssign={assign}
              />
            ) : (
              <JobQueue
                scenario={mapScenario}
                plan={liveRoutes ? null : displayPlan}
                filter={queueFilter}
                onFilter={setQueueFilter}
                selectedOrder={selectedOrder}
                onSelectOrder={selectOrder}
                changed={changed}
              />
            )}
          </div>
        )}
        {tab === 'plan' && !mapScenario && (
          <div className="loading-screen">
            <span className="spinner lg" />
          </div>
        )}

        {tab === 'schedule' && plan && scenario && (
          <Schedule
            scenario={scenario}
            plan={plan}
            now={now}
            nowLabel={nowLabel}
            selectedOrder={selectedOrder}
            selectedEngineer={selectedEngineer}
            changed={changed}
            unavailable={unavailable}
            busy={busy}
            onSelectOrder={selectOrder}
            onSelectEngineer={selectEngineer}
            onAssign={assign}
          />
        )}

        {tab === 'compare' && initial && (
          <div className="compare-page">
            <Comparison matched={initial} eventState={history.length > 0} />
          </div>
        )}

        {tab === 'sim' && plan && scenario && (
          <SimulationView
            sim={sim}
            plan={plan}
            scenario={scenario}
            geometry={roads && roads.available ? roads : null}
            changed={changed}
            selectedOrder={selectedOrder}
            selectedEngineer={selectedEngineer}
            onSelectOrder={selectOrder}
            onSelectEngineer={selectEngineer}
            onReset={resetToInitial}
          />
        )}

        {showBar && (
          <VariantBar
            job={job}
            variants={variants}
            currentPlanId={plan?.id ?? null}
            hovered={hoverVariant}
            onHover={setHoverVariant}
            onSelect={selectVariant}
            selecting={selecting}
          />
        )}
      </main>
    </div>
  )
}
