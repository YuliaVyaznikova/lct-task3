import { engineerColor } from '../colors'
import { km } from '../labels'
import { STATUS_RU, type EngineerState } from '../sim'
import type { Order, Plan, Scenario } from '../types'
import { TRANSPORT_RU } from '../types'
import { LockIcon } from './common'

interface Props {
  scenario: Scenario
  plan: Plan | null
  liveRoutes?: Record<string, string[]> | null
  selected: string | null
  selectedOrder: string | null
  onSelect: (id: string | null) => void
  onSelectOrder: (id: string) => void
  simStates?: Record<string, EngineerState> | null
  unavailable?: Set<string>
}

export function EngineerList({
  scenario,
  plan,
  liveRoutes,
  selected,
  selectedOrder,
  onSelect,
  onSelectOrder,
  simStates,
  unavailable,
}: Props) {
  const ids = scenario.engineers.map((e) => e.id)
  const orders = Object.fromEntries(scenario.orders.map((o) => [o.id, o])) as Record<string, Order>
  const visitsOf = (id: string) =>
    liveRoutes ? liveRoutes[id]?.length ?? 0 : plan?.routes.find((r) => r.engineer_id === id)?.stops.length ?? 0
  const used = scenario.engineers.filter((e) => visitsOf(e.id) > 0).length
  const list = [...scenario.engineers].sort(
    (a, b) => Number(unavailable?.has(a.id) ?? false) - Number(unavailable?.has(b.id) ?? false),
  )

  return (
    <div className="panel engineers">
      <div className="panel-head">
        <h2>
          Инженеры <span className="muted">{plan || liveRoutes ? `${used} из ${ids.length}` : ids.length}</span>
        </h2>
      </div>
      <ul className="panel-scroll eng-list">
        {list.map((engineer) => {
          const route = plan?.routes.find((r) => r.engineer_id === engineer.id)
          const visits = visitsOf(engineer.id)
          const load = plan && !liveRoutes ? plan.metrics.utilization_by_engineer[engineer.id] ?? 0 : null
          const frozen = route?.stops.some((s) => s.locked) ?? false
          const off = unavailable?.has(engineer.id) ?? false
          const state = simStates?.[engineer.id]
          const isSelected = selected === engineer.id
          const color = engineerColor(ids, engineer.id)
          return (
            <li key={engineer.id} className={`eng ${isSelected ? 'selected' : ''} ${off ? 'off' : ''} ${visits ? '' : 'idle'}`}>
              <button type="button" className="eng-row" onClick={() => onSelect(isSelected ? null : engineer.id)} aria-expanded={isSelected}>
                <i className="eng-dot" style={{ background: visits || state ? color : 'transparent', borderColor: color }} />
                <span className="eng-main">
                  <span className="eng-name">
                    {engineer.name}
                    {frozen && <LockIcon title="Есть зафиксированные визиты" />}
                  </span>
                  <span className="eng-sub">
                    {state ? (
                      <span className={`status s-${state.status}`}>{STATUS_RU[state.status]}</span>
                    ) : off ? (
                      'недоступен'
                    ) : (
                      TRANSPORT_RU[engineer.transport]
                    )}
                  </span>
                </span>
                <span className="eng-load">
                  {load !== null ? (
                    <span className="load-bar" title={`Загрузка смены ${Math.round(load * 100)}%`}>
                      <i style={{ width: `${Math.min(100, Math.round(load * 100))}%`, background: color }} />
                    </span>
                  ) : (
                    <span className="load-bar empty" />
                  )}
                  <span className="eng-shift">
                    {engineer.shift_start}–{engineer.shift_end}
                  </span>
                </span>
                <span className="eng-visits" title={state ? 'выполнено из запланированных' : 'визитов'}>
                  {state ? `${state.done}/${state.total}` : visits || 0}
                </span>
              </button>
              {isSelected && route && route.stops.length > 0 && (
                <div className="eng-detail">
                  <div className="eng-facts">
                    {km(route.distance_km)} км · в пути {route.travel_min} мин · до {route.end_time}
                    {route.break && ` · обед ${route.break.start}–${route.break.finish}`}
                  </div>
                  <ol className="stops">
                    {route.stops.map((stop, i) => (
                      <li key={stop.order_id}>
                        <button
                          type="button"
                          className={`stop ${stop.locked ? 'locked' : ''} ${selectedOrder === stop.order_id ? 'selected' : ''}`}
                          onClick={() => onSelectOrder(stop.order_id)}
                        >
                          <span className="stop-n" style={{ borderColor: color }}>
                            {i + 1}
                          </span>
                          <span className="stop-t">{stop.start}</span>
                          <span className="stop-id">{stop.order_id}</span>
                          <span className="stop-where">{orders[stop.order_id]?.district}</span>
                          {stop.locked && <LockIcon title="Зафиксирован" />}
                          {stop.late_min > 0 && <span className="late">+{stop.late_min}</span>}
                        </button>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
