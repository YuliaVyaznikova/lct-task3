import { Fragment, useEffect, useRef, useState } from 'react'

import { cx } from '../classes'
import { useEngineerColor } from '../colors'
import { displayAddress, ordersById } from '../derive'
import { km, TRANSPORT_RU } from '../labels'
import { formatMinutes, minutes } from '../time'
import type { Engineer, Order, Plan, Route, Scenario, Stop } from '../types'
import { AddressLink } from './common'

export type SortKey = 'engineer' | 'order' | 'workType' | 'time'
export interface SortState {
  key: SortKey
  descending: boolean
}

interface RouteGroup {
  engineer: Engineer
  route: Route
}

interface IndexedStop {
  stop: Stop
  index: number
}

export interface FlatStop extends IndexedStop {
  engineer: Engineer
}

export function nextSort(current: SortState | null, key: SortKey): SortState | null {
  if (current?.key !== key) {
    return { key, descending: false }
  }
  return current.descending ? null : { key, descending: true }
}

function compareText(a: string, b: string): number {
  return a.localeCompare(b, 'ru')
}

function stopCompare(key: SortKey, orders: Record<string, Order>): (a: IndexedStop, b: IndexedStop) => number {
  if (key === 'workType') {
    return (a, b) => compareText(orders[a.stop.order_id]?.work_type ?? '', orders[b.stop.order_id]?.work_type ?? '')
  }
  if (key === 'time') {
    return (a, b) => minutes(a.stop.start) - minutes(b.stop.start)
  }
  return (a, b) => a.stop.order_id.localeCompare(b.stop.order_id, 'ru', { numeric: true })
}

export function isGrouped(sort: SortState | null): boolean {
  return sort === null || sort.key === 'engineer'
}

export function sortGroups(groups: RouteGroup[], sort: SortState | null) {
  const direction = sort?.descending ? -1 : 1
  const ordered = sort?.key === 'engineer' ? [...groups].sort((a, b) => direction * compareText(a.engineer.name, b.engineer.name)) : groups
  return ordered.map(({ engineer, route }) => ({ engineer, route, stops: route.stops.map((stop, index) => ({ stop, index })) }))
}

export function sortStops(groups: RouteGroup[], sort: SortState, orders: Record<string, Order>): FlatStop[] {
  const direction = sort.descending ? -1 : 1
  const compare = stopCompare(sort.key, orders)
  const all = groups.flatMap(({ engineer, route }) => route.stops.map((stop, index) => ({ engineer, stop, index })))
  return all.sort((a, b) => direction * compare(a, b))
}

interface RouteTableProps {
  scenario: Scenario
  plan: Plan
  selectedOrder: string | null
  selectedEngineer: string | null
  changed: Set<string>
  onSelectOrder: (id: string) => void
  onGoToOrder: (id: string) => void
  onSelectEngineer: (id: string | null) => void
}

export function RouteTable({
  scenario,
  plan,
  selectedOrder,
  selectedEngineer,
  changed,
  onSelectOrder,
  onGoToOrder,
  onSelectEngineer,
}: RouteTableProps) {
  const colorOf = useEngineerColor()
  const table = useRef<HTMLTableElement>(null)
  const [sort, setSort] = useState<SortState | null>(null)
  useEffect(() => {
    if (!selectedOrder) {
      return
    }
    const row = table.current?.querySelector<HTMLElement>(`tr[data-order="${CSS.escape(selectedOrder)}"]`)
    row?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [selectedOrder, selectedEngineer])

  const orders = ordersById(scenario)
  const routes = scenario.engineers
    .filter((engineer) => selectedEngineer === null || engineer.id === selectedEngineer)
    .flatMap((engineer) => {
      const route = plan.routes.find((r) => r.engineer_id === engineer.id)
      return route?.stops.length ? [{ engineer, route }] : []
    })

  const grouped = isGrouped(sort)

  if (!routes.length) {
    return (
      <div className="empty-note">
        {selectedEngineer ? 'У выбранного инженера в этом плане нет визитов.' : 'Маршрутов нет.'}
      </div>
    )
  }

  function sortHeader(key: SortKey, label: string, align: string) {
    const active = sort?.key === key
    const direction = active ? (sort.descending ? 'descending' : 'ascending') : 'none'
    return (
      <th className={align} aria-sort={direction}>
        <button type="button" className="sort-head" onClick={() => setSort(nextSort(sort, key))}>
          {label}
          {active && <span className="sort-arrow">{sort.descending ? '↓' : '↑'}</span>}
        </button>
      </th>
    )
  }

  const rowProps = { orders, selectedOrder, changed, onSelectOrder, onGoToOrder }
  const columns = grouped ? 10 : 11

  return (
    <div className="table-scroll">
      <table ref={table} className="table route-table">
        <thead>
          <tr>
            {!grouped && sortHeader('engineer', 'Инженер', '')}
            <th className="num">№</th>
            {sortHeader('order', 'Заявка', '')}
            {sortHeader('workType', 'Вид работ', '')}
            <th>Адрес</th>
            <th className="num">Окно клиента</th>
            <th className="num">Прибытие</th>
            {sortHeader('time', 'Начало работ', 'num')}
            <th className="num">Окончание</th>
            <th className="num">Переезд</th>
            <th>Отметки</th>
          </tr>
        </thead>
        <tbody>
          {grouped
            ? sortGroups(routes, sort).map(({ engineer, route, stops }) => (
                <Fragment key={engineer.id}>
                  <tr className="group-row">
                    <td colSpan={columns}>
                      <button
                        type="button"
                        className="group-head"
                        onClick={() => onSelectEngineer(selectedEngineer === engineer.id ? null : engineer.id)}
                        style={{ borderLeftColor: colorOf(engineer.id) }}
                      >
                        <b>{engineer.name}</b>
                        <span className="muted">
                          {TRANSPORT_RU[engineer.transport]}, смена {engineer.shift_start}–{engineer.shift_end}
                        </span>
                        <span className="group-stats">
                          {route.stops.length} визитов, {km(route.distance_km)} км,{' '}
                          {formatMinutes(route.travel_min)} в пути, до {route.end_time}
                        </span>
                      </button>
                    </td>
                  </tr>
                  {stops.map(({ stop, index }) => (
                    <StopRow key={stop.order_id} stop={stop} index={index} engineer={null} {...rowProps} />
                  ))}
                </Fragment>
              ))
            : sortStops(routes, sort!, orders).map(({ engineer, stop, index }) => (
                <StopRow key={stop.order_id} stop={stop} index={index} engineer={engineer} {...rowProps} />
              ))}
        </tbody>
      </table>
    </div>
  )
}

interface StopRowProps {
  stop: Stop
  index: number
  engineer: Engineer | null
  orders: Record<string, Order>
  selectedOrder: string | null
  changed: Set<string>
  onSelectOrder: (id: string) => void
  onGoToOrder: (id: string) => void
}

function StopRow({ stop, index, engineer, orders, selectedOrder, changed, onSelectOrder, onGoToOrder }: StopRowProps) {
  const order = orders[stop.order_id]
  return (
    <tr
      data-order={stop.order_id}
      className={cx('clickable', selectedOrder === stop.order_id && 'selected', stop.locked && 'locked')}
      onClick={() => onSelectOrder(stop.order_id)}
    >
      {engineer && <td>{engineer.name}</td>}
      <td className="num mono">{index + 1}</td>
      <td className="mono strong">
        {stop.order_id}
        {order?.priority === 'urgent' && <span className="badge urgent">срочная</span>}
      </td>
      <td>{order?.work_type}</td>
      <td className="addr">
        {order?.district && <span className="muted">{order.district}, </span>}
        {order && <AddressLink onGo={() => onGoToOrder(order.id)}>{displayAddress(order.address)}</AddressLink>}
      </td>
      <td className="num mono">{order ? `${order.window_start}–${order.window_end}` : ''}</td>
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
          <span className="badge urgent" title="Обещанное время сдвинуто, предупредите клиента">
            позже окна на {stop.late_min} мин
          </span>
        )}
      </td>
    </tr>
  )
}
