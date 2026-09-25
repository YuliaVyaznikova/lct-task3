import { engineerComparison, tierCoverage } from '../derive'
import { km, plural, signed, TIER_LABEL } from '../labels'
import type { ControlReference, Metrics, Plan, Scenario } from '../types'
import { EngineerName } from './common'

export interface Matched {
  optimized: Plan
  baseline: Plan
  control: ControlReference
  scenario: Scenario
  manualEdits: number
}

interface Row {
  title: string
  ours: string
  base: string
  delta: string
  better: boolean | null
  hint?: string
  sub?: boolean
}

function pct(a: number, b: number) {
  return b ? Math.round((a / b) * 100) : 0
}

function comparisonRows(m: Metrics, b: Metrics, optimized: Plan, baseline: Plan, scenario: Scenario): Row[] {
  const tiersOurs = tierCoverage(optimized, scenario)
  const tiersBase = tierCoverage(baseline, scenario)
  const distanceBetter =
    m.assigned < b.assigned || m.distance_total_km === b.distance_total_km
      ? null
      : m.distance_total_km < b.distance_total_km
  const result: Row[] = [
    {
      title: 'Выполнено заявок',
      ours: `${m.assigned} из ${m.orders_total} (${pct(m.assigned, m.orders_total)}%)`,
      base: `${b.assigned} из ${b.orders_total} (${pct(b.assigned, b.orders_total)}%)`,
      delta: signed(m.assigned - b.assigned, 0),
      better: m.assigned === b.assigned ? null : m.assigned > b.assigned,
    },
  ]
  for (const tier of tiersOurs) {
    const other = tiersBase.find((t) => t.tier === tier.tier)
    const baseAssigned = other?.assigned ?? 0
    result.push({
      title: TIER_LABEL[tier.tier] ?? `Ярус ${tier.tier}`,
      ours: `${tier.assigned}/${tier.total}`,
      base: `${baseAssigned}/${tier.total}`,
      delta: signed(tier.assigned - baseAssigned, 0),
      better: tier.assigned === baseAssigned ? null : tier.assigned > baseAssigned,
      sub: true,
    })
  }
  result.push(
    {
      title: 'Инженеров выезжает',
      ours: `${m.engineers_used} из ${m.engineers_total}`,
      base: `${b.engineers_used} из ${b.engineers_total}`,
      delta: signed(m.engineers_used - b.engineers_used, 0),
      better: m.engineers_used === b.engineers_used ? null : m.engineers_used < b.engineers_used,
    },
    {
      title: 'Пробег за день, км',
      ours: km(m.distance_total_km),
      base: km(b.distance_total_km),
      delta: signed(m.distance_total_km - b.distance_total_km),
      better: distanceBetter,
      hint: m.assigned < b.assigned ? 'заявок меньше — сравнивать нельзя' : undefined,
    },
    {
      title: 'Км на выполненную заявку',
      ours: km(m.distance_per_order_km, 2),
      base: km(b.distance_per_order_km, 2),
      delta: signed(m.distance_per_order_km - b.distance_per_order_km, 2),
      better:
        m.distance_per_order_km === b.distance_per_order_km
          ? null
          : m.distance_per_order_km < b.distance_per_order_km,
    },
    {
      title: 'Начало впритык к концу окна',
      ours: String(m.late_risk),
      base: String(b.late_risk),
      delta: signed(m.late_risk - b.late_risk, 0),
      better: m.late_risk === b.late_risk ? null : m.late_risk < b.late_risk,
      hint: 'запас меньше 15 мин',
    },
  )
  if (m.response_measured > 0 || b.response_measured > 0) {
    result.push(
      {
        title: 'Реакция на аварию, медиана',
        ours: `${m.response_median_min} мин`,
        base: `${b.response_median_min} мин`,
        delta: signed(m.response_median_min - b.response_median_min, 0),
        better: m.response_median_min === b.response_median_min ? null : m.response_median_min < b.response_median_min,
        hint: `максимум ${m.response_max_min} мин`,
      },
      {
        title: 'Аварий дольше двух часов',
        ours: String(m.response_over_norm),
        base: String(b.response_over_norm),
        delta: signed(m.response_over_norm - b.response_over_norm, 0),
        better: m.response_over_norm === b.response_over_norm ? null : m.response_over_norm < b.response_over_norm,
        sub: true,
      },
    )
  }
  return result
}

function verdict(m: Metrics, b: Metrics, subject: string): string {
  const jobs = m.assigned - b.assigned
  const dist = m.distance_total_km - b.distance_total_km
  let jobsText = 'выполняет столько же заявок'
  if (jobs > 0) jobsText = `выполняет на ${jobs} ${plural(jobs, 'заявку', 'заявки', 'заявок')} больше`
  else if (jobs < 0) jobsText = `выполняет на ${-jobs} ${plural(-jobs, 'заявку', 'заявки', 'заявок')} меньше`

  let kmText: string
  if (Math.abs(dist) < 0.05) kmText = 'с тем же пробегом'
  else if (dist < 0) kmText = `и проезжает на ${km(-dist)} км меньше`
  else kmText = `и проезжает на ${km(dist)} км больше`
  let text = `${subject} ${jobsText} ${kmText}`
  if (jobs < 0 && dist < 0) text += ' — меньший пробег здесь не выигрыш, заявок выполнено меньше'
  return text + '.'
}

export function Comparison({ matched, eventState }: { matched: Matched; eventState: boolean }) {
  const { optimized, baseline, control, scenario } = matched
  const m = optimized.metrics
  const b = baseline.metrics
  const perEngineer = engineerComparison(scenario, optimized, baseline)
  const maxKm = Math.max(
    1,
    ...perEngineer.flatMap((row) => [row.optimized?.km ?? 0, row.baseline?.km ?? 0]),
  )

  return (
    <div className="comparison">
      <div className="cmp-col">
        <div className="cmp-meta muted small">
          {eventState ? `Исходный план ${optimized.id}, до событий` : `План ${optimized.id}`}
          {matched.manualEdits > 0 && ` · ручных правок: ${matched.manualEdits}`} · базовый {baseline.id}
        </div>

        <p className="verdict-line">По сравнению с базовым вариантом {verdict(m, b, eventState ? 'исходный план' : 'план')}</p>

        <table className="table compare-table">
          <thead>
            <tr>
              <th>Показатель</th>
              <th className="num">{eventState ? 'Исходный план' : 'Предлагаемый'}</th>
              <th className="num">Базовый</th>
              <th className="num">Разница</th>
            </tr>
          </thead>
          <tbody>
            {comparisonRows(m, b, optimized, baseline, scenario).map((row) => (
              <tr key={row.title} className={row.sub ? 'sub' : ''}>
                <td>
                  {row.title}
                  {row.hint && <div className="small muted">{row.hint}</div>}
                </td>
                <td className="num mono strong">{row.ours}</td>
                <td className="num mono">{row.base}</td>
                <td className={`num mono delta ${row.better === null ? '' : row.better ? 'good' : 'bad'}`}>
                  {row.delta}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {controlBlock(control, m, optimized, eventState)}
      </div>
      <div className="cmp-col">
        <h4 className="section-title">Пробег по инженерам</h4>
        <div className="legend-inline small">
          <span>
            <i className="swatch ours" /> {eventState ? 'исходный план' : 'предлагаемый'}
          </span>
          <span>
            <i className="swatch base" /> базовый
          </span>
        </div>
        <table className="table engineer-km">
          <thead>
            <tr>
              <th>Инженер</th>
              <th className="num">{eventState ? 'Исходный' : 'Предлагаемый'}</th>
              <th className="num">Базовый</th>
              <th className="bars-col" aria-hidden />
            </tr>
          </thead>
          <tbody>
            {perEngineer.map(({ engineer, optimized: o, baseline: base }) => (
              <tr key={engineer.id}>
                <td>
                  <EngineerName engineers={scenario.engineers} id={engineer.id} />
                </td>
                <td className="num mono">
                  {o ? (
                    <>
                      <b>{km(o.km)}</b> км <span className="muted">· {o.visits} виз.</span>
                    </>
                  ) : (
                    <span className="inactive">не выезжает · 0 км</span>
                  )}
                </td>
                <td className="num mono">
                  {base ? (
                    <>
                      {km(base.km)} км <span className="muted">· {base.visits} виз.</span>
                    </>
                  ) : (
                    <span className="inactive">не выезжает · 0 км</span>
                  )}
                </td>
                <td className="bars-col">
                  <div className="bar ours" style={{ width: `${((o?.km ?? 0) / maxKm) * 100}%` }} />
                  <div className="bar base" style={{ width: `${((base?.km ?? 0) / maxKm) * 100}%` }} />
                </td>
              </tr>
            ))}
            <tr className="total">
              <td>Итого</td>
              <td className="num mono">
                <b>{km(m.distance_total_km)}</b> км · {m.assigned} заявок
              </td>
              <td className="num mono">
                {km(b.distance_total_km)} км · {b.assigned} заявок
              </td>
              <td />
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}

function controlBlock(control: ControlReference, m: Metrics, optimized: Plan, eventState: boolean) {
  return (
    <>
      <h4 className="section-title">Факт того же дня, распределение вручную</h4>
      {control.available ? (
        <>
          <table className="table">
            <thead>
              <tr>
                <th>Показатель</th>
                <th className="num">{eventState ? 'Исходный план' : 'Предлагаемый'}</th>
                <th className="num">Факт (вручную)</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Выполнено заявок</td>
                <td className="num mono">
                  {m.assigned} из {m.orders_total}
                </td>
                <td className="num mono">
                  {control.covered_orders} из {m.orders_total}
                </td>
              </tr>
              {control.rows.map((row) => (
                <tr key={row.title}>
                  <td>{row.title}</td>
                  <td className="num mono">{row.title.includes('км') ? km(row.ours, 2) : row.ours}</td>
                  <td className="num mono">
                    {row.title.includes('км') ? km(row.control, 2) : row.control}
                  </td>
                </tr>
              ))}
              <tr>
                <td>Визитов начато позже обещанного окна</td>
                <td className="num mono">{optimized.metrics.rescheduled}</td>
                <td className={`num mono ${control.late_starts ? 'delta bad' : ''}`}>
                  {control.late_starts}
                </td>
              </tr>
            </tbody>
          </table>
          {control.summary && <p className="small">{control.summary}</p>}
          {control.covered_orders !== m.assigned && (
            <p className="small muted">
              Факт покрывает {control.covered_orders} заявок, план — {m.assigned}.
            </p>
          )}
        </>
      ) : (
        <p className="small muted">Фактического распределения для участка нет.</p>
      )}
    </>
  )
}
