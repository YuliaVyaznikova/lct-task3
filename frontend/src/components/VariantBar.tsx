import type { ReactNode } from 'react'

import { cx } from '../classes'
import { km, MINE_TITLE, VARIANT_NOTE, VARIANT_ORDER, VARIANT_TITLE } from '../labels'
import type { EventReview } from '../derive'
import type { BarVariant, Metrics, MineVariant, RunningJob, Scenario } from '../types'
import { useElapsed } from './common'
import { droppedLabel, ReviewCard } from './ReviewCard'
import { verdictAgainst } from '../variant-diff'

const LOCK_HINT = 'Поставьте симуляцию на паузу, чтобы сменить план'

interface VariantBarProps {
  job: RunningJob | null
  variants: BarVariant[]
  mine?: MineVariant | null
  review?: EventReview | null
  tools?: ReactNode
  planControl?: ReactNode
  currentPlanId: string | null
  hovered: string | null
  onHover: (planId: string | null) => void
  onSelect: (planId: string) => void
  selecting: string | null
  watching?: string | null
  onWatch?: (key: string) => void
  onPeek?: (key: string | null) => void
  onReviewDetails?: () => void
  onCompare?: (planId: string) => void
  comparing?: string | null
  scheduleOpen?: boolean
  onToggleSchedule?: () => void
  locked?: boolean
}

interface FiguresProps {
  assigned: number
  total: number
  engineers: number
  distance: number
  peak?: number
}

function Figures({ assigned, total, engineers, distance, peak }: FiguresProps) {
  return (
    <span className="vc-figures" title={`${assigned}/${total} заявок · ${engineers} инж. · ${km(distance, 0)} км`}>
      <b>{assigned}</b>/{total}<span className="vc-orders"> заявок</span> · <b>{engineers}</b> инж. · <b>{km(distance, 0)}</b> км
      {peak !== undefined && <span title="Самая большая загрузка инженера за смену"> · до <b>{Math.round(peak * 100)}</b>%</span>}
    </span>
  )
}

const fromMetrics = (m: Metrics) => ({
  assigned: m.assigned,
  total: m.orders_total,
  engineers: m.engineers_used,
  distance: m.distance_total_km,
  peak: Math.max(0, ...Object.values(m.utilization_by_engineer ?? {})),
})

interface VerdictLine {
  sign: '+' | '−'
  text: string
}

const MAX_LINES = 3

function isSameOutcome(a: Metrics, b: Metrics): boolean {
  const { pros, cons } = verdictAgainst(a, b)
  return pros.length === 0 && cons.length === 0
}

function verdictLines(metrics: Metrics, reference: Metrics): VerdictLine[] {
  const { pros, cons } = verdictAgainst(metrics, reference)
  const lines: VerdictLine[] = [
    ...pros.map((text) => ({ sign: '+' as const, text })),
    ...cons.map((text) => ({ sign: '−' as const, text })),
  ]
  return lines.slice(0, MAX_LINES)
}

interface VerdictLinesProps {
  lines: VerdictLine[]
  twinOf: string
}

function VerdictLines({ lines, twinOf }: VerdictLinesProps) {
  if (!lines.length) {
    return <span className="vc-note">совпадает с «{twinOf}»</span>
  }
  return (
    <span className="vc-lines">
      {lines.map((line) => (
        <span key={line.text} className={cx('vc-line', line.sign === '+' ? 'pro' : 'con')}>
          {line.sign} {line.text}
        </span>
      ))}
    </span>
  )
}

interface CardProps {
  title: string
  note?: string
  figures: FiguresProps | null
  lines?: VerdictLine[]
  twinOf?: string
  idle?: boolean
  on: boolean
  hover: boolean
  searching: boolean
  disabled: boolean
  hint?: string
  mine?: boolean
  spinning?: boolean
  warn?: boolean
  onEnter: () => void
  onClick: () => void
  onCompare?: () => void
  comparing?: boolean
}

function verdictTip(lines: VerdictLine[] | undefined, twinOf: string): string | undefined {
  if (!lines) {
    return undefined
  }
  return lines.length ? lines.map((line) => `${line.sign} ${line.text}`).join('\n') : `совпадает с «${twinOf}»`
}

function Card({ title, note, figures, lines, twinOf = '', idle, on, hover, searching, disabled, hint, mine, spinning, warn, onEnter, onClick, onCompare, comparing = false }: CardProps) {
  return (
    <div className="vc-slot">
      <button
        type="button"
        role="radio"
        aria-checked={on}
        disabled={disabled}
        title={hint ?? verdictTip(lines, twinOf)}
        className={cx('vc', on && 'on', hover && 'hover', searching && 'searching', mine && 'mine')}
        onMouseEnter={onEnter}
        onFocus={onEnter}
        onClick={onClick}
      >
        <i className="radio" aria-hidden />
        <span className="vc-body">
          <span className="vc-title">
            {title}
            {spinning && <span className="spinner" aria-hidden />}
          </span>
          {figures ? <Figures {...figures} /> : <span className="vc-figures muted">{idle ? '\u00a0' : 'ищем…'}</span>}
          {lines ? <VerdictLines lines={lines} twinOf={twinOf} /> : <span className={`vc-note ${warn ? 'warn' : ''}`}>{note}</span>}
        </span>
      </button>
      {onCompare && (
        <button type="button" className={cx('vc-compare', comparing && 'on')} aria-pressed={comparing} onClick={onCompare}>
          {comparing ? 'скрыть ‹' : 'сравнить ›'}
        </button>
      )}
    </div>
  )
}

function dropNote(dropped: string[], scenario: Scenario): string {
  if (!dropped.length) {
    return 'ничего не снимает'
  }
  const shown = dropped.slice(0, 2).map((id) => droppedLabel(scenario, id))
  return `снимает ${shown.join(', ')}${dropped.length > 2 ? '…' : ''}`
}

export function VariantBar({ job, variants, mine: ownMine = null, review = null, tools = null, planControl = null, currentPlanId, hovered, onHover, onSelect, selecting, watching = null, onWatch, onPeek, onReviewDetails = () => {}, onCompare = () => {}, comparing = null, scheduleOpen = false, onToggleSchedule, locked = false }: VariantBarProps) {
  const elapsed = useElapsed(job?.startedAt ?? null)
  const running = job !== null
  const idle = !running && review === null && variants.length === 0 && ownMine === null
  const reviewing = review !== null && !running
  const simLocked = locked && !reviewing
  const shownVariants = reviewing ? review.variants : variants
  const mine = reviewing ? null : ownMine
  const currentId = reviewing ? review.chosen : currentPlanId
  const hoveredId = reviewing ? review.previewed : hovered
  const hoverCard = reviewing ? review.onPreview : onHover
  const selectCard = reviewing ? review.onChoose : onSelect
  const liveKeys = job ? Object.keys(job.byVariant) : []
  const keys = running
    ? job.kind === 'plan'
      ? [...new Set([...VARIANT_ORDER.filter((k) => job.expected.includes(k) || liveKeys.includes(k)), ...liveKeys])]
      : []
    : idle
      ? VARIANT_ORDER
      : shownVariants.map((v) => v.key)
  const share = job ? Math.min(elapsed / Math.max(job.budgetS, 1), 1) : 1
  const mineActive = !running && mine !== null && mine.planId === currentId
  const cardCount = keys.length + (mine && !running ? 1 : 0)
  const currentVariant = mineActive ? null : shownVariants.find((v) => v.plan_id === currentId)
  const referenceMetrics = mineActive ? mine.metrics : currentVariant?.metrics ?? null
  const referenceTitle = mineActive ? mine.title ?? MINE_TITLE : currentVariant?.title ?? ''
  const canCompare = !running && !reviewing && !idle
  const linesFor = (planId: string, metrics: Metrics): VerdictLine[] | undefined => {
    if (running || reviewing || !referenceMetrics || planId === currentId) {
      return undefined
    }
    return twinOf(planId, metrics) ? [] : verdictLines(metrics, referenceMetrics)
  }
  const twinOf = (planId: string, metrics: Metrics): string | null => {
    const earlier = shownVariants.slice(0, shownVariants.findIndex((v) => v.plan_id === planId))
    const twin = earlier.find((v) => v.plan_id !== currentId && isSameOutcome(metrics, v.metrics))
    return twin?.title ?? null
  }
  const compareFor = (planId: string) => (canCompare && planId !== currentId ? () => onCompare(planId) : undefined)
  const side = !reviewing && (
    <div className="vb-side">
      {planControl}
      {tools}
      {canCompare && onToggleSchedule && (
        <button type="button" className={cx('ghost small vb-schedule', scheduleOpen && 'on')} aria-pressed={scheduleOpen} onClick={onToggleSchedule}>
          {scheduleOpen ? 'Скрыть' : 'Подробнее'}
        </button>
      )}
    </div>
  )

  return (
    <section className={cx('variant-bar', running && 'running', reviewing && 'deciding')} aria-label="Расчёт и варианты плана">
      {side}
      <div className={`vb-main ${reviewing ? 'reviewing' : ''}`}>
        {reviewing ? (
          <ReviewCard review={review} scenario={review.scenario} onDetails={onReviewDetails} />
        ) : (
          running && (
            <div className="vb-status" role="status" aria-live="polite">
              <span className="vb-progress">
                <span className="vb-progress-line">
                  <b>{job.label}</b>
                  <span className="vb-progress-time">
                    {Math.floor(elapsed)} из {job.budgetS} с
                  </span>
                </span>
                <span className="vb-track">
                  <i style={{ width: `${share * 100}%` }} />
                </span>
                <span className="vb-progress-note">
                  {job.kind === 'event' && job.last && (
                    <>
                      {job.last.assigned}/{job.last.total} заявок · {job.last.engineers_used} инж. · {km(job.last.distance_km, 0)} км
                    </>
                  )}
                </span>
              </span>
            </div>
          )
        )}
        <div className="vb-cards" role="radiogroup" aria-label="Вариант плана" style={{ ['--cards' as string]: Math.max(cardCount, 1) }} onMouseLeave={() => {
            hoverCard(null)
            onPeek?.(null)
          }}
        >
          {keys.map((key) => {
            const variant = shownVariants.find((v) => v.key === key)
            const live = job?.byVariant[key]
            const figures = running
              ? live ? { assigned: live.assigned, total: live.total, engineers: live.engineers_used, distance: live.distance_km } : null
              : variant ? fromMetrics(variant.metrics) : null
            return (
              <Card
                key={key}
                title={variant?.title || VARIANT_TITLE[key] || key}
                note={reviewing ? dropNote(review.dropsByPlan[variant?.plan_id ?? ''] ?? [], review.scenario) : VARIANT_NOTE[key]}
                warn={reviewing && (review.dropsByPlan[variant?.plan_id ?? '']?.length ?? 0) > 0}
                figures={figures}
                lines={variant ? linesFor(variant.plan_id, variant.metrics) : undefined}
                twinOf={(variant && twinOf(variant.plan_id, variant.metrics)) ?? referenceTitle}
                onCompare={variant ? compareFor(variant.plan_id) : undefined}
                comparing={Boolean(variant) && variant?.plan_id === comparing}
                idle={idle}
                on={running ? key === watching : !mineActive && variant?.plan_id === currentId}
                hover={Boolean(hoveredId && variant?.plan_id === hoveredId)}
                searching={running}
                disabled={running ? !live || !onWatch : !variant || simLocked}
                hint={simLocked && variant ? LOCK_HINT : undefined}
                spinning={!reviewing && selecting !== null && selecting === variant?.plan_id}
                onEnter={() => (running ? onPeek?.(key) : variant && hoverCard(variant.plan_id))}
                onClick={() => (running ? onWatch?.(key) : variant && selectCard(variant.plan_id))}
              />
            )
          })}
          {mine && !running && (
            <Card
              title={mine.title ?? MINE_TITLE}
              note={mine.from ? `${mine.draft ? 'копия' : 'из'} «${mine.from}»` : undefined}
              figures={fromMetrics(mine.metrics)}
              lines={linesFor(mine.planId, mine.metrics)}
              twinOf={referenceTitle}
              onCompare={compareFor(mine.planId)}
              comparing={mine.planId === comparing}
              on={mineActive}
              hover={hoveredId === mine.planId}
              searching={false}
              disabled={simLocked}
              hint={simLocked ? LOCK_HINT : undefined}
              mine
              spinning={selecting === mine.planId}
              onEnter={() => hoverCard(mine.planId)}
              onClick={() => selectCard(mine.planId)}
            />
          )}
        </div>
      </div>
    </section>
  )
}
