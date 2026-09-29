import { useEffect, useState } from 'react'

import { stopsByOrder, type EventReview } from '../derive'
import { engineerName, EVENT_KIND_TITLE, km, plural, REASON_LABEL, SKILL_RU } from '../labels'
import { describeEvent } from '../sim'
import { formatMinutes } from '../time'
import type { Scenario } from '../types'

export function reviewTitle(review: EventReview, scenario: Scenario): string {
  const { event } = review.record
  return `${EVENT_KIND_TITLE[event.type]}: ${describeEvent(event, scenario)}`
}

export function droppedLabel(scenario: Scenario, orderId: string): string {
  const order = scenario.orders.find((o) => o.id === orderId)
  return order ? `${orderId} (${(order.work_type || SKILL_RU[order.skill]).toLowerCase()})` : orderId
}

interface ApplyButtonProps {
  review: EventReview
  small?: boolean
}

export function ApplyButton({ review, small = false }: ApplyButtonProps) {
  const dropped = review.dropsByPlan[review.chosen] ?? []
  const [asking, setAsking] = useState(false)
  useEffect(() => setAsking(false), [review.chosen])
  const size = small ? 'small' : ''
  if (!asking) {
    return (
      <button type="button" className={`primary ${size}`} onClick={() => (dropped.length ? setAsking(true) : review.decide(true))}>
        Применить
      </button>
    )
  }
  return (
    <>
      <span className="apply-ask" role="alertdialog">
        Снимет с плана: {dropped.map((id) => droppedLabel(review.scenario, id)).join(', ')}. Клиента предупредит служба поддержки.
      </span>
      <button type="button" className={`danger ${size}`} onClick={() => review.decide(true)}>
        Снять и применить
      </button>
      <button type="button" className={`ghost ${size}`} onClick={() => setAsking(false)}>
        Отмена
      </button>
    </>
  )
}

interface ReviewCardProps {
  review: EventReview
  scenario: Scenario
  onDetails: () => void
}

export function ReviewCard({ review, scenario, onDetails }: ReviewCardProps) {
  const { record, added, decide } = review
  const { changes, before, after, diff, event } = record
  const name = (id: string) => engineerName(scenario.engineers, id)
  const reassigned = changes.changed.filter((change) => change.kinds.includes('engineer')).length
  const stopsBefore = stopsByOrder(before)
  const warn = changes.lateWindowStops.filter((ref) => !(stopsBefore[ref.stop.order_id]?.stop.late_min > 0))
  const dropped = diff.newly_unassigned
  const unassigned = Object.fromEntries(after.unassigned.map((u) => [u.order_id, u]))
  const cancelled = event.type === 'cancel_order' ? event.order_id : null
  const whyRemoved = (id: string) => unassigned[id]?.detail || REASON_LABEL[id === cancelled ? 'CANCELLED' : 'CAPACITY'].toLowerCase()
  const windowEnd = (orderId: string) => scenario.orders.find((o) => o.id === orderId)?.window_end
  const moved = changes.changed.length
  return (
    <div className="review-card" role="group" aria-label="Новый план после события">
      <div className="review-head">
        <b>{reviewTitle(review, scenario)}</b>
        <span className="muted">{event.time}</span>
        <span className="review-actions">
          <ApplyButton review={review} />
          <button type="button" className="ghost" onClick={() => decide(false)}>
            Оставить прежний план
          </button>
          <button type="button" className="ghost" onClick={onDetails}>
            Подробнее
          </button>
        </span>
      </div>
      <ul className="review-list">
        {added && <li>{added}</li>}
        <li>
          Сдвинуто {moved} {plural(moved, 'визит', 'визита', 'визитов')}
          {reassigned > 0 && <>, к другому инженеру {reassigned}</>}, зафиксировано {changes.frozen.length}
        </li>
        <li className="muted">
          Заявок {before.metrics.assigned} → {after.metrics.assigned} · {km(before.metrics.distance_total_km)} → {km(after.metrics.distance_total_km)} км
        </li>
      </ul>
      <div className="review-groups">
        {dropped.length > 0 && (
          <section className="review-group bad">
            <h3>Снято с плана</h3>
            <ul>
              {dropped.map((id) => (
                <li key={id}>
                  {droppedLabel(scenario, id)}: {whyRemoved(id)}
                </li>
              ))}
              {diff.newly_assigned.length > 0 && (
                <li className="muted">Одновременно в план вошли: {diff.newly_assigned.join(', ')}</li>
              )}
            </ul>
          </section>
        )}
        {warn.length > 0 && (
          <section className="review-group bad">
            <h3>Предупредить клиентов</h3>
            <ul>
              {warn.map((ref) => (
                <li key={ref.stop.order_id}>
                  {ref.stop.order_id}: {name(ref.engineerId)} приедет в {ref.stop.start}, позже окна на {formatMinutes(ref.stop.late_min)}
                  {windowEnd(ref.stop.order_id) && <span className="muted"> (до {windowEnd(ref.stop.order_id)})</span>}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  )
}
