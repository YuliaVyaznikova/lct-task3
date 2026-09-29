import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { colorResolver, EngineerColorContext } from './colors'
import { api, ApiError, type LegScope, type PlanRequest } from './api'
import { Comparison } from './components/Comparison'
import { EngineerList } from './components/EngineerList'
import { JobPanel, type AssignResult } from './components/JobPanel'
import { JobQueue } from './components/JobQueue'
import { KpiStrip } from './components/KpiStrip'
import { MapView } from './components/MapView'
import { PlanControl, DEFAULT_PARAMS, type PlanParamsUi } from './components/PlanControl'
import { PlanStorage } from './components/PlanStorage'
import { EventReviewSchedule } from './components/ReviewSchedule'
import { Schedule } from './components/Schedule'
import { EventsPanel, SimulationBar, StatusLegend, useSimulationView } from './components/Simulation'
import { SimToggle } from './components/SimToggle'
import { SwitchConfirm } from './components/SwitchConfirm'
import { Topbar } from './components/Topbar'
import { VariantBar } from './components/VariantBar'
import { VariantSchedule, type VariantOption } from './components/VariantSchedule'
import { Workspace } from './components/Workspace'
import { addedLabel, changedOrders, differingOrders, emptyKpi, matchedFrom, type EventRecord } from './derive'
import { dimmedEngineerIds } from './engineer-filter'
import { withRoads } from './geo'
import { km, MINE_TITLE } from './labels'
import { collectEventRecords, currentKpi, describeAssignment, isAbort, planEventMessage, stripStatus } from './plan-session'
import { dayRange } from './sim'
import { hhmm } from './time'
import type { BarVariant, MapMode, Matched, MineVariant, Plan, PlanEvent, PlanResponse, SavedPlan, Scenario, Tab, Variant } from './types'
import { useComparedPlans } from './useComparedPlans'
import { useEventReview } from './useEventReview'
import { useLiveRun } from './useLiveRun'
import { useMapInteraction } from './useMapInteraction'
import { usePlanningRequests } from './usePlanningRequests'
import { useRequiredOrders } from './useRequiredOrders'
import { useRoadLegs } from './useRoadLegs'
import { useRoads } from './useRoads'
import { useScenarioCatalog } from './useScenarioCatalog'
import { useSimulation } from './useSimulation'
import { useVariantDetails } from './useVariantDetails'
import { useVariantPreviews } from './useVariantPreviews'

interface PreEvent {
  variants: Variant[]
  mine: MineVariant | null
}

function variantOptions(variants: BarVariant[], mine: MineVariant | null, exceptId: string | null): VariantOption[] {
  const options = [
    ...variants.map((v) => ({ planId: v.plan_id, title: v.title })),
    ...(mine ? [{ planId: mine.planId, title: mine.title ?? MINE_TITLE }] : []),
  ]
  return options.filter((option, index) => option.planId !== exceptId && options.findIndex((o) => o.planId === option.planId) === index)
}

export default function App() {
  const [error, setError] = useState<string | null>(null)
  const catalog = useScenarioCatalog(setError)
  const { scenarioId } = catalog
  const [required, toggleRequired] = useRequiredOrders(scenarioId)
  const [params, setParams] = useState<PlanParamsUi>(DEFAULT_PARAMS)
  const [preview, setPreview] = useState<Scenario | null>(null)

  const [initial, setInitial] = useState<Matched | null>(null)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [scenario, setScenario] = useState<Scenario | null>(null)
  const [history, setHistory] = useState<EventRecord[]>([])

  const [tab, setTab] = useState<Tab>('map')
  const [mapMode, setMapMode] = useState<MapMode>('plan')
  const map = useMapInteraction()

  const [variants, setVariants] = useState<Variant[]>([])
  const [mine, setMine] = useState<MineVariant | null>(null)
  const [eventRecords, setEventRecords] = useState<Record<string, EventRecord>>({})
  const [selecting, setSelecting] = useState<string | null>(null)
  const [pendingSwitch, setPendingSwitch] = useState<string | null>(null)
  const previews = useVariantPreviews(plan?.id ?? null)
  const { hoverVariant, setHoverVariant, variantPlans, setVariantPlans, hovered, hoveredRoutes } = previews
  const details = useVariantDetails(variantPlans, setVariantPlans)
  const eventReview = useEventReview()
  const { review } = eventReview
  const { job, cancelPlan, requestPlan, requestEvent } = usePlanningRequests()
  const live = useLiveRun(job)
  const { liveRoutes } = live

  const selectVariantRef = useRef<(planId: string) => Promise<void>>(async () => {})
  const planRef = useRef<Plan | null>(null)
  planRef.current = plan
  const historyRef = useRef<EventRecord[]>([])
  historyRef.current = history
  const preEventRef = useRef<PreEvent | null>(null)

  const reviewPlan = review?.record.after ?? null
  const { roadsFor, resetRoads } = useRoads(reviewPlan ?? plan, variantPlans)

  const compareTarget = review ? eventReview.shownId : hoverVariant ?? plan?.id ?? null
  const compared = useComparedPlans({ tab, targetId: compareTarget, plan, onError: setError })

  const clearPlanState = useCallback(() => {
    setHistory([])
    setVariants([])
    setMine(null)
    setEventRecords({})
    compared.clear()
    preEventRef.current = null
  }, [compared.clear])

  useEffect(() => {
    cancelPlan()
    setPreview(null)
    setInitial(null)
    setPlan(null)
    setScenario(null)
    clearPlanState()
    setVariantPlans({})
    resetRoads()
    map.clearMap()
    setTab('map')
    setMapMode('plan')
    setParams((p) => ({ ...p, engineerCount: null }))
    let cancelled = false
    api
      .scenario(scenarioId)
      .then((s) => !cancelled && setPreview(s))
      .catch((e) => !cancelled && setError((e as Error).message))
    return () => {
      cancelled = true
    }
  }, [scenarioId, catalog.scenarioVersion, cancelPlan, clearPlanState, setVariantPlans, resetRoads, map.clearMap])

  const showPlan = useCallback(
    (response: PlanResponse) => {
      setPlan(response.optimized)
      setScenario(response.scenario)
      setVariantPlans((cache) => ({ ...cache, [response.optimized.id]: response.optimized }))
    },
    [setVariantPlans],
  )

  const accept = useCallback(
    (response: PlanResponse) => {
      setInitial(matchedFrom(response))
      setPlan(response.optimized)
      setScenario(response.scenario)
      clearPlanState()
      setVariants(response.variants)
      setVariantPlans({ [response.optimized.id]: response.optimized })
      setHoverVariant(null)
    },
    [clearPlanState, setVariantPlans, setHoverVariant],
  )

  const run = useCallback(async () => {
    const request: PlanRequest = {
      scenarioId,
      objective: params.objective,
      timeLimit: params.timeLimit,
      lunch: params.lunch,
      engineerCount: params.engineerCount,
      allowReschedule: params.allowReschedule,
      requiredOrders: [...required].filter((id) => scenario?.orders.some((o) => o.id === id) ?? true),
    }
    setError(null)
    map.clearSelection()
    map.setCandidate(null)
    setVariants([])
    setMine(null)
    setHoverVariant(null)
    setTab('map')
    setMapMode('plan')
    live.watchVariant(variants.find((v) => v.plan_id === plan?.id)?.key ?? null)
    try {
      const response = await requestPlan(request)
      if (!response) {
        return
      }
      accept(response)
      const watched = response.variants.find((v) => v.key === live.watchRef.current)
      if (watched && watched.plan_id !== response.optimized.id) {
        await selectVariantRef.current(watched.plan_id)
      }
    } catch (e) {
      if (isAbort(e)) {
        return
      }
      setError(`План не построен: ${stripStatus((e as Error).message)}`)
    }
  }, [scenarioId, params, required, scenario, requestPlan, accept, variants, plan?.id, live.watchVariant, live.watchRef, map.clearSelection, map.setCandidate, setHoverVariant])

  const selectVariant = useCallback(
    async (planId: string) => {
      if (planId === plan?.id) {
        setMine((m) => (m?.draft ? null : m))
        return
      }
      setSelecting(planId)
      try {
        const response = await api.select(planId)
        const record = eventRecords[planId]
        if (!historyRef.current.length) {
          setInitial(matchedFrom(response))
          setHistory([])
        } else if (record) {
          setHistory((items) => [...items.slice(0, -1), record])
        }
        showPlan(response)
        setMine((m) => (m?.draft ? null : m))
        map.clearSelection()
      } catch (e) {
        setError(`Вариант не выбран: ${(e as Error).message}`)
      } finally {
        setSelecting(null)
        setHoverVariant(null)
      }
    },
    [plan?.id, eventRecords, showPlan, map.clearSelection, setHoverVariant],
  )
  selectVariantRef.current = selectVariant

  const copyPlan = useCallback(() => {
    const current = planRef.current
    if (!current) {
      return
    }
    const from = variants.find((v) => v.plan_id === current.id)?.title
    setMine({ planId: current.id, metrics: current.metrics, from, draft: true })
  }, [variants])

  const assign = useCallback(
    async (orderId: string, engineerId: string | null, position: number | 'best'): Promise<AssignResult> => {
      const current = planRef.current
      if (!current || !scenario) {
        return { ok: false, text: 'Плана нет.' }
      }
      const before = current.metrics
      try {
        const response = await api.manual(current.id, orderId, engineerId, position)
        const after = response.optimized
        setPlan(after)
        setScenario(response.scenario)
        setVariantPlans((cache) => ({ ...cache, [after.id]: after }))
        const from = variants.find((v) => v.plan_id === current.id)?.title
        setMine((m) => ({ planId: after.id, metrics: after.metrics, from: m?.planId === current.id ? m.from : from, draft: false }))
        setEventRecords((records) => (records[current.id] ? { ...records, [after.id]: records[current.id] } : records))
        if (!historyRef.current.length) {
          setInitial(matchedFrom(response))
        }
        const where = describeAssignment(orderId, engineerId, after, scenario.engineers)
        return {
          ok: true,
          text: `${where} Пробег ${km(before.distance_total_km)} → ${km(after.metrics.distance_total_km)} км.`,
        }
      } catch (e) {
        const message = (e as Error).message
        return { ok: false, text: e instanceof ApiError && e.status === 422 ? message : `Ошибка сервиса: ${message}` }
      }
    },
    [scenario, variants, setVariantPlans],
  )

  const saveCurrent = useCallback(async (name: string) => {
    const current = planRef.current
    if (!current) {
      return
    }
    try {
      await api.savePlan(current.id, name)
    } catch (e) {
      setError(`План не сохранён: ${(e as Error).message}`)
      throw e
    }
  }, [])

  const openSaved = useCallback(
    async (item: SavedPlan) => {
      const current = planRef.current
      try {
        const response = await api.loadSaved(item.id, current?.id)
        const loaded = response.optimized
        if (!current) {
          accept(response)
        } else {
          if (!historyRef.current.length) {
            setInitial(matchedFrom(response))
          }
          showPlan(response)
        }
        setMine({ planId: loaded.id, title: item.name, metrics: loaded.metrics, from: item.from_title ?? undefined, draft: false })
        map.clearSelection()
        setHoverVariant(null)
      } catch (e) {
        setError(`План не открыт: ${(e as Error).message}`)
        throw e
      }
    },
    [accept, showPlan, map.clearSelection, setHoverVariant],
  )

  const removeSaved = useCallback(async (id: string) => {
    try {
      await api.deleteSaved(id)
    } catch (e) {
      setError(`План не удалён: ${(e as Error).message}`)
    }
  }, [])

  const applyEvent = useCallback(
    async (event: PlanEvent) => {
      const before = planRef.current
      if (!before) {
        throw new ApiError('Плана нет.', 0)
      }
      const started = Date.now()
      let response
      try {
        response = await requestEvent(before, event)
      } catch (e) {
        const message = planEventMessage(e)
        setError(`Событие не применено: ${message}`)
        throw new ApiError(message, 0)
      }
      const recommended = response.plan.id
      const records = await collectEventRecords(event, before, response)
      const eventVariants = response.variants.filter((v) => records[v.plan_id])
      const scenarioAfter = response.scenario
      const chosenId = await eventReview.ask({ records, variants: eventVariants, recommended, scenario: scenarioAfter })
      eventReview.close()
      setHoverVariant(null)
      const record = records[chosenId ?? recommended]
      const summary = {
        moved: record.changes.changed.length,
        frozen: record.changes.frozen.length,
        planId: record.after.id,
        seconds: Math.round((Date.now() - started) / 1000),
        added: addedLabel(event, record.after, scenarioAfter),
      }
      if (!chosenId) {
        return { ...summary, planId: before.id, rejected: true }
      }
      if (!historyRef.current.length) {
        preEventRef.current = { variants, mine }
      }
      setHistory((items) => [...items, record])
      setPlan(record.after)
      setScenario(scenarioAfter)
      setVariants(eventVariants)
      setMine(null)
      setEventRecords((all) => ({ ...all, ...records }))
      setVariantPlans((cache) => ({ ...cache, ...Object.fromEntries(Object.values(records).map((r) => [r.after.id, r.after])) }))
      return summary
    },
    [requestEvent, eventReview.ask, eventReview.close, variants, mine, setHoverVariant, setVariantPlans],
  )

  const range = useMemo<[number, number]>(
    () => (initial ? dayRange(initial.scenario, initial.optimized.routes) : [8 * 60, 22 * 60]),
    [initial],
  )
  const sim = useSimulation({ range, run: applyEvent })
  const simTouched = history.length > 0 || sim.clock > range[0] || sim.playing

  useEffect(() => {
    eventReview.reviewRef.current?.decide(false)
    sim.reset(initial?.scenario.events ?? [], range[0])
  }, [initial, range, sim.reset])

  const resetToInitial = useCallback(() => {
    if (!initial) {
      return
    }
    eventReview.reviewRef.current?.decide(false)
    setPlan(initial.optimized)
    setScenario(initial.scenario)
    setHistory([])
    if (preEventRef.current) {
      setVariants(preEventRef.current.variants)
      setMine(preEventRef.current.mine)
      preEventRef.current = null
    }
    map.clearSelection()
    sim.reset(initial.scenario.events, range[0])
  }, [initial, range, sim, eventReview.reviewRef, map.clearSelection])

  useEffect(() => {
    if (job && sim.playing) {
      sim.toggle()
    }
  }, [job, sim.playing, sim.toggle])

  const last = history[history.length - 1] ?? null
  const changed = useMemo(() => changedOrders(last), [last])
  const reviewChanged = useMemo(() => changedOrders(review?.record ?? null), [review])
  const unavailable = useMemo(
    () => new Set(history.flatMap((h) => (h.event.type === 'engineer_unavailable' ? [h.event.engineer_id] : []))),
    [history],
  )

  const legScope = useMemo<LegScope | null>(() => {
    if (liveRoutes) {
      if (job?.kind === 'plan') {
        return { scenarioId, engineerCount: params.engineerCount }
      }
      return plan ? { planId: plan.id } : null
    }
    return (hoveredRoutes || map.candidate) && plan ? { planId: plan.id } : null
  }, [liveRoutes, hoveredRoutes, map.candidate, job?.kind, scenarioId, params.engineerCount, plan?.id])
  const shownRoutes = liveRoutes ?? hoveredRoutes
  const roadLegs = useRoadLegs(legScope, shownRoutes ?? map.candidate?.routes ?? null)
  const displayPlan = reviewPlan ?? hovered ?? plan
  const scheduleChanged = useMemo(() => {
    if (review) {
      return reviewChanged
    }
    return hovered && plan ? differingOrders(plan, hovered) : changed
  }, [review, reviewChanged, hovered, plan, changed])

  const mapScenario = review?.scenario ?? scenario ?? preview
  const busy = job !== null || sim.busy
  const activeMapMode: MapMode = plan && scenario ? mapMode : 'plan'
  const simMode = tab === 'map' && activeMapMode === 'sim'
  const workspaceScenario = simMode ? review?.scenario ?? scenario : mapScenario
  const colorOf = useMemo(
    () => (workspaceScenario ? colorResolver(map.colorMode, workspaceScenario) : () => ''),
    [map.colorMode, workspaceScenario],
  )
  const workspacePlan = simMode ? reviewPlan ?? plan : displayPlan
  const dimmedEngineers = useMemo(
    () => dimmedEngineerIds(workspaceScenario?.engineers ?? [], map.engineerFilter),
    [workspaceScenario, map.engineerFilter],
  )
  const simView = useSimulationView({ sim, plan: workspacePlan, scenario: workspaceScenario, geometry: withRoads(roadsFor(workspacePlan)), enabled: simMode })
  const simPicking = simMode && (simView.form === 'urgent_order' || simView.form === 'new_order')
  const simMap = simMode
    ? { states: simView.states, clock: sim.clock, group: simView.group, onClearGroup: () => simView.setStatusFilter(null) }
    : null

  const kpiView = currentKpi(live.liveProgress, displayPlan, review?.scenario ?? scenario ?? preview)
  const kpiBefore = (review?.record ?? last)?.diff.metrics_before ?? null

  const switchMapMode = useCallback(
    (mode: MapMode) => {
      setMapMode(mode)
      map.clearMap()
    },
    [map.clearMap],
  )

  const switchTab = useCallback(
    (next: Tab) => {
      setTab(next)
      map.clearMap()
      details.close()
    },
    [map.clearMap, details.close],
  )

  const goToOrder = useCallback(
    (id: string) => {
      setTab('map')
      setMapMode('plan')
      map.focusOrder(id)
    },
    [map.focusOrder],
  )

  const requestVariant = useCallback(
    (planId: string) => {
      if (planId === plan?.id || !simTouched || historyRef.current.length) {
        void selectVariant(planId)
        return
      }
      setPendingSwitch(planId)
    },
    [plan?.id, simTouched, selectVariant],
  )

  const confirmSwitch = () => {
    if (!pendingSwitch) {
      return
    }
    setPendingSwitch(null)
    void selectVariant(pendingSwitch)
  }

  const now = simTouched ? sim.clock : null
  const nowLabel = `симуляция ${hhmm(Math.floor(sim.clock))}`
  const barVariants = useMemo<BarVariant[]>(
    () => (variants.length || !plan ? variants : [{ key: 'plan', title: 'План', plan_id: plan.id, metrics: plan.metrics }]),
    [variants, plan],
  )

  const detailOptions = useMemo(() => variantOptions(barVariants, mine, plan?.id ?? null), [barVariants, mine, plan?.id])
  const currentTitle = useMemo(() => variantOptions(barVariants, mine, null).find((o) => o.planId === plan?.id)?.title ?? 'План', [barVariants, mine, plan?.id])
  const closeDetails = details.close
  useEffect(() => closeDetails(), [plan?.id, review, job, closeDetails])

  const selectedOrder = map.selectedOrder
  const selectedEngineer = map.selectedEngineer

  function renderRightPanel(workspaceScenario: Scenario) {
    if (simMode && workspacePlan) {
      return <EventsPanel sim={sim} view={simView} plan={workspacePlan} scenario={workspaceScenario} reviewing={review !== null} />
    }
    if (plan && scenario && selectedOrder) {
      return (
        <JobPanel
          plan={plan}
          scenario={scenario}
          orderId={selectedOrder}
          change={last?.changes.changed.find((c) => c.orderId === selectedOrder) ?? null}
          busy={busy}
          onClose={map.clearSelection}
          onGoToOrder={goToOrder}
          onSelectEngineer={map.selectEngineer}
          onPreview={map.setCandidate}
          onAssign={assign}
        />
      )
    }
    return (
      <JobQueue
        scenario={workspaceScenario}
        plan={liveRoutes ? null : displayPlan}
        filter={map.queueFilter}
        onFilter={map.setQueueFilter}
        selectedOrder={selectedOrder}
        onSelectOrder={map.selectOrder}
        onGoToOrder={goToOrder}
        changed={changed}
        required={required}
        onToggleRequired={toggleRequired}
      />
    )
  }

  const simToggle = (
    <SimToggle on={simMode} disabled={!plan} needsDecision={review !== null} onToggle={() => switchMapMode(simMode ? 'plan' : 'sim')} />
  )
  const showEmptyCompare = tab === 'compare' && !compared.shown
  const showMapLoading = tab === 'map' && !mapScenario

  return (
    <EngineerColorContext.Provider value={colorOf}>
      <div className="app">
        <Topbar
          scenarios={catalog.scenarios}
          scenarioId={scenarioId}
          onScenario={catalog.setScenarioId}
          onUpload={catalog.upload}
          uploading={catalog.uploading}
          plan={plan}
          busy={busy}
          tab={tab}
          onTab={switchTab}
          lockedTabs={!plan}
          simNeedsDecision={review !== null && tab !== 'map'}
        />

        <KpiStrip
          view={kpiView ?? emptyKpi(preview, params.engineerCount)}
          empty={!kpiView}
          live={Boolean(live.liveProgress)}
          before={kpiBefore}
          baseline={!history.length && !review && initial ? initial.baseline.metrics : null}
        />

        {error && (
          <div className="toast error" role="alert">
            <span>{error}</span>
            {!catalog.scenarios.length && (
              <button type="button" className="ghost small" onClick={catalog.reload}>
                Повторить
              </button>
            )}
            <button type="button" className="icon" onClick={() => setError(null)} aria-label="Скрыть">
              ×
            </button>
          </div>
        )}

        <main className={`main tab-${tab}`}>
          {tab === 'map' && workspaceScenario && (
            <Workspace
              busy={!simMode && job !== null}
              top={simMode && <SimulationBar sim={sim} onReset={resetToInitial} lead={simToggle} />}
              left={
                <div className="left-stack">
                  {!simMode && simToggle}
                  <EngineerList
                    scenario={workspaceScenario}
                    plan={workspacePlan}
                    liveRoutes={simMode ? null : liveRoutes}
                    selected={selectedEngineer}
                    selectedOrder={selectedOrder}
                    onSelect={map.selectEngineer}
                    onSelectOrder={map.selectOrder}
                    unavailable={simMode ? simView.unavailable : unavailable}
                    simStates={simMode ? simView.byId : null}
                    group={simMode ? simView.group : null}
                    onGoToPlace={map.focusPlace}
                    filter={map.engineerFilter}
                    onFilter={map.setEngineerFilter}
                    onHover={map.setHoverEngineer}
                  />
                </div>
              }
              map={
                <MapView
                  scenario={workspaceScenario}
                  plan={workspacePlan}
                  routesOverride={simMode ? null : shownRoutes}
                  geometry={roadsFor(workspacePlan)}
                  placeFocus={map.placeFocus}
                  required={required}
                  onToggleRequired={toggleRequired}
                  roadLegs={simMode ? null : roadLegs}
                  selectedOrder={selectedOrder}
                  selectedEngineer={selectedEngineer}
                  changed={review ? reviewChanged : changed}
                  preview={simMode ? null : map.candidate}
                  focus={simMode ? null : map.focus}
                  sim={simMap}
                  pickPoint={simPicking ? simView.setPicked : null}
                  pickedPoint={simPicking ? simView.picked : null}
                  onSelectOrder={map.selectOrder}
                  onSelectEngineer={map.selectEngineer}
                  colorMode={map.colorMode}
                  onColorMode={map.setColorMode}
                  hoverEngineer={map.hoverEngineer}
                  dimmed={dimmedEngineers}
                />
              }
              mapOverlay={
                simMode && (
                  <StatusLegend
                    states={simView.states}
                    active={simView.statusFilter}
                    onPick={(status) => simView.setStatusFilter(simView.statusFilter === status ? null : status)}
                  />
                )
              }
              right={renderRightPanel(workspaceScenario)}
            />
          )}
          {showMapLoading && (
            <div className="loading-screen">
              <span className="spinner lg" />
            </div>
          )}

          {tab === 'schedule' && plan && scenario && (
            <Schedule
              scenario={review?.scenario ?? scenario}
              plan={displayPlan ?? plan}
              now={now}
              nowLabel={nowLabel}
              selectedOrder={selectedOrder}
              selectedEngineer={selectedEngineer}
              changed={scheduleChanged}
              unavailable={unavailable}
              busy={busy}
              previewing={hovered !== null || review !== null}
              onSelectOrder={map.selectOrder}
              onGoToOrder={goToOrder}
              onSelectEngineer={map.selectEngineer}
              onAssign={assign}
            />
          )}

          {tab === 'compare' && compared.shown && (
            <div className="compare-page">
              <Comparison matched={compared.shown} />
            </div>
          )}
          {showEmptyCompare && (
            <div className="loading-screen">
              <span className="spinner lg" />
            </div>
          )}

          {review && eventReview.details && <EventReviewSchedule review={review} onClose={() => eventReview.setDetails(false)} />}

          {plan && scenario && !review && details.otherId && (
            <VariantSchedule
              scenario={scenario}
              current={plan}
              currentTitle={currentTitle}
              options={detailOptions}
              otherId={details.otherId}
              other={details.other}
              onPick={details.open}
              onClose={details.close}
            />
          )}

          <div className="bar-slot">
            {pendingSwitch && <SwitchConfirm clock={sim.clock} onConfirm={confirmSwitch} onCancel={() => setPendingSwitch(null)} />}
            <VariantBar
              job={job}
              variants={barVariants}
              mine={mine}
              review={review}
              tools={
                plan && (
                  <PlanStorage
                    canSave={!busy}
                    onCopy={mine || variants.length === 0 ? null : copyPlan}
                    onSave={saveCurrent}
                    onList={() => api.savedPlans(scenarioId)}
                    onLoad={openSaved}
                    onDelete={removeSaved}
                  />
                )
              }
              planControl={
                <PlanControl
                  brief={catalog.scenarios.find((item) => item.id === scenarioId)}
                  params={params}
                  onParams={setParams}
                  plan={plan}
                  busy={busy}
                  onPlan={run}
                />
              }
              currentPlanId={plan?.id ?? null}
              hovered={hoverVariant}
              onHover={setHoverVariant}
              onSelect={requestVariant}
              locked={sim.playing}
              selecting={selecting}
              watching={live.watching}
              onWatch={live.watchVariant}
              onPeek={live.setPeekKey}
              onReviewDetails={() => eventReview.setDetails(true)}
              onCompare={details.toggle}
              comparing={details.otherId}
              scheduleOpen={tab === 'schedule'}
              onToggleSchedule={() => switchTab(tab === 'schedule' ? 'map' : 'schedule')}
            />
          </div>
        </main>
      </div>
    </EngineerColorContext.Provider>
  )
}
