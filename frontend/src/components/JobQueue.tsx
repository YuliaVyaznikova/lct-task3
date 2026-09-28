import { engineerColor, minutes } from '../colors'
import { stopsByOrder } from '../derive'
import { effectiveTier, reasonLabel } from '../labels'
import type { Order, Plan, Scenario } from '../types'
import { LockIcon } from './common'

export type QueueFilter = 'all' | 'unplaced' | 'urgent'

interface Props {
  scenario: Scenario
  plan: Plan | null
  filter: QueueFilter
  onFilter: (f: QueueFilter) => void
  selectedOrder: string | null
  onSelectOrder: (id: string) => void
  changed: Set<string>
}

const SKILL_SHORT: Record<string, string> = { local: 'локальные', connection: 'подключение', emergency: 'авария' }

export function JobQueue({ scenario, plan, filter, onFilter, selectedOrder, onSelectOrder, changed }: Props) {
  const refs = plan ? stopsByOrder(plan) : {}
  const unassigned = new Map((plan?.unassigned ?? []).map((u) => [u.order_id, u]))
  const ids = scenario.engineers.map((e) => e.id)
  const isUrgent = (o: Order) => o.priority === 'urgent' || effectiveTier(o) === 1
  const cancelledAt = (o: Order) => o.attributes?.cancelled_at as string | undefined
  const isUnplaced = (o: Order) => Boolean(plan && !refs[o.id] && !cancelledAt(o))
  const counts = {
    all: scenario.orders.length,
    unplaced: scenario.orders.filter(isUnplaced).length,
    urgent: scenario.orders.filter(isUrgent).length,
  }
  const items = scenario.orders
    .filter((o) => (filter === 'unplaced' ? isUnplaced(o) : filter === 'urgent' ? isUrgent(o) : true))
    .sort((a, b) => {
      const ua = isUnplaced(a) ? 0 : cancelledAt(a) ? 2 : 1
      const ub = isUnplaced(b) ? 0 : cancelledAt(b) ? 2 : 1
      if (ua !== ub) return ua - ub
      const ta = refs[a.id] ? minutes(refs[a.id].stop.start) : minutes(a.window_start)
      const tb = refs[b.id] ? minutes(refs[b.id].stop.start) : minutes(b.window_start)
      return ta - tb || a.id.localeCompare(b.id)
    })

  return (
    <div className="panel queue">
      <div className="panel-head">
        <h2>Заявки</h2>
        <div className="seg" role="tablist" aria-label="Фильтр заявок">
          {(
            [
              ['all', 'все'],
              ['unplaced', 'не размещены'],
              ['urgent', 'срочные'],
            ] as [QueueFilter, string][]
          ).map(([key, label]) => (
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
      <ul className="panel-scroll q-list">
        {items.length === 0 && <li className="empty-note">{filter === 'unplaced' ? 'Все заявки размещены.' : 'Нет заявок.'}</li>}
        {items.map((order) => {
          const ref = refs[order.id]
          const u = unassigned.get(order.id)
          const tier = effectiveTier(order)
          return (
            <li key={order.id}>
              <button
                type="button"
                className={`q-row ${selectedOrder === order.id ? 'selected' : ''} ${isUnplaced(order) ? 'unplaced' : ''} ${cancelledAt(order) ? 'cancelled' : ''}`}
                onClick={() => onSelectOrder(order.id)}
              >
                <span className="q-top">
                  <i className={`tier-dot t${tier}`} title={`ярус ${tier}`} />
                  <b className="q-id">{order.id}</b>
                  {order.priority === 'urgent' && <span className="tag urgent">срочная</span>}
                  {changed.has(order.id) && <span className="tag changed">изменена</span>}
                  {cancelledAt(order) && <span className="tag">отменена</span>}
                  <span className="q-window">
                    {order.window_start}–{order.window_end}
                  </span>
                </span>
                <span className="q-bottom">
                  {ref ? (
                    <>
                      <i className="dot" style={{ background: engineerColor(ids, ref.engineerId) }} />
                      <span className="q-eng">{scenario.engineers.find((e) => e.id === ref.engineerId)?.name}</span>
                      <span className="q-at">
                        визит {ref.position}, {ref.stop.start}
                      </span>
                      {ref.stop.locked && <LockIcon title="Зафиксирован" />}
                    </>
                  ) : u ? (
                    <span className="q-reason">{reasonLabel(u.reason_code)}</span>
                  ) : cancelledAt(order) ? (
                    <span className="muted">отменена в {cancelledAt(order)}</span>
                  ) : (
                    <span className="muted">
                      {SKILL_SHORT[order.skill]} · {order.duration_min} мин · {order.district}
                    </span>
                  )}
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
