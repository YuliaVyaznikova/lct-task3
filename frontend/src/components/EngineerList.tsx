import { cx } from '../classes'
import { useEngineerColor } from '../colors'
import { matchesFilter, toggled, type EngineerFilter } from '../engineer-filter'
import { ordersById, placeLabel } from '../derive'
import { km, SKILL_SHORT, TRANSPORT_RU } from '../labels'
import { STATUS_RU, type EngineerState } from '../sim'
import { startPlaces, type LatLon } from '../geo'
import type { Engineer, Plan, Scenario, Skill, Transport } from '../types'
import { LockIcon } from './common'
import { PLACE_TITLE, PlaceMark } from './PlaceCard'
import { TransportIcon } from './TransportIcon'

interface EngineerListProps {
  scenario: Scenario
  plan: Plan | null
  liveRoutes: Record<string, string[]> | null
  selected: string | null
  selectedOrder: string | null
  onSelect: (id: string | null) => void
  onSelectOrder: (id: string) => void
  simStates: Record<string, EngineerState> | null
  unavailable: Set<string>
  group: Set<string> | null
  onGoToPlace: (point: LatLon) => void
  filter: EngineerFilter
  onFilter: (filter: EngineerFilter) => void
  onHover: (id: string | null) => void
}

interface FilterChipsProps {
  scenario: Scenario
  filter: EngineerFilter
  onFilter: (filter: EngineerFilter) => void
}

function FilterChips({ scenario, filter, onFilter }: FilterChipsProps) {
  const skills = (Object.keys(SKILL_SHORT) as Skill[]).filter((skill) => scenario.engineers.some((e) => e.skills.includes(skill)))
  const transports = (Object.keys(TRANSPORT_RU) as Transport[]).filter((kind) => scenario.engineers.some((e) => e.transport === kind))
  return (
    <div className="eng-filter" role="group" aria-label="Фильтр инженеров">
      {skills.map((skill) => (
        <button key={skill} type="button" className={`chip ${filter.skills.includes(skill) ? 'on' : ''}`} aria-pressed={filter.skills.includes(skill)} onClick={() => onFilter({ ...filter, skills: toggled(filter.skills, skill) })}>
          {SKILL_SHORT[skill]}
        </button>
      ))}
      {transports.map((kind) => (
        <button key={kind} type="button" className={`chip ${filter.transports.includes(kind) ? 'on' : ''}`} aria-pressed={filter.transports.includes(kind)} title={TRANSPORT_RU[kind]} onClick={() => onFilter({ ...filter, transports: toggled(filter.transports, kind) })}>
          <TransportIcon transport={kind} />
        </button>
      ))}
    </div>
  )
}

export function EngineerList({
  scenario,
  plan,
  liveRoutes,
  selected,
  selectedOrder,
  onSelect,
  onSelectOrder,
  simStates,
  unavailable,
  group,
  onGoToPlace,
  filter,
  onFilter,
  onHover,
}: EngineerListProps) {
  const ids = scenario.engineers.map((e) => e.id)
  const colorOf = useEngineerColor()
  const orders = ordersById(scenario)
  const visitsOf = (id: string) =>
    liveRoutes ? liveRoutes[id]?.length ?? 0 : plan?.routes.find((r) => r.engineer_id === id)?.stops.length ?? 0
  const used = scenario.engineers.filter((e) => visitsOf(e.id) > 0).length
  const places = startPlaces(scenario).filter((place) => place.engineers.length > 0)
  const ordered = (engineers: Engineer[]) =>
    [...engineers].sort((a, b) => Number(unavailable.has(a.id)) - Number(unavailable.has(b.id)))

  const renderEngineer = (engineer: Engineer) => {
    const route = plan?.routes.find((r) => r.engineer_id === engineer.id)
    const visits = visitsOf(engineer.id)
    const load = plan && !liveRoutes ? plan.metrics.utilization_by_engineer[engineer.id] ?? 0 : null
    const frozen = route?.stops.some((s) => s.locked) ?? false
    const off = unavailable.has(engineer.id)
    const state = simStates?.[engineer.id]
    const isSelected = selected === engineer.id
    const color = colorOf(engineer.id)
    const filteredOut = !matchesFilter(engineer, filter)
    const isOut = Boolean(group && !group.has(engineer.id)) || filteredOut
    return (
      <li
        key={engineer.id}
        className={cx('eng', isSelected && 'selected', off && 'off', !visits && 'idle', isOut && 'out')}
        onMouseEnter={() => onHover(engineer.id)}
        onMouseLeave={() => onHover(null)}
      >
        <button type="button" className="eng-row" onClick={() => onSelect(isSelected ? null : engineer.id)} aria-expanded={isSelected}>
          <i className="eng-dot" style={{ background: visits || state ? color : 'transparent', borderColor: color }} />
          <span className="eng-main">
            <span className="eng-name">
              <span className="eng-name-text">{engineer.name}</span>
              {frozen && <LockIcon title="Есть зафиксированные визиты" />}
              <TransportIcon transport={engineer.transport} />
              {state ? (
                <span className={`status s-${state.status}`}>{STATUS_RU[state.status]}</span>
              ) : (
                off && <span className="eng-tag">недоступен</span>
              )}
            </span>
          </span>
          <span className="eng-load">
            {load !== null ? (
              <span className="load-bar" title={`Загрузка смены ${Math.round(load * 100)}%`}>
                <i style={{ width: `${Math.min(100, Math.round(load * 100))}%`, background: color }} />
              </span>
            ) : (
              <span className="load-bar empty" />
            )}
            <span className="eng-shift">
              {engineer.shift_start}–{engineer.shift_end}
            </span>
          </span>
          <span className="eng-visits" title={state ? 'выполнено из запланированных' : 'визитов'}>
            {state ? `${state.done}/${state.total}` : visits || 0}
          </span>
        </button>
        {isSelected && route && route.stops.length > 0 && (
          <div className="eng-detail">
            <div className="eng-facts">
              {km(route.distance_km)} км · в пути {route.travel_min} мин · до {route.end_time}
              {route.break && ` · обед ${route.break.start}–${route.break.finish}`}
            </div>
            <ol className="stops">
              {route.stops.map((stop, i) => (
                <li key={stop.order_id}>
                  <button
                    type="button"
                    className={cx('stop', stop.locked && 'locked', selectedOrder === stop.order_id && 'selected')}
                    onClick={() => onSelectOrder(stop.order_id)}
                  >
                    <span className="stop-n" style={{ borderColor: color }}>
                      {i + 1}
                    </span>
                    <span className="stop-t">{stop.start}</span>
                    <span>{stop.order_id}</span>
                    <span className="stop-where">{orders[stop.order_id]?.district}</span>
                    {stop.locked && <LockIcon title="Зафиксирован" />}
                    {stop.late_min > 0 && <span className="late">+{stop.late_min}</span>}
                  </button>
                </li>
              ))}
            </ol>
          </div>
        )}
      </li>
    )
  }

  return (
    <div className="panel engineers">
      <div className="panel-head">
        <h2>
          Инженеры <span className="muted">{plan || liveRoutes ? `${used} из ${ids.length}` : ids.length}</span>
        </h2>
        <FilterChips scenario={scenario} filter={filter} onFilter={onFilter} />
      </div>
      <ul className="panel-scroll">
        {places.map((place) => [
          <li key={`place-${place.key}`} className="eng-place">
            <PlaceMark kind={place.kind} />
            <span className="eng-place-kind">{PLACE_TITLE[place.kind]}</span>
            {place.point ? (
              <button type="button" className="oc-link eng-place-link" title={place.address} onClick={() => onGoToPlace(place.point!)}>
                {placeLabel(place.address)}
              </button>
            ) : (
              <span className="eng-place-link">{placeLabel(place.address)}</span>
            )}
            <span className="muted">{place.engineers.length}</span>
          </li>,
          ...ordered(place.engineers).map(renderEngineer),
        ])}
      </ul>
    </div>
  )
}
