import { useMemo, useState } from 'react'

import { hhmm, minutes } from '../colors'
import type { LatLon } from '../geo'
import { routeLegs } from '../geo'
import { plural } from '../labels'
import { engineerState, marksFromEvents, type EngineerState } from '../sim'
import type { Order, Plan, PlanEvent, PlanGeometry, Scenario } from '../types'
import type { SimEvent, Simulation, Speed } from '../useSimulation'
import { EngineerList } from './EngineerList'
import { MapView } from './MapView'
import { KIND_TITLE, SimulationEventForm, type Kind } from './SimulationEventForm'

export function describeEvent(event: PlanEvent, scenario: Scenario): string {
  const name = (id: string) => scenario.engineers.find((e) => e.id === id)?.name ?? id
  switch (event.type) {
    case 'urgent_order':
    case 'new_order':
      return `${event.order.id}${event.order.district ? `, ${event.order.district}` : ''}`
    case 'cancel_order':
      return `заявка ${event.order_id}`
    case 'engineer_unavailable':
      return name(event.engineer_id)
    case 'engineer_delayed':
      return `${name(event.engineer_id)} на ${event.minutes} мин`
  }
}

interface Props {
  sim: Simulation
  plan: Plan
  scenario: Scenario
  geometry: PlanGeometry | null
  changed: Set<string>
  selectedOrder: string | null
  selectedEngineer: string | null
  onSelectOrder: (id: string | null) => void
  onSelectEngineer: (id: string | null) => void
  onReset: () => void
}

export function SimulationView({
  sim,
  plan,
  scenario,
  geometry,
  changed,
  selectedOrder,
  selectedEngineer,
  onSelectOrder,
  onSelectEngineer,
  onReset,
}: Props) {
  const [form, setForm] = useState<Kind | null>(null)
  const [picked, setPicked] = useState<LatLon | null>(null)
  const orders = useMemo(() => Object.fromEntries(scenario.orders.map((o) => [o.id, o])) as Record<string, Order>, [scenario])
  const marks = useMemo(() => marksFromEvents(sim.events.filter((e) => e.status === 'done').map((e) => e.event)), [sim.events])
  const legs = useMemo(() => {
    const result: Record<string, LatLon[][]> = {}
    for (const route of plan.routes) result[route.engineer_id] = routeLegs(plan, route.engineer_id, scenario, orders, geometry)
    return result
  }, [plan, scenario, orders, geometry])

  const states: EngineerState[] = scenario.engineers.map((engineer) =>
    engineerState(
      sim.clock,
      engineer,
      plan.routes.find((r) => r.engineer_id === engineer.id),
      legs[engineer.id] ?? [],
      scenario,
      orders,
      marks[engineer.id],
    ),
  )
  const byId = Object.fromEntries(states.map((s) => [s.engineerId, s]))
  const unavailable = new Set(Object.entries(marks).filter(([, m]) => m.unavailableFrom !== undefined && sim.clock >= m.unavailableFrom).map(([id]) => id))
  const [from, to] = sim.range
  const pct = (t: number) => ((t - from) / (to - from)) * 100

  return (
    <div className="sim">
      <div className="sim-bar">
        <button
          type="button"
          className="primary play"
          onClick={sim.toggle}
          disabled={sim.busy}
          aria-label={sim.playing ? 'Пауза' : 'Пуск'}
        >
          {sim.playing ? <PauseGlyph /> : <PlayGlyph />}
          {sim.resumeIn !== null ? `через ${sim.resumeIn}` : sim.playing ? 'Пауза' : 'Пуск'}
        </button>
        <div className="sim-clock" aria-live="off">
          {sim.clockLabel}
        </div>
        <div className="seg speed" role="radiogroup" aria-label="Скорость">
          {([30, 60, 120] as Speed[]).map((s) => (
            <button key={s} type="button" role="radio" aria-checked={sim.speed === s} className={sim.speed === s ? 'on' : ''} onClick={() => sim.setSpeed(s)}>
              ×{s}
            </button>
          ))}
        </div>
        <div className="scrub">
          <div className="scrub-ticks" aria-hidden>
            {sim.events.map((e) => (
              <i
                key={e.id}
                className={`tick ${e.status}`}
                style={{ left: `${pct(minutes(e.event.time))}%` }}
                title={`${e.event.time} ${KIND_TITLE[e.event.type as Kind]}`}
              />
            ))}
          </div>
          <input
            type="range"
            min={from}
            max={to}
            step={1}
            value={Math.floor(sim.clock)}
            disabled={sim.busy}
            aria-label="Время дня"
            onChange={(e) => sim.setClock(Number(e.target.value))}
          />
          <div className="scrub-scale" aria-hidden>
            <span>{hhmm(from)}</span>
            <span>{hhmm(Math.round((from + to) / 2 / 60) * 60)}</span>
            <span>{hhmm(to)}</span>
          </div>
        </div>
        <button type="button" className="ghost" onClick={onReset} disabled={sim.busy}>
          Сначала
        </button>
      </div>

      <div className="sim-body">
        <EngineerList
          scenario={scenario}
          plan={plan}
          selected={selectedEngineer}
          selectedOrder={selectedOrder}
          onSelect={onSelectEngineer}
          onSelectOrder={(id) => onSelectOrder(id)}
          simStates={byId}
          unavailable={unavailable}
        />
        <div className="map-pane">
          <MapView
            scenario={scenario}
            plan={plan}
            geometry={geometry}
            selectedOrder={selectedOrder}
            selectedEngineer={selectedEngineer}
            changed={changed}
            sim={{ states, clock: sim.clock }}
            pickPoint={form === 'urgent_order' || form === 'new_order' ? setPicked : null}
            pickedPoint={form === 'urgent_order' || form === 'new_order' ? picked : null}
            onSelectOrder={onSelectOrder}
            onSelectEngineer={onSelectEngineer}
          />
          <StatusLegend states={states} />
        </div>
        <div className="panel events-panel">
          <div className="panel-head">
            <h2>События дня</h2>
            <span className="muted small">{sim.events.filter((e) => e.status === 'done').length} из {sim.events.length}</span>
          </div>
          <div className="panel-scroll">
            <ol className="ev-list">
              {sim.events.length === 0 && <li className="empty-note">Событий нет.</li>}
              {sim.events.map((item) => (
                <EventRow key={item.id} item={item} scenario={scenario} now={sim.clock} />
              ))}
            </ol>

            <div className="ev-add">
              <div className="ev-add-head">
                Добавить в <b>{sim.clockLabel}</b>
              </div>
              <div className="ev-kinds">
                {(Object.keys(KIND_TITLE) as Kind[]).map((kind) => (
                  <button
                    key={kind}
                    type="button"
                    className={`ghost small ${form === kind ? 'active' : ''}`}
                    disabled={sim.busy}
                    onClick={() => {
                      setForm(form === kind ? null : kind)
                      setPicked(null)
                    }}
                  >
                    {KIND_TITLE[kind]}
                  </button>
                ))}
              </div>
              {form && (
                <SimulationEventForm
                  kind={form}
                  plan={plan}
                  scenario={scenario}
                  clock={sim.clock}
                  states={states}
                  picked={picked}
                  busy={sim.busy}
                  onCancel={() => setForm(null)}
                  onAdd={(event) => {
                    sim.add(event)
                    setForm(null)
                    setPicked(null)
                  }}
                />
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function EventRow({ item, scenario, now }: { item: SimEvent; scenario: Scenario; now: number }) {
  const kind = item.event.type as Kind
  const future = item.status === 'pending' && minutes(item.event.time) > now
  return (
    <li className={`ev ${item.status} ${future ? 'future' : ''}`}>
      <span className="ev-time">{item.event.time}</span>
      <span className="ev-main">
        <span className="ev-kind">
          {KIND_TITLE[kind] ?? item.event.type}
          {item.source === 'added' && <span className="tag">добавлено</span>}
        </span>
        <span className="ev-what">{describeEvent(item.event, scenario)}</span>
        {item.status === 'running' && (
          <span className="ev-state">
            <span className="spinner" /> перестраиваем план
          </span>
        )}
        {item.status === 'done' && item.summary && (
          <span className="ev-state done">
            {item.summary.added && <>{item.summary.added}. </>}
            сдвинуто {item.summary.moved} {plural(item.summary.moved, 'визит', 'визита', 'визитов')}, зафиксировано {item.summary.frozen}
            {item.summary.seconds > 0 && <span className="muted"> · {item.summary.seconds} с</span>}
          </span>
        )}
        {item.status === 'failed' && <span className="ev-state bad">не применено: {item.error}</span>}
      </span>
    </li>
  )
}

function StatusLegend({ states }: { states: EngineerState[] }) {
  const counts = new Map<string, number>()
  for (const s of states) counts.set(s.status, (counts.get(s.status) ?? 0) + 1)
  const order: [string, string][] = [
    ['moving', 'в пути'],
    ['onsite', 'на объекте'],
    ['waiting', 'ждёт окна'],
    ['lunch', 'обед'],
    ['idle', 'свободен'],
    ['delayed', 'задержка'],
    ['unavailable', 'недоступен'],
    ['done', 'смена окончена'],
  ]
  return (
    <div className="status-legend">
      {order
        .filter(([key]) => counts.get(key))
        .map(([key, label]) => (
          <span key={key} className={`status s-${key}`}>
            {label} {counts.get(key)}
          </span>
        ))}
    </div>
  )
}


function PlayGlyph() {
  return (
    <svg className="glyph" viewBox="0 0 16 16" aria-hidden>
      <path d="M4.5 2.8v10.4L13 8z" fill="currentColor" />
    </svg>
  )
}
function PauseGlyph() {
  return (
    <svg className="glyph" viewBox="0 0 16 16" aria-hidden>
      <rect x="3.5" y="2.8" width="3" height="10.4" rx="0.8" fill="currentColor" />
      <rect x="9.5" y="2.8" width="3" height="10.4" rx="0.8" fill="currentColor" />
    </svg>
  )
}
