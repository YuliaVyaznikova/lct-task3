import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AttributionControl,
  CircleMarker,
  MapContainer,
  Marker,
  Polyline,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
} from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

import { engineerColor } from '../colors'
import { orderPoint, straightPath, type LatLon } from '../geo'
import { STATUS_RU, type EngineerState } from '../sim'
import type { Order, Plan, PlanGeometry, Scenario } from '../types'
import { SKILL_RU } from '../types'
import { baseIcon, engineerIcon, labelIcon, officeIcon, pinIcon, shortName, visitIcon } from './mapIcons'

export { shortName } from './mapIcons'

function FitScenarioBounds({ scenario }: { scenario: Scenario }) {
  const map = useMap()
  useEffect(() => {
    const points: LatLon[] = scenario.orders
      .filter((o) => o.lat !== null && o.lon !== null)
      .map((o) => [o.lat as number, o.lon as number])
    if (scenario.office.lat !== null && scenario.office.lon !== null) {
      points.push([scenario.office.lat, scenario.office.lon])
    }
    if (points.length) map.fitBounds(L.latLngBounds(points), { padding: [28, 28] })
  }, [scenario.id, map])
  return null
}

function CtrlWheelZoom({ onHint }: { onHint: () => void }) {
  const map = useMap()
  useEffect(() => {
    const container = map.getContainer()
    let last = 0
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) {
        onHint()
        return
      }
      e.preventDefault()
      const now = performance.now()
      if (now - last < 60) return
      last = now
      const point = map.mouseEventToContainerPoint(e as unknown as MouseEvent)
      const step = e.deltaY < 0 ? 0.5 : -0.5
      map.setZoomAround(point, map.getZoom() + step)
    }
    container.addEventListener('wheel', onWheel, { passive: false })
    return () => container.removeEventListener('wheel', onWheel)
  }, [map, onHint])
  return null
}

function ResizeMapWithContainer() {
  const map = useMap()
  useEffect(() => {
    const observer = new ResizeObserver(() => map.invalidateSize({ pan: false }))
    observer.observe(map.getContainer())
    return () => observer.disconnect()
  }, [map])
  return null
}

function PickMapPoint({ onPick }: { onPick: ((p: LatLon) => void) | null }) {
  const map = useMap()
  useEffect(() => {
    map.getContainer().classList.toggle('picking', Boolean(onPick))
  }, [map, onPick])
  useMapEvents({
    click: (e) => onPick?.([e.latlng.lat, e.latlng.lng]),
  })
  return null
}

export interface CandidatePreview {
  orderId: string
  engineerId: string
  routes: Record<string, string[]>
}

interface Props {
  scenario: Scenario
  plan: Plan | null
  routesOverride?: Record<string, string[]> | null
  geometry: PlanGeometry | null
  selectedOrder: string | null
  selectedEngineer: string | null
  changed?: Set<string>
  preview?: CandidatePreview | null
  sim?: { states: EngineerState[]; clock: number } | null
  pickPoint?: ((p: LatLon) => void) | null
  pickedPoint?: LatLon | null
  onSelectOrder: (orderId: string | null) => void
  onSelectEngineer?: (engineerId: string | null) => void
}

const EMPTY = new Set<string>()

type VisitInfo = { engineerId: string; n: number }
type StopInfo = { locked: boolean; start: string; late: number }

function routeSequences(plan: Plan | null, routesOverride: Record<string, string[]> | null): Record<string, string[]> {
  const sequences: Record<string, string[]> = {}
  if (routesOverride) {
    for (const [id, orders] of Object.entries(routesOverride)) if (orders.length) sequences[id] = orders
  } else {
    for (const route of plan?.routes ?? []) {
      if (route.stops.length) sequences[route.engineer_id] = route.stops.map((stop) => stop.order_id)
    }
  }
  return sequences
}

function stopDetailsByOrder(plan: Plan | null): Record<string, StopInfo> {
  const details: Record<string, StopInfo> = {}
  for (const route of plan?.routes ?? []) {
    for (const stop of route.stops) details[stop.order_id] = { locked: stop.locked, start: stop.start, late: stop.late_min }
  }
  return details
}

function visibleVisits(sequences: Record<string, string[]>, preview: CandidatePreview | null): Record<string, VisitInfo> {
  const visits: Record<string, VisitInfo> = {}
  for (const [id, orders] of Object.entries(sequences)) {
    if (preview && preview.routes[id]) continue
    orders.forEach((orderId, index) => (visits[orderId] = { engineerId: id, n: index + 1 }))
  }
  if (preview) {
    for (const [id, orders] of Object.entries(preview.routes)) {
      orders.forEach((orderId, index) => (visits[orderId] = { engineerId: id, n: index + 1 }))
    }
  }
  return visits
}

function completedOrderIdsAt(plan: Plan | null, clock: number | null): Set<string> {
  if (clock === null || !plan) return EMPTY
  const done = new Set<string>()
  for (const route of plan.routes) {
    for (const stop of route.stops) {
      const [hours, minutes] = stop.finish.split(':').map(Number)
      if (hours * 60 + minutes <= clock) done.add(stop.order_id)
    }
  }
  return done
}

function MapViewInner({
  scenario,
  plan,
  routesOverride = null,
  geometry,
  selectedOrder,
  selectedEngineer,
  changed = EMPTY,
  preview = null,
  sim = null,
  pickPoint = null,
  pickedPoint = null,
  onSelectOrder,
  onSelectEngineer,
}: Props) {
  const [hint, setHint] = useState(false)
  const hintTimer = useRef<number>()
  const showHint = useCallback(() => {
    setHint(true)
    window.clearTimeout(hintTimer.current)
    hintTimer.current = window.setTimeout(() => setHint(false), 1400)
  }, [])

  const engineerIds = useMemo(() => scenario.engineers.map((e) => e.id), [scenario])
  const orders = useMemo(
    () => Object.fromEntries(scenario.orders.map((o) => [o.id, o])) as Record<string, Order>,
    [scenario],
  )

  const sequences = useMemo(() => routeSequences(plan, routesOverride), [plan, routesOverride])
  const stopInfo = useMemo(() => stopDetailsByOrder(plan), [plan])

  const affected = preview ? new Set(Object.keys(preview.routes)) : null
  const shown = useMemo(() => visibleVisits(sequences, preview), [sequences, preview])

  const unassigned = useMemo(() => new Set((plan?.unassigned ?? []).map((u) => u.order_id)), [plan])
  const focus =
    selectedEngineer ?? (selectedOrder && !preview ? shown[selectedOrder]?.engineerId ?? null : null)
  const faded = (id: string) => (affected ? !affected.has(id) : focus !== null && focus !== id)

  const center: LatLon = [scenario.office.lat ?? 55.75, scenario.office.lon ?? 37.62]
  const pathFor = (id: string, list: string[]): LatLon[] =>
    !routesOverride && geometry?.available && geometry.routes[id] && !preview
      ? geometry.routes[id]
      : straightPath(id, list, scenario, orders)

  const simDone = useMemo(() => completedOrderIdsAt(plan, sim?.clock ?? null), [sim, plan])

  return (
    <div className="map-shell">
      <MapContainer
        center={center}
        zoom={11}
        zoomSnap={0.25}
        scrollWheelZoom={false}
        className="leaflet-container"
        preferCanvas
        attributionControl={false}
      >
        <AttributionControl position="bottomright" prefix={false} />
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitScenarioBounds scenario={scenario} />
        <CtrlWheelZoom onHint={showHint} />
        <ResizeMapWithContainer />
        <PickMapPoint onPick={pickPoint} />

        {Object.entries(sequences).map(([id, list]) => {
          const color = engineerColor(engineerIds, id)
          const isAffected = affected?.has(id)
          return (
            <Polyline
              key={`r-${id}-${isAffected ? 'old' : 'cur'}`}
              positions={pathFor(id, list)}
              pathOptions={{
                color,
                weight: isAffected ? 2.5 : focus === id ? 4.5 : sim ? 2 : 3,
                opacity: isAffected ? 0.5 : faded(id) ? 0.12 : sim ? 0.45 : 0.8,
                dashArray: isAffected ? '6 7' : undefined,
              }}
            />
          )
        })}
        {preview &&
          Object.entries(preview.routes).map(([id, list]) => (
            <Polyline
              key={`p-${id}`}
              positions={straightPath(id, list, scenario, orders)}
              pathOptions={{ color: engineerColor(engineerIds, id), weight: 5, opacity: 0.95 }}
            />
          ))}

        {scenario.orders.map((order) => {
          const p = orderPoint(order)
          if (!p) return null
          const info = shown[order.id]
          const selected = selectedOrder === order.id
          const tooltip = (
            <Tooltip direction="top" offset={[0, -8]}>
              <OrderTip order={order} scenario={scenario} info={info} stop={stopInfo[order.id]} unassigned={unassigned.has(order.id)} planned={Boolean(plan)} />
            </Tooltip>
          )
          if (!info) {
            const open = !plan && !routesOverride
            return (
              <CircleMarker
                key={`o-${order.id}`}
                center={p}
                radius={selected ? 9 : order.priority === 'urgent' ? 7 : 5.5}
                pathOptions={{
                  color: selected ? '#1b2631' : open ? '#ffffff' : '#b7791f',
                  weight: selected ? 3 : open ? 1.5 : 2.5,
                  fillColor: open ? '#7b8794' : '#fff7e8',
                  fillOpacity: affected || focus ? 0.5 : 0.95,
                }}
                eventHandlers={{ click: () => onSelectOrder(order.id) }}
              >
                {tooltip}
              </CircleMarker>
            )
          }
          const color = engineerColor(engineerIds, info.engineerId)
          const mods: string[] = []
          const stop = stopInfo[order.id]
          if (stop?.locked) mods.push('locked')
          if (changed.has(order.id)) mods.push('changed')
          if (order.priority === 'urgent') mods.push('urgent')
          if (selected || (preview && preview.orderId === order.id)) mods.push('selected')
          if (faded(info.engineerId) && !selected) mods.push('dim')
          if (sim && simDone.has(order.id)) mods.push('done')
          return (
            <Marker
              key={`o-${order.id}`}
              position={p}
              icon={visitIcon(info.n, color, mods)}
              zIndexOffset={selected ? 1000 : mods.includes('dim') ? -500 : 0}
              eventHandlers={{ click: () => onSelectOrder(order.id) }}
            >
              {tooltip}
            </Marker>
          )
        })}

        {!sim &&
          Object.entries(preview ? { ...sequences, ...preview.routes } : sequences).map(([id, list]) => {
            const engineer = scenario.engineers.find((e) => e.id === id)
            if (!engineer || !list.length) return null
            const at = orderPoint(orders[list[0]])
            if (!at) return null
            const dim = faded(id) && !(affected?.has(id))
            return (
              <Marker
                key={`lbl-${id}`}
                position={at}
                icon={labelIcon(engineer.name, engineerColor(engineerIds, id), dim)}
                zIndexOffset={dim ? -800 : 400}
                eventHandlers={{ click: () => onSelectEngineer?.(id) }}
                keyboard={false}
              />
            )
          })}

        {scenario.office.lat != null && scenario.office.lon != null && (
          <Marker position={[scenario.office.lat, scenario.office.lon]} icon={officeIcon}>
            <Tooltip direction="top" offset={[0, -10]}>
              Офис: {scenario.office.address}
            </Tooltip>
          </Marker>
        )}
        {Array.from(
          new Map(
            scenario.engineers
              .filter(
                (e) =>
                  e.start.lat != null &&
                  e.start.lon != null &&
                  (e.start.lat !== scenario.office.lat || e.start.lon !== scenario.office.lon),
              )
              .map((e) => [`${e.start.lat},${e.start.lon}`, e]),
          ).values(),
        ).map((engineer) => (
          <Marker key={`base-${engineer.id}`} position={[engineer.start.lat as number, engineer.start.lon as number]} icon={baseIcon}>
            <Tooltip direction="top" offset={[0, -10]}>
              База: {engineer.start.address}
            </Tooltip>
          </Marker>
        ))}

        {sim?.states.map((state) => {
          if (!state.position) return null
          const engineer = scenario.engineers.find((e) => e.id === state.engineerId)
          if (!engineer) return null
          return (
            <Marker
              key={`em-${state.engineerId}`}
              position={state.position}
              icon={engineerIcon(shortName(engineer.name), engineerColor(engineerIds, engineer.id), state.status)}
              zIndexOffset={2000}
              eventHandlers={{ click: () => onSelectEngineer?.(engineer.id) }}
            >
              <Tooltip direction="top" offset={[0, -14]}>
                <b>{engineer.name}</b> · {STATUS_RU[state.status]}
                {state.orderId && <> · {state.orderId}</>}
              </Tooltip>
            </Marker>
          )
        })}

        {pickedPoint && <Marker position={pickedPoint} icon={pinIcon} zIndexOffset={3000} />}
      </MapContainer>
      <div className={`map-hint ${hint ? 'show' : ''}`} aria-hidden={!hint}>
        Масштаб: Ctrl + колесо мыши
      </div>
    </div>
  )
}

function OrderTip({
  order,
  scenario,
  info,
  stop,
  unassigned,
  planned,
}: {
  order: Order
  scenario: Scenario
  info: { engineerId: string; n: number } | undefined
  stop: { locked: boolean; start: string; late: number } | undefined
  unassigned: boolean
  planned: boolean
}) {
  return (
    <div className="order-tip">
      <b>{order.id}</b>
      {order.priority === 'urgent' && ' · срочная'}
      <br />
      {SKILL_RU[order.skill]} · {order.duration_min} мин · окно {order.window_start}–{order.window_end}
      <br />
      {order.address}
      {planned && (
        <>
          <br />
          {info ? (
            <>
              <b>{scenario.engineers.find((e) => e.id === info.engineerId)?.name}</b>, визит {info.n}
              {stop && `, начало ${stop.start}`}
              {stop?.locked && ' · зафиксирован'}
            </>
          ) : (
            <b className="tip-warn">{unassigned ? 'не размещена' : 'вне плана'}</b>
          )}
        </>
      )}
    </div>
  )
}

export const MapView = memo(MapViewInner)
