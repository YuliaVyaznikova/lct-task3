import { useEffect, useState } from 'react'

import { api } from '../api'
import { engineerColor, minutes } from '../colors'
import type { VisitChange } from '../derive'
import { stopsByOrder } from '../derive'
import { effectiveTier, humanizeCodes, plural, REASON_IS_RULE, reasonLabel, shortReason, signed, TIER_LABEL } from '../labels'
import type { Candidate, NearestWindow, OrderExplanation, Plan, ReasonCode, Scenario } from '../types'
import { SKILL_RU, TRANSPORT_RU } from '../types'
import { Disclosure, EngineerName, LockIcon } from './common'
import type { CandidatePreview } from './MapView'
import { useJobCandidates, type AssignResult } from './useJobCandidates'

export type { AssignResult } from './useJobCandidates'

interface Props {
  plan: Plan
  scenario: Scenario
  orderId: string
  change: VisitChange | null
  busy: boolean
  onClose: () => void
  onSelectEngineer: (id: string) => void
  onPreview: (preview: CandidatePreview | null) => void
  onAssign: (orderId: string, engineerId: string | null, position: number | 'best') => Promise<AssignResult>
}

export function JobPanel({ plan, scenario, orderId, change, busy, onClose, onSelectEngineer, onPreview, onAssign }: Props) {
  const order = scenario.orders.find((o) => o.id === orderId)
  const ref = stopsByOrder(plan)[orderId]
  const unassigned = plan.unassigned.find((u) => u.order_id === orderId)
  const locked = ref?.stop.locked ?? false
  const ids = scenario.engineers.map((e) => e.id)
  const { rows, setHover, picked, setPicked, pending, result, rowError, list, active, feasible, blocked, estimated, assign } = useJobCandidates({
    plan,
    scenario,
    orderId,
    enabled: Boolean(order && (ref || unassigned)),
    locked,
    assignedEngineerId: ref?.engineerId,
    onPreview,
    onAssign,
  })

  const [nearest, setNearest] = useState<NearestWindow | null>(null)
  const hasReason = Boolean(unassigned)
  useEffect(() => {
    setNearest(null)
    if (!hasReason) return
    const controller = new AbortController()
    api
      .nearest(plan.id, orderId, controller.signal)
      .then(setNearest)
      .catch(() => setNearest(null))
    return () => controller.abort()
  }, [plan.id, orderId, hasReason])

  if (!order) {
    return (
      <div className="panel job">
        <div className="panel-head">
          <h2>{orderId}</h2>
          <button type="button" className="icon" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </div>
        <p className="pad muted">Этой заявки нет в текущем плане.</p>
      </div>
    )
  }

  const tier = effectiveTier(order)
  const card = plan.explanations[orderId] as OrderExplanation | undefined
  const name = (id: string) => scenario.engineers.find((e) => e.id === id)?.name ?? id

  return (
    <div className="panel job" aria-label={`Заявка ${order.id}`}>
      <div className="panel-head">
        <h2 className="job-title">
          Заявка {order.id}
          {order.priority === 'urgent' && <span className="tag urgent">срочная</span>}
        </h2>
        <button type="button" className="icon" onClick={onClose} aria-label="Закрыть заявку">
          ×
        </button>
      </div>
      <div className="panel-scroll">
        <div className="job-facts">
          <div className="fact">
            <PinGlyph />
            <span>
              {order.address}
              {order.district && <span className="muted"> · {order.district}</span>}
            </span>
          </div>
          <div className="fact-grid">
            <span className="fact">
              <ClockGlyph />
              <b>
                {order.window_start}–{order.window_end}
              </b>
            </span>
            <span className="fact">
              <ToolGlyph />
              {SKILL_RU[order.skill].toLowerCase()}, {order.duration_min} мин
            </span>
          </div>
          <div className="fact-line muted">
            {TIER_LABEL[tier]}
            {order.work_type && ` · ${order.work_type}`}
            {order.required_transport && ` · нужен ${TRANSPORT_RU[order.required_transport]}`}
          </div>
        </div>

        {change && (
          <div className="note info">
            Событие: {name(change.before.engineerId)}, визит {change.before.position}, {change.before.stop.start} →{' '}
            {name(change.after.engineerId)}, визит {change.after.position}, {change.after.stop.start}
          </div>
        )}

        {ref && (
          <div className={`status-block ${locked ? 'frozen' : 'ok'}`}>
            <div className="status-main">
              <EngineerName engineers={scenario.engineers} id={ref.engineerId} onClick={onSelectEngineer} />
              <span className="muted">
                визит {ref.position} из {ref.total}
              </span>
              {locked && (
                <span className="tag frozen">
                  <LockIcon /> зафиксирован
                </span>
              )}
            </div>
            <div className="status-times">
              приедет <b>{ref.stop.arrival}</b>
              {ref.stop.wait_min > 0 && <>, ждёт {ref.stop.wait_min} мин</>}, начало <b>{ref.stop.start}</b>, конец{' '}
              <b>{ref.stop.finish}</b>
              {ref.stop.late_min > 0 && <span className="warn-text"> · позже окна на {ref.stop.late_min} мин</span>}
            </div>
            {card && (
              <Disclosure title="Проверки" className="compact">
                <ul className="checks">
                  {card.checks.map((check, i) => (
                    <li key={i} className={check.ok ? 'ok' : 'bad'}>
                      {check.text}
                    </li>
                  ))}
                </ul>
                {card.travel && <p className="small">{card.travel}</p>}
              </Disclosure>
            )}
          </div>
        )}

        {unassigned && (
          <div className={`status-block ${REASON_IS_RULE[unassigned.reason_code as ReasonCode] ? 'bad' : 'warn'}`}>
            <div className="status-main">
              <b>{reasonLabel(unassigned.reason_code)}</b>
            </div>
            <div className="status-times">{shortReason(unassigned.reason_code, order, scenario.engineers)}</div>
            {nearest && <div className={`nearest ${nearest.available ? 'found' : ''}`}>{nearest.text}</div>}
            <Disclosure title="Текст сервиса" className="compact">
              <p className="small diag">{humanizeCodes(unassigned.reason)}</p>
            </Disclosure>
          </div>
        )}

        {!ref && !unassigned && <p className="pad muted">Заявка не участвует в плане.</p>}

        {result && (
          <div className={`note ${result.ok ? 'good' : 'bad'}`} role="status">
            {result.text}
          </div>
        )}

        {!locked && (ref || unassigned) && (
          <section className="cands">
            <div className="cands-head">
              <h3>{ref ? 'Кому можно отдать' : 'Кому можно назначить'}</h3>
              {rows.state === 'ready' && (
                <span className="muted small">
                  {feasible.length} из {list.length}
                </span>
              )}
            </div>
            {rows.state === 'loading' && (
              <div className="cands-loading">
                <span className="spinner" /> проверяем инженеров…
              </div>
            )}
            {rows.state === 'error' && <div className="note bad">{rows.text}</div>}
            {rows.state === 'ready' && (
              <ul className="cand-list" onMouseLeave={() => setHover(null)}>
                {feasible.map((row) => {
                  const isActive = active?.engineer_id === row.engineer_id
                  const isPicked = picked === row.engineer_id
                  const delta = row.total_delta_km ?? row.added_km ?? 0
                  const err = rowError?.id === row.engineer_id ? rowError.text : null
                  return (
                    <li
                      key={row.engineer_id}
                      className={`cand ok ${isActive ? 'active' : ''} ${isPicked ? 'picked' : ''}`}
                      onMouseEnter={() => setHover(row.engineer_id)}
                    >
                      <button
                        type="button"
                        className="cand-main"
                        aria-pressed={isPicked}
                        onClick={() => setPicked(isPicked ? null : row.engineer_id)}
                        onFocus={() => setHover(row.engineer_id)}
                      >
                        <i className="dot" style={{ background: engineerColor(ids, row.engineer_id) }} />
                        <span className="cand-text">
                          <span className="cand-name">{name(row.engineer_id)}</span>
                          <span className="cand-sub">
                            <b className={delta <= 0 ? 'good-text' : ''}>
                              {row.estimated ? '≈ ' : ''}
                              {signed(delta)} км
                            </b>
                            {row.arrival && <>, приедет {row.arrival}</>}
                            {!row.estimated && (
                              <>
                                ,{' '}
                                {row.shifted.length
                                  ? `сдвинет ${row.shifted.length} ${plural(row.shifted.length, 'визит', 'визита', 'визитов')}`
                                  : 'без сдвигов'}
                              </>
                            )}
                          </span>
                        </span>
                      </button>
                      <button
                        type="button"
                        className="primary give"
                        disabled={busy || pending !== null}
                        onClick={() => assign(row)}
                      >
                        {pending === row.engineer_id ? '…' : ref ? 'Отдать' : 'Назначить'}
                      </button>
                      {err && <div className="cand-error">{err}</div>}
                    </li>
                  )
                })}
                {blocked.map((row) => (
                  <li key={row.engineer_id} className="cand no" title={row.reason ?? undefined}>
                    <span className="cand-main static">
                      <i className="dot" style={{ background: engineerColor(ids, row.engineer_id) }} />
                      <span className="cand-name">{name(row.engineer_id)}</span>
                      <span className="cand-reason">{shortCandidateReason(row)}</span>
                    </span>
                    <span className="cand-dash">—</span>
                  </li>
                ))}
              </ul>
            )}
            {estimated && (
              <p className="small muted cands-foot">≈ — оценка по прямой; окно и смену сервис проверит при переносе.</p>
            )}
            {ref && (
              <button type="button" className="ghost small unassign" disabled={busy || pending !== null} onClick={() => assign(null)}>
                Снять с маршрута
              </button>
            )}
          </section>
        )}
      </div>
      {active && active.feasible && (
        <div className="cand-dock" aria-live="polite">
          <div className="dock-head">
            <i className="dot" style={{ background: engineerColor(ids, active.engineer_id) }} />
            <b>{name(active.engineer_id)}</b>
            <span className="muted">
              {active.position !== null && `визит ${active.position + 1}`}
              {active.arrival && `, приедет ${active.arrival}`}
              {active.start && active.start !== active.arrival && `, начнёт ${active.start}`}
            </span>
          </div>
          {active.estimated ? (
            <div className="dock-note muted">≈ {signed(active.total_delta_km ?? 0)} км по прямой</div>
          ) : active.shifted.length ? (
            <ul className="shifted">
              {active.shifted.map((s) => {
                const d = minutes(s.to_start) - minutes(s.from_start)
                return (
                  <li key={s.order_id}>
                    <span>{s.order_id}</span>
                    <span>
                      {s.from_start} → <b>{s.to_start}</b>
                    </span>
                    <span className={d > 0 ? 'warn-text' : 'good-text'}>
                      {d > 0 ? '+' : '−'}
                      {Math.abs(d)} мин
                    </span>
                  </li>
                )
              })}
            </ul>
          ) : (
            <div className="dock-note muted">Остальные визиты не сдвигаются.</div>
          )}
        </div>
      )}
    </div>
  )
}

function shortCandidateReason(row: Candidate): string {
  const byCode: Record<string, string> = {
    NO_SKILL: 'нет навыка',
    NO_TRANSPORT: 'не тот транспорт',
    NO_EQUIPMENT: 'не хватит оборудования',
    SHIFT_MISMATCH: 'не хватит смены',
    SHIFT_END: 'закончится смена',
    UNREACHABLE: 'не успеет к окну',
    WINDOW: 'не успеет к окну',
    LATE: 'не успеет к окну',
    CAPACITY: 'не помещается в маршрут',
    NO_COORDS: 'нет координат',
    ENGINEER_UNAVAILABLE: 'недоступен',
    LOCKED: 'маршрут зафиксирован',
  }
  if (row.reason_code && byCode[row.reason_code]) return byCode[row.reason_code]
  if (row.reason) {
    const text = humanizeCodes(row.reason)
    return text.length > 48 ? text.slice(0, 46).trimEnd() + '…' : text
  }
  return 'не подходит'
}

function PinGlyph() {
  return (
    <svg className="glyph" viewBox="0 0 16 16" aria-hidden>
      <path d="M8 1.5a4.5 4.5 0 0 0-4.5 4.5c0 3.4 4.5 8.5 4.5 8.5s4.5-5.1 4.5-8.5A4.5 4.5 0 0 0 8 1.5Z" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <circle cx="8" cy="6" r="1.6" fill="currentColor" />
    </svg>
  )
}
function ClockGlyph() {
  return (
    <svg className="glyph" viewBox="0 0 16 16" aria-hidden>
      <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path d="M8 4.5V8l2.5 1.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  )
}
function ToolGlyph() {
  return (
    <svg className="glyph" viewBox="0 0 16 16" aria-hidden>
      <path d="M10.5 2a3.5 3.5 0 0 0-3.2 4.9L2.5 11.7a1.3 1.3 0 0 0 1.8 1.8l4.8-4.8A3.5 3.5 0 0 0 14 5.5l-2 .5-1.5-1.5.5-2a3.6 3.6 0 0 0-.5 0Z" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  )
}
