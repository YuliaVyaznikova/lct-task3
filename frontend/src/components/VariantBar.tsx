import { km } from '../labels'
import type { JobProgress, Metrics, Variant } from '../types'
import { useElapsed } from './common'

export const VARIANT_TITLE: Record<string, string> = {
  min_engineers: 'Меньше инженеров',
  min_distance: 'Меньше пробега',
  balanced: 'Равномерно',
}
const ORDER = ['min_engineers', 'min_distance', 'balanced']

export interface RunningJob {
  kind: 'plan' | 'event'
  label: string
  startedAt: number
  budgetS: number
  streaming: boolean
  last: JobProgress | null
  byVariant: Record<string, JobProgress>
  improvements: number
  expected: string[]
}

interface Props {
  job: RunningJob | null
  variants: Variant[]
  currentPlanId: string | null
  hovered: string | null
  onHover: (planId: string | null) => void
  onSelect: (planId: string) => void
  selecting: string | null
}

function Figures({ assigned, total, engineers, distance }: { assigned: number; total: number; engineers: number; distance: number }) {
  return (
    <span className="vc-figures">
      <b>{assigned}</b>/{total} заявок · <b>{engineers}</b> инж. · <b>{km(distance, 0)}</b> км
    </span>
  )
}

const fromMetrics = (m: Metrics) => ({
  assigned: m.assigned,
  total: m.orders_total,
  engineers: m.engineers_used,
  distance: m.distance_total_km,
})

export function VariantBar({ job, variants, currentPlanId, hovered, onHover, onSelect, selecting }: Props) {
  const elapsed = useElapsed(job?.startedAt ?? null)
  const running = job !== null
  const liveKeys = job ? Object.keys(job.byVariant) : []
  const keys = running
    ? job!.streaming && job!.kind === 'plan'
      ? [...new Set([...ORDER.filter((k) => job!.expected.includes(k) || liveKeys.includes(k)), ...liveKeys])]
      : []
    : variants.map((v) => v.key)
  const share = job ? Math.min(elapsed / Math.max(job.budgetS, 1), 1) : 1

  return (
    <section className={`variant-bar ${running ? 'running' : ''}`} aria-label="Расчёт и варианты плана">
      <div className="vb-status" role="status" aria-live="polite">
        {running ? (
          <>
            <span className="spinner lg" aria-hidden />
            <span className="vb-text">
              <b>{job!.label}…</b>
              <span className="muted">
                {Math.floor(elapsed)} с из {job!.budgetS} с
                {job!.streaming && job!.improvements > 0 && ` · улучшений ${job!.improvements}`}
                {job!.kind === 'event' && job!.last && (
                  <>
                    {' '}
                    · {job!.last.assigned}/{job!.last.total} заявок · {job!.last.engineers_used} инж. · {km(job!.last.distance_km, 0)} км
                  </>
                )}
              </span>
              <span className={`vb-track ${job!.streaming ? '' : 'indeterminate'}`}>
                <i style={job!.streaming ? { width: `${share * 100}%` } : undefined} />
              </span>
            </span>
          </>
        ) : (
          <span className="vb-text">
            <b>Варианты плана</b>
            <span className="muted">{variants.length} из расчёта</span>
          </span>
        )}
      </div>
      <div className="vb-cards" role="radiogroup" aria-label="Вариант плана" onMouseLeave={() => onHover(null)}>
        {keys.map((key) => {
          const variant = variants.find((v) => v.key === key)
          const live = job?.byVariant[key]
          const current = !running && variant?.plan_id === currentPlanId
          const figures = running
            ? live && { assigned: live.assigned, total: live.total, engineers: live.engineers_used, distance: live.distance_km }
            : variant && fromMetrics(variant.metrics)
          const searching = running && job?.last?.variant === key
          return (
            <button
              key={key}
              type="button"
              role="radio"
              aria-checked={current}
              disabled={running || !variant}
              className={`vc ${current ? 'on' : ''} ${hovered && variant?.plan_id === hovered ? 'hover' : ''} ${searching ? 'searching' : ''}`}
              onMouseEnter={() => variant && !running && onHover(variant.plan_id)}
              onFocus={() => variant && !running && onHover(variant.plan_id)}
              onClick={() => variant && onSelect(variant.plan_id)}
            >
              <i className="radio" aria-hidden />
              <span className="vc-body">
                <span className="vc-title">
                  {variant?.title || VARIANT_TITLE[key] || key}
                  {selecting === variant?.plan_id && <span className="spinner" aria-hidden />}
                </span>
                {figures ? <Figures {...figures} /> : <span className="vc-figures muted">ищем…</span>}
              </span>
            </button>
          )
        })}
      </div>
    </section>
  )
}
