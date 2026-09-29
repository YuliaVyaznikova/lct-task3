import { cx } from '../classes'
import { useEngineerColor } from '../colors'
import { addressWithoutCity, orderCity, stopsByOrder } from '../derive'
import { effectiveTier, engineerName, SKILL_SHORT, TIER_LABEL } from '../labels'
import { minutes } from '../time'
import type { Engineer, Order, Plan, Scenario, Unassigned } from '../types'
import { AddressLink, LockIcon, RequiredToggle } from './common'

export type QueueFilter = 'all' | 'unplaced' | 'urgent' | 'required'

const QUEUE_FILTERS: [QueueFilter, string][] = [
  ['all', 'все'],
  ['unplaced', 'не размещены'],
  ['urgent', 'срочные'],
  ['required', 'обязательные'],
]

const EMPTY_NOTE: Record<QueueFilter, string> = {
  all: 'Нет заявок.',
  unplaced: 'Все заявки размещены.',
  urgent: 'Нет заявок.',
  required: 'Обязательных заявок нет.',
}

interface JobQueueProps {
  scenario: Scenario
  plan: Plan | null
  filter: QueueFilter
  onFilter: (f: QueueFilter) => void
  selectedOrder: string | null
  onSelectOrder: (id: string) => void
  onGoToOrder: (id: string) => void
  changed: Set<string>
  required: Set<string>
  onToggleRequired: (orderId: string) => void
}

export function JobQueue({ scenario, plan, filter, onFilter, selectedOrder, onSelectOrder, onGoToOrder, changed, required, onToggleRequired }: JobQueueProps) {
  const refs = plan ? stopsByOrder(plan) : {}
  const unassigned = new Map((plan?.unassigned ?? []).map((u) => [u.order_id, u]))
  const isUrgent = (o: Order) => o.priority === 'urgent' || effectiveTier(o) === 1
  const isUnplaced = (o: Order) => Boolean(plan && !refs[o.id] && !cancelledAt(o))
  const counts = {
    all: scenario.orders.length,
    unplaced: scenario.orders.filter(isUnplaced).length,
    urgent: scenario.orders.filter(isUrgent).length,
    required: scenario.orders.filter((o) => required.has(o.id)).length,
  }
  const items = scenario.orders
    .filter((o) =>
      filter === 'unplaced' ? isUnplaced(o) : filter === 'urgent' ? isUrgent(o) : filter === 'required' ? required.has(o.id) : true,
    )
    .sort((a, b) => {
      const ua = isUnplaced(a) ? 0 : cancelledAt(a) ? 2 : 1
      const ub = isUnplaced(b) ? 0 : cancelledAt(b) ? 2 : 1
      if (ua !== ub) {
        return ua - ub
      }
      const ta = refs[a.id] ? minutes(refs[a.id].stop.start) : minutes(a.window_start)
      const tb = refs[b.id] ? minutes(refs[b.id].stop.start) : minutes(b.window_start)
      return ta - tb || a.id.localeCompare(b.id)
    })

  return (
    <div className="panel queue">
      <div className="panel-head">
        <h2>Заявки</h2>
        <div className="seg" role="tablist" aria-label="Фильтр заявок">
          {QUEUE_FILTERS.filter(([key]) => key !== 'required' || counts.required > 0 || filter === 'required').map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={filter === key}
              className={filter === key ? 'on' : ''}
              onClick={() => onFilter(key)}
            >
              {label} <span className="n">{counts[key]}</span>
            </button>
          ))}
        </div>
      </div>
      <ul className="panel-scroll">
        {items.length === 0 && <li className="empty-note">{EMPTY_NOTE[filter]}</li>}
        {groupByTier(items).map((group) => {
          const hasSubgroups = group.cities.length > 1
          return (
            <li key={group.tier} className="q-group">
              <div className="q-group-head">
                <i className={`tier-dot t${group.tier}`} />
                {TIER_LABEL[group.tier]} <span className="n">{group.count}</span>
              </div>
              <ul>
                {group.cities.map((part) => (
                  <li key={part.city} className={cx(hasSubgroups && 'q-subgroup')}>
                    {hasSubgroups && <div className="q-subgroup-head">{part.city}</div>}
                    <ul>
                      {part.orders.map((order) => (
                        <QueueRow
                          key={order.id}
                          order={order}
                          ref_={refs[order.id]}
                          unassigned={unassigned.get(order.id)}
                          hasPlan={Boolean(plan)}
                          engineers={scenario.engineers}
                          selected={selectedOrder === order.id}
                          changed={changed.has(order.id)}
                          required={required.has(order.id)}
                          onSelect={() => onSelectOrder(order.id)}
                          onGo={() => onGoToOrder(order.id)}
                          onToggleRequired={() => onToggleRequired(order.id)}
                        />
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

interface CityPart {
  city: string
  orders: Order[]
}

interface TierGroup {
  tier: number
  count: number
  cities: CityPart[]
}

function groupByTier(orders: Order[]): TierGroup[] {
  return [1, 2, 3]
    .map((tier) => orders.filter((o) => effectiveTier(o) === tier))
    .filter((inTier) => inTier.length > 0)
    .map((inTier) => ({ tier: effectiveTier(inTier[0]), count: inTier.length, cities: groupByCity(inTier) }))
}

function cancelledAt(order: Order): string | undefined {
  return order.attributes?.cancelled_at as string | undefined
}

function groupByCity(orders: Order[]): CityPart[] {
  const byCity = new Map<string, Order[]>()
  for (const order of orders) {
    const city = orderCity(order)
    byCity.set(city, [...(byCity.get(city) ?? []), order])
  }
  return [...byCity].map(([city, inCity]) => ({ city, orders: inCity }))
}

interface QueueRowProps {
  order: Order
  ref_: ReturnType<typeof stopsByOrder>[string] | undefined
  unassigned: Unassigned | undefined
  hasPlan: boolean
  engineers: Engineer[]
  selected: boolean
  changed: boolean
  required: boolean
  onSelect: () => void
  onGo: () => void
  onToggleRequired: () => void
}

function QueueRowBottom({ order, ref_: ref, unassigned, engineers }: QueueRowProps) {
  const colorOf = useEngineerColor()
  if (ref) {
    return (
      <span className="q-bottom">
        <i className="dot" style={{ background: colorOf(ref.engineerId) }} />
        <span className="q-eng">{engineerName(engineers, ref.engineerId)}</span>
        <span className="q-at">
          визит {ref.position}, {ref.stop.start}
        </span>
        {ref.stop.locked && <LockIcon title="Зафиксирован" />}
      </span>
    )
  }
  if (cancelledAt(order)) {
    return (
      <span className="q-bottom">
        <span className="muted">отменена в {cancelledAt(order)}</span>
      </span>
    )
  }
  if (unassigned) {
    return (
      <span className="q-bottom">
        <span className="q-reason-block">
          <span className="q-detail">{unassigned.detail}</span>
        </span>
      </span>
    )
  }
  return (
    <span className="q-bottom">
      <span className="muted">
        {SKILL_SHORT[order.skill]} · {order.duration_min} мин · {order.district}
      </span>
    </span>
  )
}

function QueueRow(p: QueueRowProps) {
  const { order } = p
  const tier = effectiveTier(order)
  return (
    <li>
      <button type="button" className={cx('q-row', p.selected && 'selected', !p.ref_ && p.hasPlan && !cancelledAt(order) && 'unplaced', cancelledAt(order) && 'cancelled')} onClick={p.onSelect}>
        <span className="q-top">
          <i className={`tier-dot t${tier}`} title={`ярус ${tier}`} />
          <b className="q-id">{order.id}</b>
          {order.priority === 'urgent' && <span className="tag urgent">срочная</span>}
          {p.changed && <span className="tag changed">изменена</span>}
          {cancelledAt(order) && <span className="tag">отменена</span>}
          <span className="q-window">
            {order.window_start}–{order.window_end}
          </span>
          <RequiredToggle on={p.required} onToggle={p.onToggleRequired} compact />
        </span>
        <span className="q-addr">
          <AddressLink onGo={p.onGo}>{addressWithoutCity(order.address)}</AddressLink>
        </span>
        <QueueRowBottom {...p} />
      </button>
    </li>
  )
}
