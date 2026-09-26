import { useEffect, useState } from 'react'

import { api } from '../api'
import { hhmm, minutes } from '../colors'
import type { LatLon } from '../geo'
import type { EngineerState } from '../sim'
import type { Plan, PlanEvent, Scenario, WorkType } from '../types'

export type Kind = 'urgent_order' | 'new_order' | 'cancel_order' | 'engineer_unavailable' | 'engineer_delayed'

export const KIND_TITLE: Record<Kind, string> = {
  urgent_order: 'Авария',
  new_order: 'Новая заявка',
  cancel_order: 'Отмена',
  engineer_unavailable: 'Инженер недоступен',
  engineer_delayed: 'Задержка',
}

const WINDOW_STARTS = ['10:00', '12:00', '14:00', '16:00', '18:00']

function initialEngineerId(plan: Plan, scenario: Scenario, states: EngineerState[], clock: number): string {
  const nextAvailable = states
    .filter((state) => state.done < state.total && ['idle', 'onsite', 'waiting'].includes(state.status) && (state.until ?? 0) > clock)
    .sort((a, b) => (a.until ?? Infinity) - (b.until ?? Infinity))[0]
  const busiestRoute = [...plan.routes].filter((route) => route.stops.length).sort((a, b) => b.stops.length - a.stops.length)[0]
  return nextAvailable?.engineerId ?? busiestRoute?.engineer_id ?? scenario.engineers[0]?.id ?? ''
}

function openWindowStarts(clock: number): string[] {
  return WINDOW_STARTS.filter((start) => minutes(start) + 120 > clock)
}

function cancellableOrderIds(plan: Plan, clock: number): string[] {
  return plan.routes
    .flatMap((route) => route.stops)
    .filter((stop) => !stop.locked && minutes(stop.arrival) - stop.travel_min > clock)
    .map((stop) => stop.order_id)
    .sort()
}

function newOrderLocation(prefix: string, scenario: Scenario, anchor: string, picked: LatLon | null) {
  const base = scenario.orders.find((order) => order.id === anchor)
  let n = 100
  while (scenario.orders.some((order) => order.id === `${prefix}-${n}`)) n += 1
  const lat = picked ? picked[0] : base?.lat ?? null
  const lon = picked ? picked[1] : base?.lon ?? null
  return {
    id: `${prefix}-${n}`,
    address: picked ? `Точка ${lat!.toFixed(5)}, ${lon!.toFixed(5)}` : base?.address ?? '',
    district: picked ? '' : base?.district ?? '',
    lat,
    lon,
    geocode_quality: 'manual',
  }
}

export function SimulationEventForm({
  kind,
  plan,
  scenario,
  clock,
  states,
  picked,
  busy,
  onCancel,
  onAdd,
}: {
  kind: Kind
  plan: Plan
  scenario: Scenario
  clock: number
  states: EngineerState[]
  picked: LatLon | null
  busy: boolean
  onCancel: () => void
  onAdd: (event: PlanEvent) => void
}) {
  const time = hhmm(Math.floor(clock))
  const [engineerId, setEngineerId] = useState(() => initialEngineerId(plan, scenario, states, clock))
  const [delay, setDelay] = useState(30)
  const [anchor, setAnchor] = useState(scenario.orders[0]?.id ?? '')
  const [duration, setDuration] = useState<number | null>(null)
  const [workTypes, setWorkTypes] = useState<WorkType[]>([])
  const [workType, setWorkType] = useState('')
  const emergency = workTypes.find((item) => item.priority === 'urgent')
  const regular = workTypes.filter((item) => item.priority === 'normal')
  const chosen = regular.find((item) => item.work_type === workType) ?? regular[0]
  const emergencyDuration = duration ?? emergency?.duration_min
  const windows = openWindowStarts(clock)
  const [windowStart, setWindowStart] = useState(windows[windows.length > 1 ? 1 : 0] ?? '')
  const windowFrom = windows.includes(windowStart) ? windowStart : windows[0]

  useEffect(() => {
    if (kind !== 'new_order' && kind !== 'urgent_order') return
    let cancelled = false
    api
      .workTypes()
      .then((items) => !cancelled && setWorkTypes(items))
      .catch(() => !cancelled && setWorkTypes([]))
    return () => {
      cancelled = true
    }
  }, [kind])
  const cancellable = cancellableOrderIds(plan, clock)
  const [cancelId, setCancelId] = useState(cancellable[0] ?? '')
  const cancelTarget = cancellable.includes(cancelId) ? cancelId : cancellable[0]

  function submit() {
    if (kind === 'urgent_order') {
      if (!emergency || !emergencyDuration) return
      onAdd({
        type: 'urgent_order',
        time,
        order: {
          ...newOrderLocation('SOS', scenario, anchor, picked),
          skill: emergency.skill,
          work_type: emergency.work_type,
          description: 'Авария',
          duration_min: emergencyDuration,
          window_start: time,
          window_end: '23:59',
          priority: 'urgent',
          priority_tier: emergency.priority_tier,
        },
      })
    } else if (kind === 'new_order') {
      if (!chosen || !windowFrom) return
      onAdd({
        type: 'new_order',
        time,
        order: {
          ...newOrderLocation('NEW', scenario, anchor, picked),
          skill: chosen.skill,
          work_type: chosen.work_type,
          description: chosen.normative,
          duration_min: chosen.duration_min,
          window_start: windowFrom,
          window_end: hhmm(minutes(windowFrom) + 120),
          priority: 'normal',
          priority_tier: chosen.priority_tier,
        },
      })
    } else if (kind === 'cancel_order') {
      if (cancelTarget) onAdd({ type: 'cancel_order', time, order_id: cancelTarget })
    } else if (kind === 'engineer_unavailable') {
      onAdd({ type: 'engineer_unavailable', time, engineer_id: engineerId })
    } else {
      onAdd({ type: 'engineer_delayed', time, engineer_id: engineerId, minutes: delay })
    }
  }

  const engineerSelect = (
    <label className="field">
      <span className="field-label">Инженер</span>
      <select value={engineerId} onChange={(e) => setEngineerId(e.target.value)}>
        {scenario.engineers.map((engineer) => {
          const n = plan.routes.find((r) => r.engineer_id === engineer.id)?.stops.length ?? 0
          return (
            <option key={engineer.id} value={engineer.id}>
              {engineer.name} · {n} виз.
            </option>
          )
        })}
      </select>
    </label>
  )

  return (
    <div className="ev-form">
      {(kind === 'urgent_order' || kind === 'new_order') && (
        <>
          <label className="field">
            <span className="field-label">Адрес{picked ? ', точка на карте' : ''}</span>
            {picked ? (
              <div className="picked">
                {picked[0].toFixed(5)}, {picked[1].toFixed(5)}
              </div>
            ) : (
              <select value={anchor} onChange={(e) => setAnchor(e.target.value)}>
                {scenario.orders.map((order) => (
                  <option key={order.id} value={order.id}>
                    {order.district ? `${order.district}, ` : ''}
                    {order.address}
                  </option>
                ))}
              </select>
            )}
            <span className="small muted">или щёлкните по карте</span>
          </label>
          {kind === 'urgent_order' && (
            <label className="field">
              <span className="field-label">Работа, мин</span>
              <input type="number" min={10} max={480} value={emergencyDuration ?? ''} disabled={!emergency} onChange={(e) => setDuration(Number(e.target.value))} />
              {emergency && <span className="small muted">норматив {emergency.duration_min} мин</span>}
            </label>
          )}
        </>
      )}
      {kind === 'new_order' && (
        <>
          <label className="field">
            <span className="field-label">Тип работ</span>
            <select value={chosen?.work_type ?? ''} onChange={(e) => setWorkType(e.target.value)}>
              {!workTypes.length && <option value="">…</option>}
              {workTypes.map((item) => (
                <option key={item.work_type} value={item.work_type}>
                  {item.work_type}, {item.duration_min} мин
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">Окно клиента</span>
            <select value={windowFrom ?? ''} onChange={(e) => setWindowStart(e.target.value)}>
              {!windows.length && <option value="">окна на сегодня закрыты</option>}
              {windows.map((start) => (
                <option key={start} value={start}>
                  {start}–{hhmm(minutes(start) + 120)}
                </option>
              ))}
            </select>
          </label>
        </>
      )}
      {kind === 'cancel_order' && (
        <label className="field">
          <span className="field-label">Заявка</span>
          <select value={cancelTarget ?? ''} onChange={(e) => setCancelId(e.target.value)}>
            {!cancellable.length && <option value="">все визиты уже начаты</option>}
            {cancellable.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
      )}
      {(kind === 'engineer_unavailable' || kind === 'engineer_delayed') && engineerSelect}
      {kind === 'engineer_delayed' && (
        <div className="seg" role="radiogroup" aria-label="На сколько">
          {[15, 30, 45, 60, 90].map((m) => (
            <button key={m} type="button" role="radio" aria-checked={delay === m} className={delay === m ? 'on' : ''} onClick={() => setDelay(m)}>
              {m} мин
            </button>
          ))}
        </div>
      )}
      <div className="ev-form-actions">
        <button type="button" className="primary" disabled={busy || (kind === 'cancel_order' && !cancelTarget) || (kind === 'new_order' && (!chosen || !windowFrom)) || (kind === 'urgent_order' && (!emergency || !emergencyDuration))} onClick={submit}>
          Добавить и перестроить
        </button>
        <button type="button" className="ghost" onClick={onCancel}>
          Отмена
        </button>
      </div>
    </div>
  )
}
