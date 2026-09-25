import { useState } from 'react'

import { api, isMissing } from '../api'
import { estimateCandidates } from '../candidates'
import { plural, signed } from '../labels'
import type { Candidate, Plan, Scenario } from '../types'
import { Gantt } from './Gantt'
import type { AssignResult } from './JobPanel'
import { RouteTable } from './RouteTable'

interface Props {
  scenario: Scenario
  plan: Plan
  now: number | null
  nowLabel: string
  selectedOrder: string | null
  selectedEngineer: string | null
  changed: Set<string>
  unavailable: Set<string>
  busy: boolean
  onSelectOrder: (id: string) => void
  onSelectEngineer: (id: string | null) => void
  onAssign: (orderId: string, engineerId: string | null, position: number | 'best') => Promise<AssignResult>
}

type Drop =
  | { orderId: string; engineerId: string; state: 'loading' }
  | { orderId: string; engineerId: string; state: 'ready'; row: Candidate & { estimated?: true } }
  | { orderId: string; engineerId: string; state: 'error'; text: string }
  | { orderId: string; engineerId: string; state: 'done'; text: string }

export function Schedule(props: Props) {
  const { scenario, plan, busy, onAssign } = props
  const [drop, setDrop] = useState<Drop | null>(null)
  const [pending, setPending] = useState(false)
  const name = (id: string) => scenario.engineers.find((e) => e.id === id)?.name ?? id

  async function onDropVisit(orderId: string, engineerId: string) {
    setDrop({ orderId, engineerId, state: 'loading' })
    let rows: (Candidate & { estimated?: true })[]
    try {
      rows = await api.candidates(plan.id, orderId)
    } catch (e) {
      if (!isMissing(e)) {
        setDrop({ orderId, engineerId, state: 'error', text: (e as Error).message })
        return
      }
      rows = estimateCandidates(plan, scenario, orderId)
    }
    const row = rows.find((r) => r.engineer_id === engineerId)
    if (!row) setDrop({ orderId, engineerId, state: 'error', text: `${name(engineerId)} нет в списке кандидатов.` })
    else setDrop({ orderId, engineerId, state: 'ready', row })
  }

  async function confirm(row: Candidate) {
    if (!drop) return
    setPending(true)
    const outcome = await onAssign(drop.orderId, row.engineer_id, row.position ?? 'best')
    setPending(false)
    setDrop(outcome.ok ? { ...drop, state: 'done', text: outcome.text } : { ...drop, state: 'error', text: outcome.text })
  }

  return (
    <div className="schedule">
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
            <span>
              <i className="sw now" /> {props.nowLabel}
            </span>
          </div>
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
                  {drop.row.estimated ? '≈ ' : ''}
                  {signed(drop.row.total_delta_km ?? drop.row.added_km ?? 0)} км
                  {drop.row.arrival && `, приедет ${drop.row.arrival}`}
                  {!drop.row.estimated &&
                    `, ${drop.row.shifted.length ? `сдвинет ${drop.row.shifted.length} ${plural(drop.row.shifted.length, 'визит', 'визита', 'визитов')}` : 'без сдвигов'}`}
                </span>
                <button type="button" className="primary small" disabled={busy || pending} onClick={() => confirm(drop.row)}>
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
            dropTarget={drop && drop.state !== 'done' ? { orderId: drop.orderId, engineerId: drop.engineerId } : null}
          />
        </div>
      </section>
      <section className="sched-table">
        <div className="sched-head">
          <h2>Кто, куда и когда</h2>
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
            changed={props.changed}
            onSelectOrder={props.onSelectOrder}
            onSelectEngineer={props.onSelectEngineer}
          />
        </div>
      </section>
    </div>
  )
}
