import { useState } from 'react'

import type { PlanEvent, Scenario, Plan } from '../types'

type Kind = 'urgent_order' | 'cancel_order' | 'engineer_unavailable'

const TITLE: Record<Kind, string> = {
  urgent_order: 'Срочная заявка',
  cancel_order: 'Отмена заявки',
  engineer_unavailable: 'Инженер недоступен',
}

interface Props {
  scenario: Scenario
  plan: Plan
  pickedPoint: { lat: number; lon: number } | null
  busy: boolean
  onApply: (event: PlanEvent) => void
}

/** Форма события для диспетчера: одно из трёх, как требует ТЗ §2.1.6. */
export function EventPanel({ scenario, plan, busy, onApply }: Props) {
  const [kind, setKind] = useState<Kind>('urgent_order')
  const [time, setTime] = useState('12:30')

  // Срочная заявка
  const [anchor, setAnchor] = useState(scenario.orders[0]?.id ?? '')
  const [duration, setDuration] = useState(80)

  // Отмена: только те, что ещё не начаты к моменту события
  const cancellable = plan.routes
    .flatMap((route) => route.stops)
    .filter((stop) => stop.arrival > time)
    .map((stop) => stop.order_id)
  const [cancelId, setCancelId] = useState('')

  const busiest = [...plan.routes].sort((a, b) => b.stops.length - a.stops.length)[0]
  const [engineerId, setEngineerId] = useState(busiest?.engineer_id ?? '')

  const ready =
    kind === 'urgent_order'
      ? Boolean(anchor)
      : kind === 'cancel_order'
        ? Boolean(cancelId || cancellable[0])
        : Boolean(engineerId)

  function apply() {
    if (kind === 'urgent_order') {
      const base = scenario.orders.find((o) => o.id === anchor)
      if (!base) return
      const id = `SOS-${Math.floor(Math.random() * 900 + 100)}`
      onApply({
        type: 'urgent_order',
        time,
        order: {
          id,
          address: `${base.address} (авария)`,
          district: base.district,
          lat: base.lat,
          lon: base.lon,
          skill: 'emergency',
          work_type: 'Глобальная проблема',
          description: 'Авария',
          duration_min: duration,
          window_start: time,
          window_end: '23:59',
          priority: 'urgent',
        } as never,
      })
    } else if (kind === 'cancel_order') {
      onApply({ type: 'cancel_order', time, order_id: cancelId || cancellable[0] })
    } else {
      onApply({ type: 'engineer_unavailable', time, engineer_id: engineerId })
    }
  }

  return (
    <div className="panel">
      <h2>Событие в течение дня</h2>
      <div className="row" style={{ gap: 4, marginBottom: 10, flexWrap: 'wrap' }}>
        {(Object.keys(TITLE) as Kind[]).map((key) => (
          <button
            key={key}
            className={kind === key ? 'primary' : ''}
            style={{ fontSize: 12, padding: '4px 8px' }}
            onClick={() => setKind(key)}
          >
            {TITLE[key]}
          </button>
        ))}
      </div>

      <div className="field">
        <label>Время события</label>
        <input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
      </div>

      {kind === 'urgent_order' && (
        <>
          <div className="field">
            <label>Адрес (берём у существующей заявки)</label>
            <select value={anchor} onChange={(e) => setAnchor(e.target.value)}>
              {scenario.orders.slice(0, 200).map((order) => (
                <option key={order.id} value={order.id}>
                  {order.district}, {order.address}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Длительность, мин (норматив аварии — 80)</label>
            <input
              type="number"
              min={10}
              max={480}
              value={duration}
              onChange={(e) => setDuration(Number(e.target.value))}
            />
          </div>
        </>
      )}

      {kind === 'cancel_order' && (
        <div className="field">
          <label>Какую заявку отменяем</label>
          <select value={cancelId} onChange={(e) => setCancelId(e.target.value)}>
            <option value="">— ближайшая подходящая —</option>
            {cancellable.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
          {!cancellable.length && (
            <div className="small muted">
              К этому времени все визиты уже начаты — отменять нечего.
            </div>
          )}
        </div>
      )}

      {kind === 'engineer_unavailable' && (
        <div className="field">
          <label>Кто выбывает</label>
          <select value={engineerId} onChange={(e) => setEngineerId(e.target.value)}>
            {scenario.engineers.map((engineer) => {
              const route = plan.routes.find((r) => r.engineer_id === engineer.id)
              return (
                <option key={engineer.id} value={engineer.id}>
                  {engineer.name} ({route?.stops.length ?? 0} визитов)
                </option>
              )
            })}
          </select>
        </div>
      )}

      <button className="primary" style={{ width: '100%' }} disabled={busy || !ready} onClick={apply}>
        {busy ? 'Перестраиваем…' : 'Перестроить план'}
      </button>
      <p className="small muted" style={{ marginBottom: 0 }}>
        Визиты, начатые до времени события, останутся неизменными.
      </p>
    </div>
  )
}
