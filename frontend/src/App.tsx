import { useCallback, useEffect, useMemo, useState } from 'react'

import { api } from './api'
import { MapView } from './components/MapView'
import { Timeline } from './components/Timeline'
import { EventPanel } from './components/EventPanel'
import {
  DiffView,
  MetricsPanel,
  OrderCard,
  RoutesTable,
  UnassignedList,
} from './components/Panels'
import type {
  Diff,
  MetricRow,
  Objective,
  Plan,
  PlanEvent,
  Scenario,
  ScenarioBrief,
} from './types'
import { SKILL_COLOR, SKILL_RU } from './types'

type Tab = 'routes' | 'unassigned' | 'metrics' | 'diff'

export default function App() {
  const [scenarios, setScenarios] = useState<ScenarioBrief[]>([])
  const [scenarioId, setScenarioId] = useState('demo')
  const [objective, setObjective] = useState<Objective>('auto')
  const [timeLimit, setTimeLimit] = useState(15)
  const [lunch, setLunch] = useState(false)

  const [scenario, setScenario] = useState<Scenario | null>(null)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [comparison, setComparison] = useState<MetricRow[]>([])
  const [diff, setDiff] = useState<Diff | null>(null)

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('routes')
  const [selectedOrder, setSelectedOrder] = useState<string | null>(null)
  const [selectedEngineer, setSelectedEngineer] = useState<string | null>(null)

  useEffect(() => {
    api.scenarios().then((list) => {
      setScenarios(list)
      if (list.length && !list.some((s) => s.id === scenarioId)) setScenarioId(list[0].id)
    }).catch((e) => setError(e.message))
  }, [])

  useEffect(() => {
    api.scenario(scenarioId).then(setScenario).catch((e) => setError(e.message))
    setPlan(null)
    setDiff(null)
    setSelectedOrder(null)
    setSelectedEngineer(null)
  }, [scenarioId])

  const run = useCallback(async () => {
    setBusy(true)
    setError(null)
    setDiff(null)
    setSelectedOrder(null)
    try {
      const response = await api.plan(scenarioId, objective, timeLimit, lunch)
      setPlan(response.optimized)
      setComparison(response.comparison)
      setScenario(response.scenario)
      setTab('routes')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }, [scenarioId, objective, timeLimit, lunch])

  const applyEvent = useCallback(
    async (event: PlanEvent) => {
      if (!plan) return
      setBusy(true)
      setError(null)
      try {
        const response = await api.event(plan.id, event)
        setPlan(response.plan)
        setScenario(response.scenario)
        setDiff(response.diff)
        setTab('diff')
      } catch (e) {
        setError((e as Error).message)
      } finally {
        setBusy(false)
      }
    },
    [plan],
  )

  const manual = useCallback(
    async (orderId: string, engineerId: string | null) => {
      if (!plan) return
      setBusy(true)
      setError(null)
      try {
        const response = await api.manual(plan.id, orderId, engineerId)
        setPlan(response.optimized)
        setComparison(response.comparison)
        setScenario(response.scenario)
      } catch (e) {
        setError((e as Error).message)
      } finally {
        setBusy(false)
      }
    },
    [plan],
  )

  const brief = useMemo(
    () => scenarios.find((s) => s.id === scenarioId),
    [scenarios, scenarioId],
  )

  return (
    <div className="app">
      {/* ------------------------------------------------ управление */}
      <div className="column">
        <div className="panel">
          <h2>Планирование маршрутов</h2>
          <div className="field">
            <label>Участок</label>
            <select value={scenarioId} onChange={(e) => setScenarioId(e.target.value)}>
              {scenarios.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </div>
          {brief && (
            <p className="small muted" style={{ marginTop: -4 }}>
              {brief.date} · {brief.orders} заявок · {brief.engineers} инженеров
              <br />
              офис: {brief.office}
            </p>
          )}

          <div className="field">
            <label>Что важнее</label>
            <select value={objective} onChange={(e) => setObjective(e.target.value as Objective)}>
              <option value="auto">Выбрать лучшее автоматически</option>
              <option value="min_engineers">Меньше задействованных инженеров</option>
              <option value="min_distance">Меньше пробега</option>
            </select>
          </div>
          <div className="field">
            <label>Время на расчёт: {timeLimit} с</label>
            <input
              type="range"
              min={3}
              max={60}
              value={timeLimit}
              onChange={(e) => setTimeLimit(Number(e.target.value))}
            />
          </div>
          <label className="row small" style={{ marginBottom: 10 }}>
            <input
              type="checkbox"
              style={{ width: 'auto' }}
              checked={lunch}
              onChange={(e) => setLunch(e.target.checked)}
            />
            <span>учитывать обеденный перерыв</span>
          </label>

          <button className="primary" style={{ width: '100%' }} disabled={busy} onClick={run}>
            {busy ? (
              <>
                <span className="spinner" />
                Считаем…
              </>
            ) : (
              'Спланировать день'
            )}
          </button>
        </div>

        {plan && scenario && (
          <EventPanel
            scenario={scenario}
            plan={plan}
            pickedPoint={null}
            busy={busy}
            onApply={applyEvent}
          />
        )}

        {plan && (
          <div className="panel">
            <h2>Выгрузка</h2>
            <a href={api.exportUrl(plan.id)} target="_blank" rel="noreferrer">
              Результат в формате ТЗ §2.4.2
            </a>
            <p className="small muted" style={{ marginBottom: 0 }}>
              План {plan.id}
              {plan.parent_plan_id && `, построен из ${plan.parent_plan_id}`}
            </p>
          </div>
        )}
      </div>

      {/* ------------------------------------------------------ карта */}
      <div className="column">
        {error && <div className="error">{error}</div>}
        {scenario && plan ? (
          <>
            <div className="summary">{plan.plan_explanation}</div>
            <div className="map">
              <MapView
                scenario={scenario}
                plan={plan}
                diff={diff}
                selectedOrder={selectedOrder}
                selectedEngineer={selectedEngineer}
                onSelectOrder={setSelectedOrder}
              />
            </div>
            <div className="legend">
              {(Object.keys(SKILL_RU) as (keyof typeof SKILL_RU)[]).map((skill) => (
                <span key={skill}>
                  <i className="dot" style={{ background: SKILL_COLOR[skill] }} />
                  {SKILL_RU[skill]}
                </span>
              ))}
              <span>
                <i
                  className="dot"
                  style={{ background: '#fff', border: '2px solid #c9513e' }}
                />
                не назначена
              </span>
              {diff && (
                <span>
                  <i className="dot" style={{ background: '#fff', border: '2px solid #f0a500' }} />
                  изменена событием
                </span>
              )}
              <span className="muted">заливка кружка — цвет инженера</span>
            </div>
          </>
        ) : (
          <div style={{ padding: 40, textAlign: 'center' }} className="muted">
            {scenario
              ? 'Выберите параметры слева и нажмите «Спланировать день».'
              : 'Загружаем участок…'}
          </div>
        )}
      </div>

      {/* -------------------------------------------- таймлайн и таблицы */}
      <div className="column">
        {scenario && plan && (
          <>
            <Timeline
              scenario={scenario}
              plan={plan}
              selectedOrder={selectedOrder}
              selectedEngineer={selectedEngineer}
              onSelectOrder={setSelectedOrder}
              onSelectEngineer={setSelectedEngineer}
            />
            <div className="tabs">
              <button
                className={tab === 'routes' ? 'active' : ''}
                onClick={() => setTab('routes')}
              >
                Маршруты<span className="count">{plan.metrics.engineers_used}</span>
              </button>
              <button
                className={tab === 'unassigned' ? 'active' : ''}
                onClick={() => setTab('unassigned')}
              >
                Не назначены<span className="count">{plan.unassigned.length}</span>
              </button>
              <button
                className={tab === 'metrics' ? 'active' : ''}
                onClick={() => setTab('metrics')}
              >
                Метрики
              </button>
              <button className={tab === 'diff' ? 'active' : ''} onClick={() => setTab('diff')}>
                Изменения{diff && <span className="count">{diff.changed.length}</span>}
              </button>
            </div>

            {selectedOrder && (
              <OrderCard
                planId={plan.id}
                scenario={scenario}
                orderId={selectedOrder}
                onClose={() => setSelectedOrder(null)}
                onManual={manual}
              />
            )}

            {tab === 'routes' && (
              <RoutesTable
                scenario={scenario}
                plan={plan}
                selectedOrder={selectedOrder}
                selectedEngineer={selectedEngineer}
                onSelectOrder={setSelectedOrder}
                onSelectEngineer={setSelectedEngineer}
              />
            )}
            {tab === 'unassigned' && (
              <UnassignedList
                scenario={scenario}
                plan={plan}
                selectedOrder={selectedOrder}
                onSelectOrder={setSelectedOrder}
              />
            )}
            {tab === 'metrics' && <MetricsPanel plan={plan} comparison={comparison} />}
            {tab === 'diff' && <DiffView diff={diff} scenario={scenario} />}
          </>
        )}
      </div>
    </div>
  )
}
