import { useEffect, useState } from 'react'

import { api } from '../api'
import { engineerColor, formatMinutes } from '../colors'
import type {
  ControlReference,
  Diff,
  MetricRow,
  OrderExplanation,
  Plan,
  Scenario,
} from '../types'
import { SKILL_RU, TRANSPORT_RU } from '../types'

/* ------------------------------------------------------------ маршруты */

export function RoutesTable({
  scenario,
  plan,
  selectedOrder,
  selectedEngineer,
  onSelectOrder,
  onSelectEngineer,
}: {
  scenario: Scenario
  plan: Plan
  selectedOrder: string | null
  selectedEngineer: string | null
  onSelectOrder: (id: string) => void
  onSelectEngineer: (id: string | null) => void
}) {
  const engineerIds = scenario.engineers.map((e) => e.id)
  const ordersById = Object.fromEntries(scenario.orders.map((o) => [o.id, o]))
  const routes = plan.routes.filter((r) => r.stops.length)

  if (!routes.length) return <p className="muted" style={{ padding: 12 }}>Маршрутов нет.</p>

  return (
    <div>
      {routes
        .filter((r) => selectedEngineer === null || r.engineer_id === selectedEngineer)
        .map((route) => {
          const engineer = scenario.engineers.find((e) => e.id === route.engineer_id)!
          const color = engineerColor(engineerIds, route.engineer_id)
          return (
            <div key={route.engineer_id} style={{ marginBottom: 6 }}>
              <div
                className="panel"
                style={{ padding: '8px 12px', cursor: 'pointer', borderLeft: `4px solid ${color}` }}
                onClick={() =>
                  onSelectEngineer(selectedEngineer === route.engineer_id ? null : route.engineer_id)
                }
              >
                <b>{engineer.name}</b>{' '}
                <span className="muted small">
                  {TRANSPORT_RU[engineer.transport]} · {engineer.shift_start}–{engineer.shift_end} ·{' '}
                  {engineer.skills.map((s) => SKILL_RU[s]).join(', ')}
                </span>
                <div className="small muted mono">
                  {route.stops.length} визитов · {route.distance_km.toFixed(1)} км ·{' '}
                  {formatMinutes(route.travel_min)} в пути · до {route.end_time}
                </div>
              </div>
              <table>
                <tbody>
                  {route.stops.map((stop) => {
                    const order = ordersById[stop.order_id]
                    return (
                      <tr
                        key={stop.order_id}
                        className={`clickable${selectedOrder === stop.order_id ? ' selected' : ''}`}
                        onClick={() => onSelectOrder(stop.order_id)}
                      >
                        <td className="mono muted" style={{ width: 22 }}>
                          {stop.seq}
                        </td>
                        <td className="mono" style={{ width: 92 }}>
                          {stop.start}–{stop.finish}
                          {stop.locked && (
                            <div className="small muted" title="Выполнено до события">
                              зафиксир.
                            </div>
                          )}
                          {stop.late_min > 0 && (
                            <div
                              className="small"
                              style={{ color: 'var(--bad)' }}
                              title="Время сдвинуто относительно обещанного клиенту — нужен звонок службы поддержки"
                            >
                              +{stop.late_min} мин
                            </div>
                          )}
                        </td>
                        <td>
                          <span className="mono">{order?.id}</span>{' '}
                          {order?.priority === 'urgent' && <span className="badge urgent">срочная</span>}
                          <div className="small muted">
                            {order?.district}, {order?.address}
                          </div>
                        </td>
                        <td className="mono muted small" style={{ width: 54, textAlign: 'right' }}>
                          {stop.travel_km.toFixed(1)} км
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )
        })}
    </div>
  )
}

/* ------------------------------------------------------- неназначенные */

const REASON_TITLE: Record<string, string> = {
  NO_SKILL: 'нет навыка',
  NO_TRANSPORT: 'нет транспорта',
  SHIFT_MISMATCH: 'окно вне смен',
  UNREACHABLE: 'слишком далеко',
  CAPACITY: 'не хватило мощности',
  NO_COORDS: 'нет координат',
  MANUAL: 'снята вручную',
}

export function UnassignedList({
  scenario,
  plan,
  selectedOrder,
  onSelectOrder,
}: {
  scenario: Scenario
  plan: Plan
  selectedOrder: string | null
  onSelectOrder: (id: string) => void
}) {
  const ordersById = Object.fromEntries(scenario.orders.map((o) => [o.id, o]))
  if (!plan.unassigned.length) {
    return (
      <p className="muted" style={{ padding: 12 }}>
        Все заявки распределены.
      </p>
    )
  }
  return (
    <table>
      <thead>
        <tr>
          <th>Заявка</th>
          <th>Причина</th>
        </tr>
      </thead>
      <tbody>
        {plan.unassigned.map((item) => {
          const order = ordersById[item.order_id]
          return (
            <tr
              key={item.order_id}
              className={`clickable${selectedOrder === item.order_id ? ' selected' : ''}`}
              onClick={() => onSelectOrder(item.order_id)}
            >
              <td style={{ width: 130 }}>
                <span className="mono">{item.order_id}</span>
                <div className="small muted">
                  {order && `${SKILL_RU[order.skill]}, ${order.window_start}–${order.window_end}`}
                </div>
              </td>
              <td>
                <span className="badge">{REASON_TITLE[item.reason_code] ?? item.reason_code}</span>
                <div className="small">{item.reason}</div>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

/* ---------------------------------------------------------- метрики */

export function MetricsPanel({
  plan,
  comparison,
  control,
}: {
  plan: Plan
  comparison: MetricRow[]
  control: ControlReference | null
}) {
  const m = plan.metrics
  return (
    <div style={{ padding: 12 }}>
      <div className="stat-grid" style={{ marginBottom: 12 }}>
        <div className="stat">
          <div className="value">
            {m.assigned}
            <span className="muted" style={{ fontSize: 14 }}>
              /{m.orders_total}
            </span>
          </div>
          <div className="label">назначено заявок</div>
        </div>
        <div className="stat">
          <div className="value">
            {m.engineers_used}
            <span className="muted" style={{ fontSize: 14 }}>
              /{m.engineers_total}
            </span>
          </div>
          <div className="label">задействовано инженеров</div>
        </div>
        <div className="stat">
          <div className="value">{m.distance_total_km.toFixed(0)}</div>
          <div className="label">пробег, км</div>
        </div>
        <div className="stat">
          <div className="value">{m.distance_per_order_km.toFixed(1)}</div>
          <div className="label">км на заявку</div>
        </div>
      </div>

      {m.rescheduled > 0 && (
        <p className="small" style={{ color: 'var(--bad)', marginTop: -6 }}>
          Перенесено за пределы обещанного окна: {m.rescheduled}. Службе поддержки
          нужно предупредить клиентов.
        </p>
      )}

      <h2 style={{ fontSize: 12, color: 'var(--muted)' }}>Сравнение с базовым вариантом</h2>
      <p className="small muted" style={{ marginTop: -4 }}>
        Базовый вариант задан в ТЗ §2.3: заявки в порядке поступления — первому подходящему
        инженеру, без оптимизации.
      </p>
      <table>
        <thead>
          <tr>
            <th>Показатель</th>
            <th style={{ textAlign: 'right' }}>Наш</th>
            <th style={{ textAlign: 'right' }}>Базовый</th>
            <th style={{ textAlign: 'right' }}>Δ</th>
          </tr>
        </thead>
        <tbody>
          {comparison.map((row, index) => (
            <tr key={row.key}>
              <td>
                {row.title}
                {index < 2 && (
                  <span className="badge" style={{ marginLeft: 6 }} title="Обязательная метрика ТЗ">
                    ТЗ
                  </span>
                )}
              </td>
              <td className="mono" style={{ textAlign: 'right' }}>
                {row.ours.toFixed(row.key.includes('km') ? 1 : 0)}
              </td>
              <td className="mono muted" style={{ textAlign: 'right' }}>
                {row.baseline.toFixed(row.key.includes('km') ? 1 : 0)}
              </td>
              <td
                className={`mono delta ${row.better === null ? '' : row.better ? 'good' : 'bad'}`}
                style={{ textAlign: 'right' }}
              >
                {row.delta > 0 ? '+' : ''}
                {row.delta.toFixed(row.key.includes('km') ? 1 : 0)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {control?.available && (
        <>
          <h2 style={{ fontSize: 12, color: 'var(--muted)', marginTop: 16 }}>
            Справочно: как распределили вручную
          </h2>
          <p className="small muted" style={{ marginTop: -4 }}>
            Контрольный файл выгрузки — не эталон, а факт того же дня. В расчётах
            не используется.
          </p>
          <table>
            <thead>
              <tr>
                <th>Показатель</th>
                <th style={{ textAlign: 'right' }}>Наш</th>
                <th style={{ textAlign: 'right' }}>Факт</th>
              </tr>
            </thead>
            <tbody>
              {control.rows.map((row) => (
                <tr key={row.title}>
                  <td>{row.title}</td>
                  <td className="mono" style={{ textAlign: 'right' }}>
                    {row.ours.toFixed(1)}
                  </td>
                  <td className="mono muted" style={{ textAlign: 'right' }}>
                    {row.control.toFixed(1)}
                  </td>
                </tr>
              ))}
              {control.late_starts > 0 && (
                <tr>
                  <td>Визитов начато позже окна</td>
                  <td className="mono delta good" style={{ textAlign: 'right' }}>
                    0
                  </td>
                  <td className="mono delta bad" style={{ textAlign: 'right' }}>
                    {control.late_starts}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          <p className="small" style={{ marginTop: 6 }}>
            {control.summary}
          </p>
        </>
      )}

      <h2 style={{ fontSize: 12, color: 'var(--muted)', marginTop: 16 }}>Пробег по инженерам</h2>
      <table>
        <tbody>
          {Object.entries(m.distance_by_engineer)
            .sort((a, b) => b[1] - a[1])
            .map(([id, km]) => (
              <tr key={id}>
                <td>{id}</td>
                <td className="mono" style={{ textAlign: 'right', width: 70 }}>
                  {km.toFixed(1)} км
                </td>
                <td className="mono muted" style={{ textAlign: 'right', width: 60 }}>
                  {Math.round((m.utilization_by_engineer[id] ?? 0) * 100)}%
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  )
}

/* ------------------------------------------------------------- diff */

export function DiffView({ diff, scenario }: { diff: Diff | null; scenario: Scenario }) {
  if (!diff) {
    return (
      <p className="muted" style={{ padding: 12 }}>
        Событий ещё не было. Добавьте срочную заявку, отмените существующую или сделайте
        инженера недоступным — здесь появится список изменений.
      </p>
    )
  }
  const name = (id: string | null) =>
    scenario.engineers.find((e) => e.id === id)?.name ?? id ?? '—'

  return (
    <div>
      <div className="summary">{diff.summary}</div>
      <div style={{ padding: '0 12px 12px' }}>
        <div className="small muted" style={{ marginBottom: 8 }}>
          Зафиксировано визитов, начатых до события: {diff.locked_stops}
        </div>
        {diff.changed.length > 0 && (
          <>
            <h2 style={{ fontSize: 12, color: 'var(--muted)' }}>Изменённые назначения</h2>
            <table>
              <thead>
                <tr>
                  <th>Заявка</th>
                  <th>Было</th>
                  <th>Стало</th>
                </tr>
              </thead>
              <tbody>
                {diff.changed.map((change) => (
                  <tr key={change.order_id}>
                    <td className="mono">{change.order_id}</td>
                    <td className="small">
                      {name(change.from_engineer)}
                      <div className="mono muted">{change.from_start}</div>
                    </td>
                    <td className="small">
                      {name(change.to_engineer)}
                      <div className="mono muted">{change.to_start}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
        {[
          ['Добавлены', diff.added],
          ['Удалены', diff.removed],
          ['Удалось разместить', diff.newly_assigned],
          ['Выпали из плана', diff.newly_unassigned],
        ]
          .filter(([, list]) => (list as string[]).length)
          .map(([title, list]) => (
            <p key={title as string} className="small">
              <b>{title as string}:</b> <span className="mono">{(list as string[]).join(', ')}</span>
            </p>
          ))}
      </div>
    </div>
  )
}

/* ---------------------------------------------------- карточка заявки */

export function OrderCard({
  planId,
  scenario,
  orderId,
  onClose,
  onManual,
}: {
  planId: string
  scenario: Scenario
  orderId: string
  onClose: () => void
  onManual: (orderId: string, engineerId: string | null) => void
}) {
  const [card, setCard] = useState<
    (OrderExplanation & { assigned: boolean; reason?: string; reason_code?: string }) | null
  >(null)
  const [error, setError] = useState<string | null>(null)
  const order = scenario.orders.find((o) => o.id === orderId)

  useEffect(() => {
    setCard(null)
    setError(null)
    api
      .explain(planId, orderId)
      .then(setCard)
      .catch((e) => setError(e.message))
  }, [planId, orderId])

  if (!order) return null

  return (
    <div className="card">
      <div className="row">
        <h3 className="grow">
          {order.id}{' '}
          {order.priority === 'urgent' && <span className="badge urgent">срочная</span>}
        </h3>
        <button onClick={onClose}>×</button>
      </div>
      <div className="small muted" style={{ marginBottom: 8 }}>
        {order.work_type} / {order.description}
        <br />
        {SKILL_RU[order.skill]} · {order.duration_min} мин · окно {order.window_start}–
        {order.window_end}
        {order.required_transport && ` · требуется ${TRANSPORT_RU[order.required_transport]}`}
        <br />
        {order.district}, {order.address}
      </div>

      {error && <div className="error">{error}</div>}
      {!card && !error && (
        <div className="muted small">
          <span className="spinner" />
          загружаем объяснение…
        </div>
      )}

      {card?.assigned && (
        <>
          <b className="small">{card.headline}</b>
          <ul>
            {card.checks.map((check, i) => (
              <li key={i} className={check.ok ? 'check-ok' : 'check-bad'}>
                {check.text}
              </li>
            ))}
          </ul>
          <div className="small muted">{card.travel}</div>
          {card.alternatives.length > 0 && (
            <>
              <div className="small" style={{ marginTop: 8, fontWeight: 600 }}>
                Альтернативы
              </div>
              <ul className="small">
                {card.alternatives.map((text, i) => (
                  <li key={i}>{text}</li>
                ))}
              </ul>
            </>
          )}
          <div className="small" style={{ marginTop: 6 }}>
            {card.why}
          </div>
        </>
      )}

      {card && !card.assigned && (
        <>
          <span className="badge">{REASON_TITLE[card.reason_code ?? ''] ?? 'не назначена'}</span>
          <p className="small">{card.reason}</p>
        </>
      )}

      <div className="row" style={{ marginTop: 10, gap: 6 }}>
        <select
          className="grow"
          defaultValue=""
          onChange={(event) => {
            const value = event.target.value
            if (value) onManual(orderId, value === '__none__' ? null : value)
            event.target.value = ''
          }}
        >
          <option value="">Переназначить вручную…</option>
          <option value="__none__">— снять с маршрута —</option>
          {scenario.engineers.map((engineer) => (
            <option key={engineer.id} value={engineer.id}>
              {engineer.name} ({TRANSPORT_RU[engineer.transport]})
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}
