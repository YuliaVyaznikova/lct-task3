import { engineerColor, hhmm, minutes } from '../colors'
import type { Plan, Scenario } from '../types'
import { SKILL_COLOR } from '../types'

interface Props {
  scenario: Scenario
  plan: Plan
  selectedOrder: string | null
  selectedEngineer: string | null
  onSelectOrder: (orderId: string) => void
  onSelectEngineer: (engineerId: string | null) => void
}

/** Диаграмма занятости инженеров: работа, дорога и ожидание по часам. */
export function Timeline({
  scenario,
  plan,
  selectedOrder,
  selectedEngineer,
  onSelectOrder,
  onSelectEngineer,
}: Props) {
  const engineerIds = scenario.engineers.map((e) => e.id)
  const ordersById = Object.fromEntries(scenario.orders.map((o) => [o.id, o]))

  const from = Math.min(...scenario.engineers.map((e) => minutes(e.shift_start)), 9 * 60)
  const to = Math.max(...scenario.engineers.map((e) => minutes(e.shift_end)), 23 * 60)
  const span = Math.max(to - from, 60)
  const percent = (value: number) => ((value - from) / span) * 100

  const eventAt = plan.event ? minutes(plan.event.time) : null
  const hours: number[] = []
  for (let h = Math.ceil(from / 60); h <= Math.floor(to / 60); h += 2) hours.push(h)

  return (
    <div className="timeline">
      {scenario.engineers.map((engineer) => {
        const route = plan.routes.find((r) => r.engineer_id === engineer.id)
        const color = engineerColor(engineerIds, engineer.id)
        const dimmed = selectedEngineer !== null && selectedEngineer !== engineer.id
        return (
          <div
            className="tl-row"
            key={engineer.id}
            style={{ opacity: dimmed ? 0.35 : 1 }}
            title={`${engineer.name}, смена ${engineer.shift_start}–${engineer.shift_end}`}
          >
            <div
              className="tl-name"
              style={{ cursor: 'pointer', color: route?.stops.length ? color : undefined }}
              onClick={() =>
                onSelectEngineer(selectedEngineer === engineer.id ? null : engineer.id)
              }
            >
              {engineer.name.replace('Инженер ', '№')}
            </div>
            <div className="tl-track">
              {/* смена как светлая подложка */}
              <div
                className="tl-bar"
                style={{
                  left: `${percent(minutes(engineer.shift_start))}%`,
                  width: `${((minutes(engineer.shift_end) - minutes(engineer.shift_start)) / span) * 100}%`,
                  background: '#e6e9ee',
                }}
              />
              {route?.stops.map((stop) => {
                const order = ordersById[stop.order_id]
                const arrival = minutes(stop.arrival)
                const start = minutes(stop.start)
                const finish = minutes(stop.finish)
                return (
                  <span key={stop.order_id}>
                    <div
                      className="tl-bar travel"
                      style={{
                        left: `${percent(arrival - stop.travel_min)}%`,
                        width: `${(stop.travel_min / span) * 100}%`,
                      }}
                    />
                    {stop.wait_min > 0 && (
                      <div
                        className="tl-bar wait"
                        style={{
                          left: `${percent(arrival)}%`,
                          width: `${(stop.wait_min / span) * 100}%`,
                        }}
                      />
                    )}
                    <div
                      className={`tl-bar work${stop.locked ? ' locked' : ''}`}
                      style={{
                        left: `${percent(start)}%`,
                        width: `${Math.max((finish - start) / span, 0.004) * 100}%`,
                        background: order ? SKILL_COLOR[order.skill] : color,
                        outline: selectedOrder === stop.order_id ? '2px solid #1d2430' : undefined,
                      }}
                      onClick={() => onSelectOrder(stop.order_id)}
                      title={`${stop.order_id} · ${stop.start}–${stop.finish}${
                        stop.locked ? ' · выполнено до события' : ''
                      }`}
                    />
                  </span>
                )
              })}
              {eventAt !== null && (
                <div className="tl-now" style={{ left: `${percent(eventAt)}%` }} />
              )}
            </div>
          </div>
        )
      })}
      <div className="tl-axis">
        {hours.map((h) => (
          <span key={h}>{hhmm(h * 60)}</span>
        ))}
      </div>
    </div>
  )
}
