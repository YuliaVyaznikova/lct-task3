import { useState } from 'react'

import { cx } from '../classes'
import { useEngineerColor } from '../colors'
import { displayAddress, ordersById } from '../derive'
import { departureMin, hhmm, minutes } from '../time'
import { startPlaces, type StartPlace } from '../geo'
import type { Candidate, Engineer, Plan, Scenario } from '../types'
import { LockIcon } from './common'
import { PLACE_TITLE, PlaceMark } from './PlaceCard'
import { canTake, takeReason } from './useJobCandidates'

export interface Ghost {
  engineerId: string
  orderId: string
  start: string
  finish: string
  kind: 'moved' | 'removed'
  title?: string
}

type Line =
  | { kind: 'place'; place: StartPlace; count: number }
  | { kind: 'shift'; key: string; start: string; end: string; count: number }
  | { kind: 'engineer'; engineer: Engineer }

const shiftKey = (engineer: Engineer) => `${engineer.shift_start}–${engineer.shift_end}`

function groupedLines(scenario: Scenario, shown: Engineer[]): Line[] {
  const visible = new Set(shown.map((engineer) => engineer.id))
  return startPlaces(scenario).flatMap((place) => {
    const crew = place.engineers.filter((engineer) => visible.has(engineer.id))
    if (!crew.length) {
      return []
    }
    const shifts = new Map<string, Engineer[]>()
    for (const engineer of [...crew].sort((a, b) => minutes(a.shift_start) - minutes(b.shift_start))) {
      shifts.set(shiftKey(engineer), [...(shifts.get(shiftKey(engineer)) ?? []), engineer])
    }
    const lines: Line[] = [{ kind: 'place', place, count: crew.length }]
    for (const [key, engineers] of shifts) {
      if (shifts.size > 1) {
        lines.push({ kind: 'shift', key: `${place.key}|${key}`, start: engineers[0].shift_start, end: engineers[0].shift_end, count: engineers.length })
      }
      lines.push(...engineers.map((engineer): Line => ({ kind: 'engineer', engineer })))
    }
    return lines
  })
}

interface GanttProps {
  scenario: Scenario
  plan: Plan
  now: number | null
  nowLabel: string
  selectedOrder: string | null
  selectedEngineer: string | null
  changed: Set<string>
  unavailable: Set<string>
  onSelectOrder: (orderId: string) => void
  onSelectEngineer: (engineerId: string | null) => void
  onDropVisit: (orderId: string, engineerId: string) => void
  onCarryVisit: (orderId: string | null) => void
  carried: { orderId: string; rows: Candidate[] } | null
  dropTarget: { orderId: string; engineerId: string } | null
  ghosts?: Ghost[]
  added?: Set<string>
  received?: Set<string>
  rows?: Set<string>
  readOnly?: boolean
  detailed?: boolean
  describe?: (orderId: string) => string | undefined
}

function LunchIcon() {
  return (
    <svg
      className="g-lunch-icon"
      viewBox="0 0 12 12"
      width="11"
      height="11"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M2.5 1.5v3a1 1 0 0 0 2 0v-3" />
      <path d="M3.5 1.5v9" />
      <path d="M8.5 1.5v9" />
      <path d="M8.5 1.5c1.5 0 2 1.2 2 3s-.5 2.5-2 2.5" />
    </svg>
  )
}

const NOW_LABEL_CLEARANCE_MIN = 50

export function Gantt({
  scenario,
  plan,
  now,
  nowLabel,
  selectedOrder,
  selectedEngineer,
  changed,
  unavailable,
  onSelectOrder,
  onSelectEngineer,
  onDropVisit,
  onCarryVisit,
  carried,
  dropTarget,
  ghosts = [],
  added,
  received,
  rows,
  readOnly = false,
  detailed = false,
  describe,
}: GanttProps) {
  const colorOf = useEngineerColor()
  const [dragging, setDragging] = useState<{ orderId: string; from: string } | null>(null)
  const [over, setOver] = useState<string | null>(null)

  const shown = scenario.engineers.filter((engineer) => !rows || rows.has(engineer.id))
  const isShown = (engineerId: string) => shown.some((engineer) => engineer.id === engineerId)
  const finishes = [
    ...plan.routes.filter((r) => isShown(r.engineer_id)).flatMap((r) => r.stops.map((s) => minutes(s.finish))),
    ...ghosts.filter((g) => isShown(g.engineerId)).map((g) => minutes(g.finish)),
  ]
  const from = Math.floor(Math.min(...shown.map((e) => minutes(e.shift_start)), 9 * 60) / 60) * 60
  const to = Math.ceil(Math.max(...shown.map((e) => minutes(e.shift_end)), ...finishes, 18 * 60) / 60) * 60
  const span = Math.max(to - from, 60)
  const pct = (value: number) => ((value - from) / span) * 100
  const nowShown = now !== null && now >= from && now <= to
  const nearNow = (value: number) => nowShown && Math.abs(value - now!) < NOW_LABEL_CLEARANCE_MIN
  const hours: number[] = []
  for (let h = from / 60; h <= to / 60; h += 1) hours.push(h)
  const orders = ordersById(scenario)
  const lines: Line[] = readOnly ? shown.map((engineer) => ({ kind: 'engineer', engineer })) : groupedLines(scenario, shown)

  return (
    <div className={cx('gantt', dragging && 'dragging', detailed && 'detailed')}>
      <div className="g-axis">
        <div className="g-name" />
        <div className="g-track">
          {hours.filter((h) => !nearNow(h * 60)).map((h) => (
            <span key={h} className="g-hour" style={{ left: `${pct(h * 60)}%` }}>
              {hhmm(h * 60)}
            </span>
          ))}
          {nowShown && (
            <span className="g-now-label" style={{ left: `${pct(now)}%` }}>
              {nowLabel}
            </span>
          )}
        </div>
      </div>
      {lines.map((line) => {
        if (line.kind === 'place') {
          return (
            <div key={`place-${line.place.key}`} className="g-group">
              <PlaceMark kind={line.place.kind} />
              <span className="g-group-kind">{PLACE_TITLE[line.place.kind]}</span>
              <span className="g-group-address">{displayAddress(line.place.address)}</span>
              <span className="muted">{line.count}</span>
            </div>
          )
        }
        if (line.kind === 'shift') {
          return (
            <div key={`shift-${line.key}`} className="g-shift-head">
              <span className="g-shift-label">
                Смена {line.start}–{line.end} <span className="muted">{line.count}</span>
              </span>
              <div className="g-track">
                <span
                  className="g-shift-span"
                  style={{ left: `${pct(minutes(line.start))}%`, width: `${((minutes(line.end) - minutes(line.start)) / span) * 100}%` }}
                />
              </div>
            </div>
          )
        }
        const engineer = line.engineer
        const route = plan.routes.find((r) => r.engineer_id === engineer.id)
        const color = colorOf(engineer.id)
        const dim = selectedEngineer !== null && selectedEngineer !== engineer.id
        const isOver = over === engineer.id && dragging && dragging.from !== engineer.id
        const verdictKnown = dragging !== null && carried?.orderId === dragging.orderId && dragging.from !== engineer.id
        const allowed = verdictKnown && canTake(carried.rows, engineer.id)
        const refused = verdictKnown && !allowed
        const isTarget = dropTarget?.engineerId === engineer.id
        return (
          <div
            key={engineer.id}
            className={cx('g-row', dim && 'dim', isOver && 'over', isTarget && 'target', allowed && 'can', refused && 'cannot', unavailable.has(engineer.id) && 'off')}
            title={refused ? (takeReason(carried.rows, engineer.id) ?? 'не подходит') : undefined}
            onDragOver={(e) => {
              if (!dragging) {
                return
              }
              e.preventDefault()
              setOver(engineer.id)
            }}
            onDragLeave={() => setOver((v) => (v === engineer.id ? null : v))}
            onDrop={(e) => {
              e.preventDefault()
              const orderId = e.dataTransfer.getData('text/plain') || dragging?.orderId
              setOver(null)
              setDragging(null)
              onCarryVisit(null)
              if (orderId && dragging?.from !== engineer.id) {
                onDropVisit(orderId, engineer.id)
              }
            }}
          >
            <button
              type="button"
              className={`g-name ${selectedEngineer === engineer.id ? 'on' : ''}`}
              onClick={() => onSelectEngineer(selectedEngineer === engineer.id ? null : engineer.id)}
            >
              <i className="dot" style={{ background: route?.stops.length ? color : 'transparent', borderColor: color }} />
              <span className="g-name-text">{engineer.name}</span>
              <span className="g-count">{route?.stops.length || ''}</span>
            </button>
            <div className="g-track">
              <div
                className="g-shift"
                style={{
                  left: `${pct(minutes(engineer.shift_start))}%`,
                  width: `${((minutes(engineer.shift_end) - minutes(engineer.shift_start)) / span) * 100}%`,
                }}
              />
              {route?.break && (
                <div
                  className="g-lunch"
                  title={`Обед ${route.break.start}–${route.break.finish}`}
                  style={{
                    left: `${pct(minutes(route.break.start))}%`,
                    width: `${((minutes(route.break.finish) - minutes(route.break.start)) / span) * 100}%`,
                  }}
                >
                  <LunchIcon />
                  <span className="g-lunch-label">обед</span>
                </div>
              )}
              {route?.stops.map((stop) => {
                const arrival = minutes(stop.arrival)
                const depart = departureMin(stop)
                const start = minutes(stop.start)
                const finish = minutes(stop.finish)
                const order = orders[stop.order_id]
                const exportNumber = order?.external_id ? ` · выгрузка ${order.external_id}` : ''
                const cls = [
                  'g-work',
                  stop.locked ? 'locked' : '',
                  changed.has(stop.order_id) ? 'changed' : '',
                  selectedOrder === stop.order_id ? 'selected' : '',
                  stop.late_min > 0 ? 'late' : '',
                  order?.priority === 'urgent' ? 'urgent' : '',
                  added?.has(stop.order_id) ? 'added' : '',
                  received?.has(stop.order_id) ? 'received' : '',
                  detailed ? 'detailed' : '',
                ].filter(Boolean).join(' ')
                return (
                  <span key={stop.order_id}>
                    <div
                      className="g-travel"
                      style={{ left: `${pct(depart)}%`, width: `${((arrival - depart) / span) * 100}%` }}
                    />
                    {stop.wait_min > 0 && (
                      <div className="g-wait" style={{ left: `${pct(arrival)}%`, width: `${(stop.wait_min / span) * 100}%` }} />
                    )}
                    <div
                      className={cls}
                      role="button"
                      tabIndex={0}
                      draggable={!stop.locked && !readOnly}
                      onDragStart={(e) => {
                        e.dataTransfer.setData('text/plain', stop.order_id)
                        e.dataTransfer.effectAllowed = 'move'
                        setDragging({ orderId: stop.order_id, from: engineer.id })
                        onCarryVisit(stop.order_id)
                      }}
                      onDragEnd={() => {
                        setDragging(null)
                        setOver(null)
                        onCarryVisit(null)
                      }}
                      onClick={() => onSelectOrder(stop.order_id)}
                      onKeyDown={(e) => e.key === 'Enter' && onSelectOrder(stop.order_id)}
                      style={{
                        left: `${pct(start)}%`,
                        width: `${Math.max((finish - start) / span, 0.006) * 100}%`,
                        ['--c' as string]: color,
                      }}
                      title={describe?.(stop.order_id) ?? `${stop.order_id} · ${stop.start}–${stop.finish}${exportNumber}${stop.locked ? ' · зафиксирован' : ''}${
                        stop.late_min > 0 ? ` · позже окна на ${stop.late_min} мин` : ''
                      }`}
                    >
                      <span className="g-work-content">
                        {stop.locked && <LockIcon />}
                        {received?.has(stop.order_id) && <span aria-hidden>←</span>}
                        <span className="g-order-id">{stop.order_id}</span>
                        {detailed && order && (
                          <span className="g-work-detail">
                            {order.work_type}{order.address && ` · ${displayAddress(order.address)}`}
                          </span>
                        )}
                      </span>
                    </div>
                  </span>
                )
              })}
              {ghosts
                .filter((ghost) => ghost.engineerId === engineer.id)
                .map((ghost) => (
                  <div
                    key={`${ghost.kind}-${ghost.orderId}`}
                    className={`g-ghost ${ghost.kind}`}
                    title={ghost.title ?? `${ghost.orderId} · было ${ghost.start}–${ghost.finish}`}
                    style={{
                      left: `${pct(minutes(ghost.start))}%`,
                      width: `${Math.max((minutes(ghost.finish) - minutes(ghost.start)) / span, 0.006) * 100}%`,
                      ['--c' as string]: color,
                    }}
                  />
                ))}
              {now !== null && <div className="g-now" style={{ left: `${pct(now)}%` }} />}
            </div>
          </div>
        )
      })}
    </div>
  )
}
