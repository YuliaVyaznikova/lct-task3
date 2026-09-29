import { cx } from '../classes'
import { compareWithBaseline, type KpiView } from '../derive'
import { km, percent, signed, TIER_NAME } from '../labels'
import type { Metrics } from '../types'

interface KpiStripProps {
  view: KpiView
  empty?: boolean
  live: boolean
  before: Metrics | null
  baseline: Metrics | null
}

interface DeltaProps {
  value: number
  digits?: number
  lowerIsBetter?: boolean
  unit?: string
}

function Delta({ value, digits = 0, lowerIsBetter = false, unit = '' }: DeltaProps) {
  const rounded = Number(value.toFixed(digits))
  if (rounded === 0) {
    return <span className="delta-chip">±0{unit}</span>
  }
  const good = lowerIsBetter ? rounded < 0 : rounded > 0
  return (
    <span className={`delta-chip ${good ? 'good' : 'bad'}`}>
      {signed(rounded, digits)}
      {unit}
    </span>
  )
}

interface BaselineLineProps {
  current?: number
  baseline: number | null
  higherIsBetter: boolean
  digits?: number
  unit?: string
  unknown?: boolean
  canPraise?: boolean
  canBlame?: boolean
}

function BaselineLine({ current = 0, baseline, higherIsBetter, digits = 0, unit = '', unknown = false, canPraise = true, canBlame = true }: BaselineLineProps) {
  if (baseline === null) {
    return <div className="kpi-base">{unknown ? 'база ?' : NO_BASE}</div>
  }
  const { delta, better } = compareWithBaseline(current, baseline, higherIsBetter)
  const cls = cx(canPraise && better === true && 'good-text', canBlame && better === false && 'bad-text') || undefined
  const unitSuffix = unit && ` ${unit.trim()}`
  return (
    <div className="kpi-base">
      <span className={cls}>{`база ${km(baseline, digits)}${unitSuffix} · ${signed(delta, digits)}`}</span>
    </div>
  )
}

const NO_BASE = '\u00a0'
const UNKNOWN = '?'

interface KmBarProps {
  km: number
  baseline: number | null
  canBlame: boolean
}

function KmBar({ km: value, baseline, canBlame }: KmBarProps) {
  const over = canBlame && baseline !== null && value > baseline
  return (
    <div className={cx('thin-bar', over && 'bad')} aria-hidden>
      <i style={{ width: `${baseline ? Math.min(percent(value, baseline), 100) : 0}%` }} />
    </div>
  )
}

export function KpiStrip({ view, empty = false, live, before, baseline }: KpiStripProps) {
  const v = view
  const deltas = before && !empty
  const base = (value: (m: Metrics) => number) => (baseline && !empty ? value(baseline) : null)
  const kmCanPraise = baseline !== null && v.assigned >= baseline.assigned
  const kmCanBlame = baseline !== null && v.assigned <= baseline.assigned
  return (
    <section className={cx('kpis', live && 'live', empty && 'empty')} aria-label="Сводка плана" aria-live={live ? 'polite' : undefined}>
      <div className="kpi">
        <div className="kpi-line">
          <b className="kpi-value">{empty ? UNKNOWN : v.assigned}</b>
          <span className="kpi-unit">{v.total ? `из ${v.total} заявок` : 'заявок'}</span>
          {deltas && <Delta value={v.assigned - before.assigned} />}
        </div>
        <div className="tier-bar" aria-hidden>
          {v.tiers.map((t) => (
            <span key={t.tier} className={`tier-seg t${t.tier}`} style={{ flexGrow: t.total }}>
              <i style={{ width: `${percent(t.assigned, t.total)}%` }} />
            </span>
          ))}
        </div>
        <div className="kpi-legend">
          {v.tiers.map((t) => (
            <span key={t.tier} className={!empty && t.assigned < t.total ? 'short' : ''}>
              <i className={`tier-dot t${t.tier}`} />
              {TIER_NAME[t.tier] ?? `ярус ${t.tier}`} {empty ? UNKNOWN : t.assigned}/{t.total}
              {t.tier === 1 && v.response && (
                <span
                  className={v.response.over ? 'warn-text' : ''}
                  title={`Реакция на аварию по ${v.response.measured}: медиана ${v.response.median} мин, максимум ${v.response.max} мин, дольше двух часов ${v.response.over}`}
                >
                  {' '}· реакция {v.response.median} мин
                </span>
              )}
            </span>
          ))}
          {v.rescheduled > 0 && <span className="warn-text">сдвинуто время у {v.rescheduled}</span>}
        </div>
        <BaselineLine current={v.assigned} baseline={base((m) => m.assigned)} higherIsBetter unknown={empty} />
      </div>

      <div className="kpi">
        <div className="kpi-line">
          <b className="kpi-value">{empty ? UNKNOWN : v.engineersUsed}</b>
          <span className="kpi-unit">{v.engineersTotal ? `из ${v.engineersTotal} инженеров` : 'инженеров'}</span>
          {deltas && <Delta value={v.engineersUsed - before.engineers_used} lowerIsBetter />}
        </div>
        <div className="thin-bar">
          <i style={{ width: `${percent(v.engineersUsed, v.engineersTotal)}%` }} />
        </div>
        <BaselineLine current={v.engineersUsed} baseline={base((m) => m.engineers_used)} higherIsBetter={false} unknown={empty} />
      </div>

      <div className="kpi">
        <div className="kpi-line">
          <b className="kpi-value">{empty ? UNKNOWN : km(v.km, 0)}</b>
          <span className="kpi-unit">км</span>
          {deltas && <Delta value={v.km - before.distance_total_km} digits={1} lowerIsBetter unit=" км" />}
        </div>
        <KmBar km={v.km} baseline={base((m) => m.distance_total_km)} canBlame={kmCanBlame} />
        <div className="kpi-legend">
          <span>{`${empty ? UNKNOWN : v.assigned ? km(v.km / v.assigned, 1) : '0'} км на заявку`}</span>
        </div>
        <BaselineLine current={v.km} baseline={base((m) => m.distance_total_km)} higherIsBetter={false} digits={1} unit="км" unknown={empty} canPraise={kmCanPraise} canBlame={kmCanBlame} />
      </div>
    </section>
  )
}
