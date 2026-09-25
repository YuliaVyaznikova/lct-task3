import { Fragment } from 'react'

import { engineerColor, formatMinutes } from '../colors'
import { km } from '../labels'
import type { Plan, Scenario } from '../types'
import { TRANSPORT_RU } from '../types'
import { EmptyNote } from './common'

export function RouteTable({
  scenario,
  plan,
  selectedOrder,
  selectedEngineer,
  changed,
  onSelectOrder,
  onSelectEngineer,
}: {
  scenario: Scenario
  plan: Plan
  selectedOrder: string | null
  selectedEngineer: string | null
  changed: Set<string>
  onSelectOrder: (id: string) => void
  onSelectEngineer: (id: string | null) => void
}) {
  const ids = scenario.engineers.map((e) => e.id)
  const orders = Object.fromEntries(scenario.orders.map((o) => [o.id, o]))
  const routes = scenario.engineers
    .map((engineer) => ({ engineer, route: plan.routes.find((r) => r.engineer_id === engineer.id) }))
    .filter(({ route }) => route && route.stops.length)
    .filter(({ engineer }) => selectedEngineer === null || engineer.id === selectedEngineer)

  if (!routes.length) {
    return (
      <EmptyNote>
        {selectedEngineer ? 'У выбранного инженера в этом плане нет визитов.' : 'Маршрутов нет.'}
      </EmptyNote>
    )
  }

  return (
    <div className="table-scroll">
      <table className="table route-table">
        <thead>
          <tr>
            <th className="num">№</th>
            <th>Заявка</th>
            <th>Адрес</th>
            <th className="num">Окно клиента</th>
            <th className="num">Прибытие</th>
            <th className="num">Начало работ</th>
            <th className="num">Окончание</th>
            <th className="num">Переезд</th>
            <th>Отметки</th>
          </tr>
        </thead>
        <tbody>
          {routes.map(({ engineer, route }) => (
            <Fragment key={engineer.id}>
              <tr className="group-row">
                <td colSpan={9}>
                  <button
                    type="button"
                    className="group-head"
                    onClick={() => onSelectEngineer(selectedEngineer === engineer.id ? null : engineer.id)}
                    style={{ borderLeftColor: engineerColor(ids, engineer.id) }}
                  >
                    <b>{engineer.name}</b>
                    <span className="muted">
                      {TRANSPORT_RU[engineer.transport]}, смена {engineer.shift_start}–{engineer.shift_end}
                    </span>
                    <span className="group-stats">
                      {route!.stops.length} визитов, {km(route!.distance_km)} км,{' '}
                      {formatMinutes(route!.travel_min)} в пути, до {route!.end_time}
                    </span>
                  </button>
                </td>
              </tr>
              {route!.stops.map((stop, index) => {
                const order = orders[stop.order_id]
                return (
                  <tr
                    key={stop.order_id}
                    className={`clickable ${selectedOrder === stop.order_id ? 'selected' : ''} ${
                      stop.locked ? 'locked' : ''
                    }`}
                    onClick={() => onSelectOrder(stop.order_id)}
                  >
                    <td className="num mono">{index + 1}</td>
                    <td className="mono strong">
                      {stop.order_id}
                      {order?.priority === 'urgent' && <span className="badge urgent">срочная</span>}
                    </td>
                    <td className="addr">
                      {order?.district && <span className="muted">{order.district}, </span>}
                      {order?.address}
                    </td>
                    <td className="num mono">
                      {order ? `${order.window_start}–${order.window_end}` : ''}
                    </td>
                    <td className="num mono">
                      {stop.arrival}
                      {stop.wait_min > 0 && <div className="small muted">ждёт {stop.wait_min} мин</div>}
                    </td>
                    <td className="num mono strong">{stop.start}</td>
                    <td className="num mono">{stop.finish}</td>
                    <td className="num mono muted">
                      {km(stop.travel_km)} км
                      <div className="small">{formatMinutes(stop.travel_min)}</div>
                    </td>
                    <td className="marks">
                      {stop.locked && <span className="badge frozen">зафиксирован</span>}
                      {changed.has(stop.order_id) && <span className="badge changed">изменён событием</span>}
                      {stop.late_min > 0 && (
                        <span className="badge urgent" title="Обещанное время сдвинуто — предупредить клиента">
                          позже окна на {stop.late_min} мин
                        </span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  )
}
