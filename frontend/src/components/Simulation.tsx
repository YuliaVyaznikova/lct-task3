import { useMemo, useState, type ReactNode } from 'react'

import { ordersById } from '../derive'
import type { LatLon } from '../geo'
import { routeLegs } from '../geo'
import { EVENT_KIND_TITLE, plural } from '../labels'
import { describeEvent, engineerState, marksFromEvents, STATUS_RU, type EngineerState, type SimEvent, type Simulation, type Speed } from '../sim'
import { hhmm, minutes } from '../time'
import type { EventKind, Order, Plan, PlanGeometry, Scenario } from '../types'
import { SimulationEventForm } from './SimulationEventForm'

interface SimulationViewInput {
  sim: Simulation
  plan: Plan | null
  scenario: Scenario | null
  geometry: PlanGeometry | null
  enabled: boolean
}

export interface SimulationView {
  states: EngineerState[]
  byId: Record<string, EngineerState>
  group: Set<string> | null
  unavailable: Set<string>
  statusFilter: EngineerState['status'] | null
  setStatusFilter: (status: EngineerState['status'] | null) => void
  form: EventKind | null
  setForm: (kind: EventKind | null) => void
  picked: LatLon | null
  setPicked: (point: LatLon | null) => void
}

const NO_STATES: EngineerState[] = []

export function useSimulationView({ sim, plan, scenario, geometry, enabled }: SimulationViewInput): SimulationView {
  const [form, setForm] = useState<EventKind | null>(null)
  const [picked, setPicked] = useState<LatLon | null>(null)
  const [statusFilter, setStatusFilter] = useState<EngineerState['status'] | null>(null)
  const active = enabled && plan !== null && scenario !== null
  const orders = useMemo<Record<string, Order>>(() => (scenario ? ordersById(scenario) : {}), [scenario])
  const marks = useMemo(() => marksFromEvents(sim.events.filter((e) => e.status === 'done').map((e) => e.event)), [sim.events])
  const legs = useMemo(() => {
    const result: Record<string, LatLon[][]> = {}
    if (!active) {
      return result
    }
    for (const route of plan.routes) result[route.engineer_id] = routeLegs(plan, route.engineer_id, scenario, orders, geometry)
    return result
  }, [active, plan, scenario, orders, geometry])

  const states: EngineerState[] = active
    ? scenario.engineers.map((engineer) =>
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
    : NO_STATES
  const byId = Object.fromEntries(states.map((s) => [s.engineerId, s]))
  const group = statusFilter ? new Set(states.filter((s) => s.status === statusFilter).map((s) => s.engineerId)) : null
  const unavailable = new Set(
    Object.entries(marks)
      .filter(([, m]) => m.unavailableFrom !== undefined && sim.clock >= m.unavailableFrom)
      .map(([id]) => id),
  )
  return { states, byId, group, unavailable, statusFilter, setStatusFilter, form, setForm, picked, setPicked }
}

interface SimulationBarProps {
  sim: Simulation
  onReset: () => void
  lead?: ReactNode
}

export function SimulationBar({ sim, onReset, lead = null }: SimulationBarProps) {
  const [from, to] = sim.range
  const pct = (t: number) => ((t - from) / (to - from)) * 100
  return (
    <div className="sim-bar">
      {lead}
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
      <div className="seg" role="radiogroup" aria-label="Скорость">
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
              title={`${e.event.time} ${EVENT_KIND_TITLE[e.event.type]}`}
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
  )
}

interface EventsPanelProps {
  sim: Simulation
  view: SimulationView
  plan: Plan
  scenario: Scenario
  reviewing: boolean
}

export function EventsPanel({ sim, view, plan, scenario, reviewing }: EventsPanelProps) {
  const { form, setForm, setPicked } = view
  return (
    <div className="panel" aria-label="События дня">
      <div className="panel-head">
        <h2>События дня</h2>
        <span className="muted small">{sim.events.filter((e) => e.status === 'done').length} из {sim.events.length}</span>
      </div>
      <div className="panel-scroll">
        <ol>
          {sim.events.length === 0 && <li className="empty-note">Событий нет.</li>}
          {sim.events.map((item) => (
            <EventRow key={item.id} item={item} scenario={scenario} now={sim.clock} reviewing={reviewing} />
          ))}
        </ol>

        <div className="ev-add">
          <div className="ev-add-head">
            Добавить в <b>{sim.clockLabel}</b>
          </div>
          <div className="ev-kinds">
            {(Object.keys(EVENT_KIND_TITLE) as EventKind[]).map((kind) => (
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
                {EVENT_KIND_TITLE[kind]}
              </button>
            ))}
          </div>
          {form && (
            <SimulationEventForm
              kind={form}
              plan={plan}
              scenario={scenario}
              clock={sim.clock}
              states={view.states}
              picked={view.picked}
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
  )
}


interface EventRowProps {
  item: SimEvent
  scenario: Scenario
  now: number
  reviewing: boolean
}

function EventRow({ item, scenario, now, reviewing }: EventRowProps) {
  const future = item.status === 'pending' && minutes(item.event.time) > now
  return (
    <li className={`ev ${item.status} ${future ? 'future' : ''}`}>
      <span className="ev-time">{item.event.time}</span>
      <span className="ev-main">
        <span className="ev-kind">
          {EVENT_KIND_TITLE[item.event.type]}
          {item.source === 'added' && <span className="tag">добавлено</span>}
        </span>
        <span className="ev-what">{describeEvent(item.event, scenario)}</span>
        {item.status === 'running' && !reviewing && (
          <span className="ev-state">
            <span className="spinner" /> перестраиваем план
          </span>
        )}
        {item.status === 'running' && reviewing && <span className="ev-state review">ждёт подтверждения</span>}
        {item.status === 'rejected' && <span className="ev-state">оставлен прежний план</span>}
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

interface StatusLegendProps {
  states: EngineerState[]
  active: EngineerState['status'] | null
  onPick: (status: EngineerState['status']) => void
}

export function StatusLegend({ states, active, onPick }: StatusLegendProps) {
  const counts = new Map<string, number>()
  for (const s of states) counts.set(s.status, (counts.get(s.status) ?? 0) + 1)
  return (
    <div className="status-legend">
      {(Object.keys(STATUS_RU) as EngineerState['status'][])
        .filter((key) => counts.get(key) || key === active)
        .map((key) => (
          <button
            key={key}
            type="button"
            className={`status s-${key} ${key === active ? 'on' : ''}`}
            aria-pressed={key === active}
            onClick={() => onPick(key)}
          >
            {STATUS_RU[key]} {counts.get(key) ?? 0}
          </button>
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
