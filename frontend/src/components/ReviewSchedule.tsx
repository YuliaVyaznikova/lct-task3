import { useEffect, useMemo, useState, type ReactNode } from 'react'

import type { EventChanges, EventReview } from '../derive'
import { engineerName, km } from '../labels'
import type { Plan, Scenario } from '../types'
import { Gantt, type Ghost } from './Gantt'
import { reviewTitle } from './ReviewCard'

const noop = () => {}

interface ReviewScheduleProps {
  title: string
  badge?: string
  label: string
  before: Plan
  after: Plan
  changes: EventChanges
  scenario: Scenario
  picker?: ReactNode
  onClose: () => void
}

export function ReviewSchedule({ title, badge, label, before, after, changes, scenario, picker = null, onClose }: ReviewScheduleProps) {
  const [everyone, setEveryone] = useState(false)
  const name = (id: string) => engineerName(scenario.engineers, id)
  const ghosts = useMemo(() => buildGhosts(changes, name), [changes, scenario])
  const rows = useMemo(() => (everyone ? undefined : changedEngineers(changes)), [everyone, changes])
  const added = useMemo(() => new Set(changes.added.map((ref) => ref.stop.order_id)), [changes])
  const received = useMemo(
    () => new Set(changes.changed.filter((c) => c.kinds.includes('engineer')).map((c) => c.orderId)),
    [changes],
  )
  const titles = useMemo(() => buildTitles(changes, name), [changes, scenario])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="review-overlay" role="region" aria-label={label}>
      <div className="sched-head">
        <div className="review-title">
          <button type="button" className="ghost small" onClick={onClose}>
            ← Назад
          </button>
          <h2>{title}</h2>
          {badge && <span className="review-variant">{badge}</span>}
          {picker}
        </div>
        <div className="review-stats">
          <Stat label="Заявок" from={before.metrics.assigned} to={after.metrics.assigned} />
          <Stat label="Километров" from={km(before.metrics.distance_total_km)} to={km(after.metrics.distance_total_km)} />
          <Stat label="Инженеров" from={before.metrics.engineers_used} to={after.metrics.engineers_used} />
        </div>
        <label className="review-toggle">
          <input type="checkbox" checked={everyone} onChange={(e) => setEveryone(e.target.checked)} />
          Все инженеры
        </label>
      </div>
      <div className="review-legend">
        <span className="lg-ghost">прежнее место</span>
        <span className="lg-added">новая в плане</span>
        <span className="lg-received">← от другого инженера</span>
        <span className="lg-removed">снята с плана</span>
      </div>
      <div className="review-gantt">
        <Gantt
          scenario={scenario}
          plan={after}
          now={null}
          nowLabel=""
          selectedOrder={null}
          selectedEngineer={null}
          changed={new Set()}
          unavailable={new Set()}
          onSelectOrder={noop}
          onSelectEngineer={noop}
          onDropVisit={noop}
          onCarryVisit={noop}
          carried={null}
          dropTarget={null}
          ghosts={ghosts}
          added={added}
          received={received}
          rows={rows}
          readOnly
          describe={(orderId) => titles[orderId]}
        />
      </div>
    </div>
  )
}

interface EventReviewScheduleProps {
  review: EventReview
  onClose: () => void
}

export function EventReviewSchedule({ review, onClose }: EventReviewScheduleProps) {
  const { record, scenario } = review
  const badge = review.variants.find((variant) => variant.plan_id === record.after.id)?.title
  return (
    <ReviewSchedule
      title={reviewTitle(review, scenario)}
      badge={badge}
      label="Расписание после события"
      before={record.before}
      after={record.after}
      changes={record.changes}
      scenario={scenario}
      onClose={onClose}
    />
  )
}

interface StatProps {
  label: string
  from: number | string
  to: number | string
}

function Stat({ label, from, to }: StatProps) {
  return (
    <span className="review-stat">
      <span className="muted">{label}</span>
      <b>{from === to ? to : `${from} → ${to}`}</b>
    </span>
  )
}

function changedEngineers(changes: EventChanges): Set<string> {
  return new Set(changes.routes.map((route) => route.engineerId))
}

function buildGhosts(changes: EventChanges, name: (id: string) => string): Ghost[] {
  const moved = changes.changed
    .filter((c) => c.before.engineerId !== c.after.engineerId || c.shiftMin !== 0)
    .map((c) => ({
      engineerId: c.before.engineerId,
      orderId: c.orderId,
      start: c.before.stop.start,
      finish: c.before.stop.finish,
      kind: 'moved' as const,
      title: `${c.orderId} · было ${c.before.stop.start}, ${name(c.before.engineerId)}`,
    }))
  const removed = changes.removed.map((ref) => ({
    engineerId: ref.engineerId,
    orderId: ref.stop.order_id,
    start: ref.stop.start,
    finish: ref.stop.finish,
    kind: 'removed' as const,
    title: `${ref.stop.order_id} · снята с плана, была ${ref.stop.start}, ${name(ref.engineerId)}`,
  }))
  return [...moved, ...removed]
}

function buildTitles(changes: EventChanges, name: (id: string) => string): Record<string, string> {
  const titles: Record<string, string> = {}
  for (const ref of changes.added) {
    titles[ref.stop.order_id] = `${ref.stop.order_id} · новая в плане, ${ref.stop.start}–${ref.stop.finish}, ${name(ref.engineerId)}`
  }
  for (const c of changes.changed) {
    const who = c.kinds.includes('engineer') ? `${name(c.before.engineerId)} → ${name(c.after.engineerId)}` : name(c.after.engineerId)
    titles[c.orderId] = `${c.orderId} · ${c.before.stop.start} → ${c.after.stop.start}, ${who}`
  }
  return titles
}
