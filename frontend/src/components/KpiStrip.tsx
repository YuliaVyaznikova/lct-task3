import { effectiveTier, km, plural, signed } from '../labels'
import type { JobProgress, Metrics, Plan, Scenario } from '../types'

export interface KpiView {
  assigned: number
  total: number
  engineersUsed: number
  engineersTotal: number
  km: number
  unplaced: number
  rescheduled: number
  tiers: { tier: number; assigned: number; total: number }[]
  response: { median: number; max: number; over: number; measured: number } | null
}

const TIER_NAME: Record<number, string> = { 1: 'аварии', 2: 'подключения', 3: 'ремонт' }

function tiersFor(scenario: Scenario, assigned: Set<string>) {
  const rows = new Map<number, { tier: number; assigned: number; total: number }>()
  for (const order of scenario.orders) {
    const tier = effectiveTier(order)
    const row = rows.get(tier) ?? { tier, assigned: 0, total: 0 }
    row.total += 1
    if (assigned.has(order.id)) row.assigned += 1
    rows.set(tier, row)
  }
  return [...rows.values()].sort((a, b) => a.tier - b.tier)
}

export function kpiFromPlan(plan: Plan, scenario: Scenario): KpiView {
  const m = plan.metrics
  const assigned = new Set(plan.routes.flatMap((r) => r.stops.map((s) => s.order_id)))
  return {
    assigned: m.assigned,
    total: m.orders_total,
    engineersUsed: m.engineers_used,
    engineersTotal: m.engineers_total,
    km: m.distance_total_km,
    unplaced: plan.unassigned.length,
    rescheduled: m.rescheduled,
    tiers: tiersFor(scenario, assigned),
    response: m.response_measured
      ? { median: m.response_median_min, max: m.response_max_min, over: m.response_over_norm, measured: m.response_measured }
      : null,
  }
}

export function kpiFromProgress(p: JobProgress, scenario: Scenario): KpiView {
  const assigned = new Set(Object.values(p.routes ?? {}).flat())
  return {
    assigned: p.assigned,
    total: p.total,
    engineersUsed: p.engineers_used,
    engineersTotal: scenario.engineers.length,
    km: p.distance_km,
    unplaced: Math.max(0, p.total - p.assigned),
    rescheduled: 0,
    tiers: tiersFor(scenario, assigned),
    response: null,
  }
}

const pct = (a: number, b: number) => (b ? Math.round((a / b) * 100) : 0)

interface Props {
  view: KpiView
  live: boolean
  before: Metrics | null
  baseline: Metrics | null
  onUnplaced: () => void
  onCompare: () => void
}

function Delta({ value, digits = 0, lowerIsBetter = false, unit = '' }: { value: number; digits?: number; lowerIsBetter?: boolean; unit?: string }) {
  const rounded = Number(value.toFixed(digits))
  if (rounded === 0) return <span className="delta-chip">±0{unit}</span>
  const good = lowerIsBetter ? rounded < 0 : rounded > 0
  return (
    <span className={`delta-chip ${good ? 'good' : 'bad'}`}>
      {signed(rounded, digits)}
      {unit}
    </span>
  )
}

export function KpiStrip({ view, live, before, baseline, onUnplaced, onCompare }: Props) {
  const v = view
  return (
    <section className={`kpis ${live ? 'live' : ''}`} aria-label="Сводка плана" aria-live={live ? 'polite' : undefined}>
      <div className="kpi">
        <div className="kpi-line">
          <b className="kpi-value">{v.assigned}</b>
          <span className="kpi-unit">из {v.total} заявок</span>
          {before && <Delta value={v.assigned - before.assigned} />}
        </div>
        <div className="tier-bar" aria-hidden>
          {v.tiers.map((t) => (
            <span key={t.tier} className={`tier-seg t${t.tier}`} style={{ flexGrow: t.total }}>
              <i style={{ width: `${pct(t.assigned, t.total)}%` }} />
            </span>
          ))}
        </div>
        <div className="kpi-legend">
          {v.tiers.map((t) => (
            <span key={t.tier} className={t.assigned < t.total ? 'short' : ''}>
              <i className={`tier-dot t${t.tier}`} />
              {TIER_NAME[t.tier] ?? `ярус ${t.tier}`} {t.assigned}/{t.total}
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
        </div>
      </div>

      <div className="kpi">
        <div className="kpi-line">
          <b className="kpi-value">{v.engineersUsed}</b>
          <span className="kpi-unit">из {v.engineersTotal} инженеров</span>
          {before && <Delta value={v.engineersUsed - before.engineers_used} lowerIsBetter />}
        </div>
        <div className="thin-bar">
          <i style={{ width: `${pct(v.engineersUsed, v.engineersTotal)}%` }} />
        </div>
        <div className="kpi-legend">
          <span>{pct(v.engineersUsed, v.engineersTotal)}% выезжают</span>
          <span>
            {v.engineersTotal - v.engineersUsed > 0 ? `${v.engineersTotal - v.engineersUsed} в резерве` : 'резерва нет'}
          </span>
        </div>
      </div>

      <div className="kpi">
        <div className="kpi-line">
          <b className="kpi-value">{km(v.km, 0)}</b>
          <span className="kpi-unit">км</span>
          {before && <Delta value={v.km - before.distance_total_km} digits={1} lowerIsBetter unit=" км" />}
        </div>
        <div className="kpi-sub">{v.assigned ? km(v.km / v.assigned, 1) : '0'} км на заявку</div>
      </div>

      <button type="button" className={`kpi kpi-action ${v.unplaced ? 'warn' : 'ok'}`} onClick={onUnplaced}>
        <span className="kpi-line">
          <b className="kpi-value">{v.unplaced}</b>
          <span className="kpi-unit">{plural(v.unplaced, 'не размещена', 'не размещены', 'не размещены')}</span>
          {before && <Delta value={v.unplaced - before.unassigned} lowerIsBetter />}
        </span>
        <span className="thin-bar amber">
          <i style={{ width: `${pct(v.unplaced, v.total)}%` }} />
        </span>
        <span className="kpi-legend">
          <span>{pct(v.unplaced, v.total)}%</span>
          {v.rescheduled > 0 && <span className="warn-text">сдвинуто время у {v.rescheduled}</span>}
        </span>
      </button>

      {baseline && !live && (
        <button type="button" className="kpi was-now" onClick={onCompare} title="Сравнение с базовым">
          <span className="was-title">Базовый → план</span>
          <span className="was-row">
            <span>заявки</span>
            <b>
              {baseline.assigned} → {v.assigned}
            </b>
          </span>
          <span className="was-row">
            <span>инженеры</span>
            <b>
              {baseline.engineers_used} → {v.engineersUsed}
            </b>
          </span>
          <span className="was-row">
            <span>км</span>
            <b>
              {km(baseline.distance_total_km, 0)} → {km(v.km, 0)}
            </b>
          </span>
        </button>
      )}
    </section>
  )
}
