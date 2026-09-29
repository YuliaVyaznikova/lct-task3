import { useEffect, useRef, useState } from 'react'

import { candidateDeltaKm, engineerName, SCHEDULE_VIEWS, shiftedVisits, signed, type ScheduleView } from '../labels'
import type { Candidate, Plan, Scenario } from '../types'
import { Gantt } from './Gantt'
import type { AssignResult } from './JobPanel'
import { RouteTable } from './RouteTable'
import { SplitHandle, useSplitShare } from './SplitHandle'
import { fetchCandidates } from './useJobCandidates'

interface ScheduleProps {
  scenario: Scenario
  plan: Plan
  now: number | null
  nowLabel: string
  selectedOrder: string | null
  selectedEngineer: string | null
  changed: Set<string>
  unavailable: Set<string>
  busy: boolean
  previewing: boolean
  onSelectOrder: (id: string) => void
  onGoToOrder: (id: string) => void
  onSelectEngineer: (id: string | null) => void
  onAssign: (orderId: string, engineerId: string | null, position: number | 'best') => Promise<AssignResult>
}

const noChanges = new Set<string>()

type Drop =
  | { orderId: string; engineerId: string; state: 'loading' }
  | { orderId: string; engineerId: string; state: 'ready'; row: Candidate }
  | { orderId: string; engineerId: string; state: 'error'; text: string }
  | { orderId: string; engineerId: string; state: 'done'; text: string }

export function Schedule(props: ScheduleProps) {
  const { scenario, plan, busy, previewing, onAssign } = props
  const [drop, setDrop] = useState<Drop | null>(null)
  const [pending, setPending] = useState(false)
  const [carried, setCarried] = useState<{ orderId: string; rows: Candidate[] } | null>(null)
  const cache = useRef(new Map<string, Candidate[]>())
  const carriedId = useRef<string | null>(null)
  const layout = useRef<HTMLDivElement>(null)
  const [share, setShare, resetShare] = useSplitShare('schedule-split', 0.56)
  const [expanded, setExpanded] = useState(false)
  const [view, setView] = useState<ScheduleView>('both')
  const name = (id: string) => engineerName(scenario.engineers, id)
  const showGantt = !expanded || view !== 'routes'
  const showTable = !expanded || view !== 'gantt'

  useEffect(() => {
    if (!expanded) {
      return
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setExpanded(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded])

  useEffect(() => {
    cache.current.clear()
  }, [plan.id])

  async function onCarryVisit(orderId: string | null) {
    if (previewing) {
      return
    }
    carriedId.current = orderId
    if (!orderId) {
      setCarried(null)
      return
    }
    const key = `${plan.id}:${orderId}`
    const known = cache.current.get(key)
    if (known) {
      setCarried({ orderId, rows: known })
      return
    }
    setCarried(null)
    const loaded = await fetchCandidates(plan.id, orderId)
    if (loaded.state === 'error') {
      return
    }
    cache.current.set(key, loaded.rows)
    if (carriedId.current === orderId) {
      setCarried({ orderId, rows: loaded.rows })
    }
  }

  async function onDropVisit(orderId: string, engineerId: string) {
    if (previewing) {
      return
    }
    setDrop({ orderId, engineerId, state: 'loading' })
    const loaded = await fetchCandidates(plan.id, orderId)
    if (loaded.state === 'error') {
      setDrop({ orderId, engineerId, state: 'error', text: loaded.text })
      return
    }
    const row = loaded.rows.find((r) => r.engineer_id === engineerId)
    if (!row) {
      setDrop({ orderId, engineerId, state: 'error', text: `${name(engineerId)} нет в списке кандидатов.` })
    } else {
      setDrop({ orderId, engineerId, state: 'ready', row })
    }
  }

  async function confirm(row: Candidate) {
    if (!drop) {
      return
    }
    setPending(true)
    const outcome = await onAssign(drop.orderId, row.engineer_id, row.position ?? 'best')
    setPending(false)
    setDrop(outcome.ok ? { ...drop, state: 'done', text: outcome.text } : { ...drop, state: 'error', text: outcome.text })
  }

  return (
    <div
      className={`schedule ${expanded ? 'expanded' : ''}`}
      ref={layout}
      style={{ gridTemplateRows: scheduleRows(expanded, view, share) }}
    >
      {showGantt && (
        <section className="sched-gantt">
          <div className="sched-head">
            <h2>Расписание</h2>
            <div className="legend">
              <span>
                <i className="sw work" /> работа
              </span>
              <span>
                <i className="sw travel" /> дорога
              </span>
              <span>
                <i className="sw wait" /> ожидание окна
              </span>
              <span>
                <i className="sw lunch" /> обед
              </span>
              <span>
                <i className="sw locked" /> зафиксирован
              </span>
              {props.now !== null && (
                <span>
                  <i className="sw now" /> {props.nowLabel}
                </span>
              )}
            </div>
            <ExpandControls expanded={expanded} view={view} onView={setView} onToggle={() => setExpanded(!expanded)} />
          </div>
          {drop && (
            <div className={`drop-card ${drop.state}`} role="status">
              {drop.state === 'loading' && (
                <>
                  <span className="spinner" /> Проверяем {drop.orderId} у {name(drop.engineerId)}…
                </>
              )}
              {drop.state === 'ready' && drop.row.feasible && (
                <>
                  <span>
                    Отдать <b>{drop.orderId}</b> → <b>{name(drop.engineerId)}</b>:{' '}
                    {signed(candidateDeltaKm(drop.row))} км
                    {drop.row.arrival && `, приедет ${drop.row.arrival}`}, {shiftedVisits(drop.row)}
                  </span>
                  <button type="button" className="primary small" disabled={busy || pending || previewing} onClick={() => confirm(drop.row)}>
                    {pending ? '…' : 'Отдать'}
                  </button>
                  <button type="button" className="ghost small" onClick={() => setDrop(null)}>
                    Отмена
                  </button>
                </>
              )}
              {drop.state === 'ready' && !drop.row.feasible && (
                <>
                  <span>
                    {name(drop.engineerId)} не может взять {drop.orderId}: {drop.row.reason ?? 'не подходит'}
                  </span>
                  <button type="button" className="ghost small" onClick={() => setDrop(null)}>
                    Закрыть
                  </button>
                </>
              )}
              {(drop.state === 'error' || drop.state === 'done') && (
                <>
                  <span>{drop.text}</span>
                  <button type="button" className="ghost small" onClick={() => setDrop(null)}>
                    Закрыть
                  </button>
                </>
              )}
            </div>
          )}
          <div className="sched-scroll">
            <Gantt
              scenario={scenario}
              plan={plan}
              now={props.now}
              nowLabel={props.nowLabel}
              selectedOrder={props.selectedOrder}
              selectedEngineer={props.selectedEngineer}
              changed={props.changed}
              unavailable={props.unavailable}
              onSelectOrder={props.onSelectOrder}
              onSelectEngineer={props.onSelectEngineer}
              onDropVisit={onDropVisit}
              onCarryVisit={onCarryVisit}
              carried={carried}
              dropTarget={drop && drop.state !== 'done' ? { orderId: drop.orderId, engineerId: drop.engineerId } : null}
              detailed={expanded}
            />
          </div>
        </section>
      )}
      {showGantt && showTable && (
        <SplitHandle container={layout} share={share} onShare={setShare} onReset={resetShare} label="Размер расписания и таблицы" />
      )}
      {showTable && (
        <section className="sched-table">
          <div className="sched-head">
            <h2>Маршруты</h2>
            {!showGantt && <ExpandControls expanded={expanded} view={view} onView={setView} onToggle={() => setExpanded(!expanded)} />}
            {props.selectedEngineer && (
              <button type="button" className="ghost small" onClick={() => props.onSelectEngineer(null)}>
                Все инженеры
              </button>
            )}
          </div>
          <div className="sched-scroll">
            <RouteTable
              scenario={scenario}
              plan={plan}
              selectedOrder={props.selectedOrder}
              selectedEngineer={props.selectedEngineer}
              changed={previewing ? noChanges : props.changed}
              onSelectOrder={props.onSelectOrder}
              onGoToOrder={props.onGoToOrder}
              onSelectEngineer={props.onSelectEngineer}
            />
          </div>
        </section>
      )}
    </div>
  )
}

function scheduleRows(expanded: boolean, view: ScheduleView, share: number): string {
  if (expanded && view !== 'both') {
    return 'minmax(0, 1fr)'
  }
  return `minmax(0, ${share}fr) 10px minmax(0, ${1 - share}fr)`
}

interface ExpandControlsProps {
  expanded: boolean
  view: ScheduleView
  onView: (view: ScheduleView) => void
  onToggle: () => void
}

function ExpandControls({
  expanded,
  view,
  onView,
  onToggle,
}: ExpandControlsProps) {
  return (
    <div className="expand-controls">
      {expanded && (
        <div className="seg" role="tablist" aria-label="Что показывать">
          {SCHEDULE_VIEWS.map(([key, label]) => (
            <button key={key} type="button" role="tab" aria-selected={view === key} className={view === key ? 'on' : ''} onClick={() => onView(key)}>
              {label}
            </button>
          ))}
        </div>
      )}
      <button type="button" className="ghost small" onClick={onToggle} aria-pressed={expanded}>
        {expanded ? 'Свернуть' : 'Развернуть'}
      </button>
    </div>
  )
}
