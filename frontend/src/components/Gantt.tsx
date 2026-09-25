import { useState } from 'react'

import { engineerColor, hhmm, minutes } from '../colors'
import type { Plan, Scenario } from '../types'
import { LockIcon } from './common'

interface Props {
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
  dropTarget: { orderId: string; engineerId: string } | null
}

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
  dropTarget,
}: Props) {
  const [dragging, setDragging] = useState<{ orderId: string; from: string } | null>(null)
  const [over, setOver] = useState<string | null>(null)
  const ids = scenario.engineers.map((e) => e.id)

  const finishes = plan.routes.flatMap((r) => r.stops.map((s) => minutes(s.finish)))
  const from = Math.floor(Math.min(...scenario.engineers.map((e) => minutes(e.shift_start)), 9 * 60) / 60) * 60
  const to = Math.ceil(Math.max(...scenario.engineers.map((e) => minutes(e.shift_end)), ...finishes, 18 * 60) / 60) * 60
  const span = Math.max(to - from, 60)
  const pct = (value: number) => ((value - from) / span) * 100
  const hours: number[] = []
  for (let h = from / 60; h <= to / 60; h += 1) hours.push(h)
  const orders = Object.fromEntries(scenario.orders.map((o) => [o.id, o]))

  return (
    <div className={`gantt ${dragging ? 'dragging' : ''}`}>
      <div className="g-axis">
        <div className="g-name" />
        <div className="g-track">
          {hours.map((h) => (
            <span key={h} className="g-hour" style={{ left: `${pct(h * 60)}%` }}>
              {hhmm(h * 60)}
            </span>
          ))}
          {now !== null && now >= from && now <= to && (
            <span className="g-now-label" style={{ left: `${pct(now)}%` }}>
              {nowLabel}
            </span>
          )}
        </div>
      </div>
      {scenario.engineers.map((engineer) => {
        const route = plan.routes.find((r) => r.engineer_id === engineer.id)
        const color = engineerColor(ids, engineer.id)
        const dim = selectedEngineer !== null && selectedEngineer !== engineer.id
        const isOver = over === engineer.id && dragging && dragging.from !== engineer.id
        const isTarget = dropTarget?.engineerId === engineer.id
        return (
          <div
            key={engineer.id}
            className={`g-row ${dim ? 'dim' : ''} ${isOver ? 'over' : ''} ${isTarget ? 'target' : ''} ${unavailable.has(engineer.id) ? 'off' : ''}`}
            onDragOver={(e) => {
              if (!dragging) return
              e.preventDefault()
              setOver(engineer.id)
            }}
            onDragLeave={() => setOver((v) => (v === engineer.id ? null : v))}
            onDrop={(e) => {
              e.preventDefault()
              const orderId = e.dataTransfer.getData('text/plain') || dragging?.orderId
              setOver(null)
              setDragging(null)
              if (orderId && dragging?.from !== engineer.id) onDropVisit(orderId, engineer.id)
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
                  обед
                </div>
              )}
              {route?.stops.map((stop, i) => {
                const arrival = minutes(stop.arrival)
                const depart = stop.departure ? minutes(stop.departure) : arrival - stop.travel_min
                const start = minutes(stop.start)
                const finish = minutes(stop.finish)
                const order = orders[stop.order_id]
                const cls = [
                  'g-work',
                  stop.locked ? 'locked' : '',
                  changed.has(stop.order_id) ? 'changed' : '',
                  selectedOrder === stop.order_id ? 'selected' : '',
                  stop.late_min > 0 ? 'late' : '',
                  order?.priority === 'urgent' ? 'urgent' : '',
                ].join(' ')
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
                      draggable={!stop.locked}
                      onDragStart={(e) => {
                        e.dataTransfer.setData('text/plain', stop.order_id)
                        e.dataTransfer.effectAllowed = 'move'
                        setDragging({ orderId: stop.order_id, from: engineer.id })
                      }}
                      onDragEnd={() => {
                        setDragging(null)
                        setOver(null)
                      }}
                      onClick={() => onSelectOrder(stop.order_id)}
                      onKeyDown={(e) => e.key === 'Enter' && onSelectOrder(stop.order_id)}
                      style={{
                        left: `${pct(start)}%`,
                        width: `${Math.max((finish - start) / span, 0.006) * 100}%`,
                        ['--c' as string]: color,
                      }}
                      title={`${stop.order_id} · визит ${i + 1} · ${stop.start}–${stop.finish}${stop.locked ? ' · зафиксирован' : ''}${
                        stop.late_min > 0 ? ` · позже окна на ${stop.late_min} мин` : ''
                      }`}
                    >
                      {stop.locked ? <LockIcon /> : <span className="g-n">{i + 1}</span>}
                    </div>
                  </span>
                )
              })}
              {now !== null && <div className="g-now" style={{ left: `${pct(now)}%` }} />}
            </div>
          </div>
        )
      })}
    </div>
  )
}
