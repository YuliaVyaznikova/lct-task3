import { memo, useEffect, useMemo, useRef } from 'react'
import {
  AttributionControl,
  CircleMarker,
  MapContainer,
  Marker,
  Polyline,
  Popup,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
} from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

import { useEngineerColor, type ColorMode } from '../colors'
import { displayAddress, ordersById } from '../derive'
import { orderPoint, routePieces, startPlaces, straightPath, type LatLon, type RoadLegLookup } from '../geo'
import { COLOR_MODE_RU } from '../labels'
import { STATUS_RU, type EngineerState } from '../sim'
import { minutes } from '../time'
import type { Order, Plan, PlanGeometry, Scenario } from '../types'
import type { Engineer, Stop, Unassigned } from '../types'
import { goToPoint } from '../map-focus'
import { OfficeButton, PLACE_TITLE, PlaceCard, PlaceFocus, type PlaceFocusTarget } from './PlaceCard'
import { OrderCard, OrderHint, type OrderCardVisit } from './OrderCard'
import { baseIcon, engineerIcon, officeIcon, pinIcon, shortName, visitIcon } from './mapIcons'

interface FitScenarioBoundsProps {
  scenario: Scenario
}

function FitScenarioBounds({ scenario }: FitScenarioBoundsProps) {
  const map = useMap()
  useEffect(() => {
    const points: LatLon[] = scenario.orders
      .filter((o) => o.lat !== null && o.lon !== null)
      .map((o) => [o.lat as number, o.lon as number])
    if (scenario.office.lat !== null && scenario.office.lon !== null) {
      points.push([scenario.office.lat, scenario.office.lon])
    }
    if (points.length) {
      map.fitBounds(L.latLngBounds(points), { padding: [28, 28] })
    }
  }, [scenario.id, map])
  return null
}

export interface MapFocus {
  orderId: string
  nonce: number
}


interface FlyToFocusProps {
  focus: MapFocus | null
  orders: Record<string, Order>
}

function FlyToFocus({ focus, orders }: FlyToFocusProps) {
  const map = useMap()
  useEffect(() => {
    const point = focus ? orderPoint(orders[focus.orderId]) : null
    if (point) {
      goToPoint(map, point)
    }
  }, [focus, map])
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

function repaint(renderer: L.Canvas): void {
  const canvas = renderer as unknown as { _map?: L.Map & { _animatingZoom?: boolean }; _update: () => void }
  if (canvas._map && !canvas._map._animatingZoom) {
    canvas._update()
  }
}

function NoWheelZoomWhileDragging() {
  const map = useMap()
  useEffect(() => {
    const pause = () => map.scrollWheelZoom.disable()
    const resume = () => map.scrollWheelZoom.enable()
    map.on('dragstart', pause)
    map.on('dragend', resume)
    return () => {
      map.off('dragstart', pause)
      map.off('dragend', resume)
    }
  }, [map])
  return null
}

interface RedrawWhileMovingProps {
  renderer: L.Canvas
}

function RedrawWhileMoving({ renderer }: RedrawWhileMovingProps) {
  const map = useMap()
  useEffect(() => {
    let frame = 0
    const redraw = () => {
      frame = 0
      repaint(renderer)
    }
    const onMove = () => {
      if (!frame) {
        frame = requestAnimationFrame(redraw)
      }
    }
    map.on('move', onMove)
    return () => {
      map.off('move', onMove)
      cancelAnimationFrame(frame)
    }
  }, [map, renderer])
  return null
}

interface RepaintOnChangeProps {
  renderer: L.Canvas
  signal: unknown[]
}

function RepaintOnChange({ renderer, signal }: RepaintOnChangeProps) {
  useEffect(() => {
    const frame = requestAnimationFrame(() => repaint(renderer))
    return () => cancelAnimationFrame(frame)
  }, [renderer, ...signal])
  return null
}

interface FitSelectedRouteProps {
  engineerId: string | null
  points: LatLon[]
  keepView: boolean
}

function FitSelectedRoute({ engineerId, points, keepView }: FitSelectedRouteProps) {
  const map = useMap()
  const saved = useRef<{ center: L.LatLng; zoom: number } | null>(null)
  const latest = useRef({ points, keepView })
  latest.current = { points, keepView }
  useEffect(() => {
    if (!engineerId) {
      if (saved.current && !latest.current.keepView) {
        map.setView(saved.current.center, saved.current.zoom)
      }
      saved.current = null
      return
    }
    if (latest.current.points.length < 2) {
      return
    }
    saved.current ??= { center: map.getCenter(), zoom: map.getZoom() }
    map.fitBounds(L.latLngBounds(latest.current.points), { padding: [48, 48] })
  }, [engineerId, map])
  return null
}

interface ColorModeSwitchProps {
  mode: ColorMode
  onMode: (mode: ColorMode) => void
}

function ColorModeSwitch({ mode, onMode }: ColorModeSwitchProps) {
  return (
    <div className="map-color-mode seg" role="group" aria-label="Раскраска маршрутов">
      {(Object.keys(COLOR_MODE_RU) as ColorMode[]).map((option) => (
        <button key={option} type="button" className={option === mode ? 'on' : ''} aria-pressed={option === mode} onClick={() => onMode(option)}>
          {COLOR_MODE_RU[option]}
        </button>
      ))}
    </div>
  )
}

interface PickMapPointProps {
  onPick: ((p: LatLon) => void) | null
}

function PickMapPoint({ onPick }: PickMapPointProps) {
  const map = useMap()
  useEffect(() => {
    map.getContainer().classList.toggle('picking', Boolean(onPick))
  }, [map, onPick])
  useMapEvents({
    click: (e) => onPick?.([e.latlng.lat, e.latlng.lng]),
  })
  return null
}

interface ClearOnEmptyClickProps {
  onClear: (() => void) | null
}

function ClearOnEmptyClick({ onClear }: ClearOnEmptyClickProps) {
  useMapEvents({
    click: () => {
      window.getSelection()?.removeAllRanges()
      onClear?.()
    },
  })
  return null
}

export interface CandidatePreview {
  orderId: string
  engineerId: string
  routes: Record<string, string[]>
}

interface MapViewProps {
  scenario: Scenario
  plan: Plan | null
  routesOverride: Record<string, string[]> | null
  geometry: PlanGeometry | null
  roadLegs: RoadLegLookup | null
  selectedOrder: string | null
  selectedEngineer: string | null
  changed: Set<string>
  preview: CandidatePreview | null
  focus: MapFocus | null
  placeFocus: PlaceFocusTarget | null
  required: Set<string>
  onToggleRequired: (orderId: string) => void
  sim: { states: EngineerState[]; clock: number; group: Set<string> | null; onClearGroup: () => void } | null
  pickPoint: ((p: LatLon) => void) | null
  pickedPoint: LatLon | null
  onSelectOrder: (orderId: string | null) => void
  onSelectEngineer: (engineerId: string | null) => void
  colorMode: ColorMode
  onColorMode: (mode: ColorMode) => void
  hoverEngineer: string | null
  dimmed: Set<string>
}

const EMPTY = new Set<string>()
const HOVER_DIM_OPACITY = 0.12

type VisitInfo = { engineerId: string; n: number }
type StopInfo = Stop & { engineerId: string }

function routeSequences(plan: Plan | null, routesOverride: Record<string, string[]> | null): Record<string, string[]> {
  const sequences: Record<string, string[]> = {}
  if (routesOverride) {
    for (const [id, orders] of Object.entries(routesOverride)) if (orders.length) sequences[id] = orders
  } else {
    for (const route of plan?.routes ?? []) {
      if (route.stops.length) {
        sequences[route.engineer_id] = route.stops.map((stop) => stop.order_id)
      }
    }
  }
  return sequences
}

function stopDetailsByOrder(plan: Plan | null): Record<string, StopInfo> {
  const details: Record<string, StopInfo> = {}
  for (const route of plan?.routes ?? []) {
    for (const stop of route.stops) details[stop.order_id] = { ...stop, engineerId: route.engineer_id }
  }
  return details
}

function visibleVisits(sequences: Record<string, string[]>, preview: CandidatePreview | null): Record<string, VisitInfo> {
  const visits: Record<string, VisitInfo> = {}
  for (const [id, orders] of Object.entries(sequences)) {
    if (preview && preview.routes[id]) {
      continue
    }
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
  if (clock === null || !plan) {
    return EMPTY
  }
  const done = new Set<string>()
  for (const route of plan.routes) {
    for (const stop of route.stops) if (minutes(stop.finish) <= clock) done.add(stop.order_id)
  }
  return done
}

function MapViewInner({
  scenario,
  plan,
  routesOverride,
  geometry,
  roadLegs,
  selectedOrder,
  selectedEngineer,
  changed,
  preview,
  focus: mapFocus,
  placeFocus,
  required,
  onToggleRequired,
  sim,
  pickPoint,
  pickedPoint,
  onSelectOrder,
  onSelectEngineer,
  colorMode,
  onColorMode,
  hoverEngineer,
  dimmed,
}: MapViewProps) {
  const renderer = useMemo(() => L.canvas({ tolerance: 6, padding: 0.5 }), [])
  const colorOf = useEngineerColor()
  const orders = useMemo(() => ordersById(scenario), [scenario])

  const sequences = useMemo(() => routeSequences(plan, routesOverride), [plan, routesOverride])
  const stopInfo = useMemo(() => stopDetailsByOrder(plan), [plan])

  const affected = preview ? new Set(Object.keys(preview.routes)) : null
  const shown = useMemo(() => visibleVisits(sequences, preview), [sequences, preview])

  const unassignedById = useMemo(
    () => Object.fromEntries((plan?.unassigned ?? []).map((u) => [u.order_id, u])) as Record<string, Unassigned>,
    [plan],
  )
  const engineersById = useMemo(
    () => Object.fromEntries(scenario.engineers.map((e) => [e.id, e])) as Record<string, Engineer>,
    [scenario],
  )
  const orderVisit = (orderId: string): OrderCardVisit | null => {
    const info = shown[orderId]
    const engineer = info && engineersById[info.engineerId]
    if (!info || !engineer) {
      return null
    }
    const stop = stopInfo[orderId]
    return {
      engineer,
      color: colorOf(engineer.id),
      n: info.n,
      total: sequences[info.engineerId]?.length ?? info.n,
      stop: stop && stop.engineerId === engineer.id ? stop : null,
    }
  }
  const focus =
    selectedEngineer ?? (selectedOrder && !preview ? shown[selectedOrder]?.engineerId ?? null : null)
  const group = sim?.group ?? null
  const loneOrder = selectedOrder && !preview && !shown[selectedOrder] ? selectedOrder : null
  const faded = (id: string) => {
    if (affected) {
      return !affected.has(id)
    }
    if (hoverEngineer) {
      return hoverEngineer !== id
    }
    if (dimmed.has(id)) {
      return true
    }
    if (loneOrder) {
      return true
    }
    if (focus !== null) {
      return focus !== id
    }
    return group !== null && !group.has(id)
  }
  const toggleEngineer = (id: string) => onSelectEngineer(selectedEngineer === id ? null : id)
  const toggleOrder = (id: string) => onSelectOrder(selectedOrder === id ? null : id)
  const clearSelection =
    (selectedEngineer || selectedOrder || group) && !pickPoint
      ? () => {
          onSelectOrder(null)
          sim?.onClearGroup()
        }
      : null

  const center: LatLon = [scenario.office.lat ?? 55.75, scenario.office.lon ?? 37.62]
  const places = useMemo(() => startPlaces(scenario), [scenario])

  const routePath = (id: string, list: string[], ownPlanRoute: boolean): LatLon[][] =>
    routePieces(id, list, straightPath(id, list, scenario, orders), ownPlanRoute ? { geometry } : { roadLegs })

  const selectedRoutePoints = useMemo(
    () => (selectedEngineer && sequences[selectedEngineer] ? straightPath(selectedEngineer, sequences[selectedEngineer], scenario, orders) : []),
    [selectedEngineer, sequences, scenario, orders],
  )

  const simDone = useMemo(() => completedOrderIdsAt(plan, sim?.clock ?? null), [sim, plan])

  return (
    <div className="map-shell">
      <ColorModeSwitch mode={colorMode} onMode={onColorMode} />
      <MapContainer
        center={center}
        zoom={11}
        zoomSnap={0.25}
        className="leaflet-container"
        preferCanvas
        renderer={renderer}
        attributionControl={false}
      >
        <AttributionControl position="bottomright" prefix={false} />
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitScenarioBounds scenario={scenario} />
        <FlyToFocus focus={mapFocus} orders={orders} />
        <ResizeMapWithContainer />
        <RedrawWhileMoving renderer={renderer} />
        <NoWheelZoomWhileDragging />
        <RepaintOnChange renderer={renderer} signal={[sequences, geometry, roadLegs, plan, preview]} />
        <FitSelectedRoute engineerId={selectedEngineer} points={selectedRoutePoints} keepView={selectedOrder !== null} />
        <PickMapPoint onPick={pickPoint} />
        <ClearOnEmptyClick onClear={clearSelection} />

        {Object.entries(sequences).map(([id, list]) => {
          const color = colorOf(id)
          const isAffected = affected?.has(id)
          const positions = routePath(id, list, !routesOverride)
          if (!positions.length) {
            return null
          }
          return (
            <Polyline
              key={`r-${id}-${isAffected ? 'old' : 'cur'}`}
              positions={positions}
              pathOptions={{
                color,
                weight: isAffected ? 2.5 : focus === id || hoverEngineer === id ? 5 : 3,
                opacity: isAffected ? 0.5 : faded(id) ? (hoverEngineer ? HOVER_DIM_OPACITY : 0.4) : hoverEngineer === id ? 1 : sim ? 0.7 : 0.8,
                dashArray: isAffected ? '6 7' : undefined,
              }}
              bubblingMouseEvents={false}
              eventHandlers={{ click: () => toggleEngineer(id) }}
            />
          )
        })}
        {preview &&
          Object.entries(preview.routes).map(([id, list]) => (
            <Polyline
              key={`p-${id}`}
              positions={routePath(id, list, false)}
              pathOptions={{ color: colorOf(id), weight: 5, opacity: 0.95 }}
            />
          ))}

        {scenario.orders.map((order) => {
          const p = orderPoint(order)
          if (!p) {
            return null
          }
          const info = shown[order.id]
          const selected = selectedOrder === order.id
          const visit = orderVisit(order.id)
          const tooltip = (
            <>
              <Tooltip direction="top" offset={[0, -8]}>
                <OrderHint order={order} visit={visit} />
              </Tooltip>
              <Popup offset={[0, -6]} className="order-popup" minWidth={320} maxWidth={320} autoPanPadding={[24, 24]}>
                <OrderCard
                  order={order}
                  visit={visit}
                  unassigned={unassignedById[order.id] ?? null}
                  now={sim?.clock ?? null}
                  onSelectEngineer={onSelectEngineer}
                  required={required.has(order.id)}
                  onToggleRequired={() => onToggleRequired(order.id)}
                />
              </Popup>
            </>
          )
          if (!info) {
            const open = !plan && !routesOverride
            return (
              <CircleMarker
                key={`o-${order.id}`}
                center={p}
                radius={selected ? 11 : order.priority === 'urgent' ? 7 : 5.5}
                pathOptions={{
                  color: selected ? '#1b2631' : open ? '#ffffff' : '#b7791f',
                  weight: selected ? 3.5 : open ? 1.5 : 2.5,
                  opacity: loneOrder && !selected ? 0.6 : 1,
                  fillColor: open ? '#7b8794' : '#fff7e8',
                  fillOpacity: loneOrder && !selected ? 0.45 : affected || focus ? 0.5 : 0.95,
                }}
                bubblingMouseEvents={false}
                eventHandlers={{ click: () => toggleOrder(order.id) }}
              >
                {tooltip}
              </CircleMarker>
            )
          }
          const color = colorOf(info.engineerId)
          const mods: string[] = []
          const stop = stopInfo[order.id]
          if (stop?.locked) {
            mods.push('locked')
          }
          if (changed.has(order.id)) {
            mods.push('changed')
          }
          if (order.priority === 'urgent') {
            mods.push('urgent')
          }
          if (selected || (preview && preview.orderId === order.id)) {
            mods.push('selected')
          }
          if (faded(info.engineerId) && !selected) {
            mods.push(hoverEngineer ? 'faint' : 'dim')
          }
          if (sim && simDone.has(order.id)) {
            mods.push('done')
          }
          return (
            <Marker
              key={`o-${order.id}`}
              position={p}
              icon={visitIcon(info.n, color, mods)}
              zIndexOffset={selected ? 1000 : mods.includes('dim') || mods.includes('faint') ? -500 : 0}
              eventHandlers={{ click: () => toggleOrder(order.id) }}
            >
              {tooltip}
            </Marker>
          )
        })}

        {places.map((place) =>
          place.point ? (
            <Marker key={`place-${place.key}`} position={place.point} icon={place.kind === 'office' ? officeIcon : baseIcon}>
              <Tooltip direction="top" offset={[0, -10]}>
                {PLACE_TITLE[place.kind]}: {displayAddress(place.address)}
              </Tooltip>
              <Popup className="order-popup" minWidth={320} maxWidth={320} autoPanPadding={[24, 24]}>
                <PlaceCard title={PLACE_TITLE[place.kind]} address={displayAddress(place.address)} point={place.point} engineers={place.engineers}
                  colorOf={colorOf} onSelectEngineer={onSelectEngineer}
                />
              </Popup>
            </Marker>
          ) : null,
        )}
        <PlaceFocus focus={placeFocus} />
        <OfficeButton point={places.find((place) => place.kind === 'office')?.point ?? null} />

        {sim?.states.map((state) => {
          if (!state.position) {
            return null
          }
          const engineer = scenario.engineers.find((e) => e.id === state.engineerId)
          if (!engineer) {
            return null
          }
          return (
            <Marker
              key={`em-${state.engineerId}`}
              position={state.position}
              icon={engineerIcon(shortName(engineer.name), colorOf(engineer.id), state.status, faded(engineer.id))}
              zIndexOffset={faded(engineer.id) ? 1500 : 2000}
              eventHandlers={{ click: () => toggleEngineer(engineer.id) }}
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
    </div>
  )
}

export const MapView = memo(MapViewInner)
