import { useEffect, useMemo } from 'react'
import {
  CircleMarker,
  MapContainer,
  Marker,
  Polyline,
  TileLayer,
  Tooltip,
  useMap,
} from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

import { engineerColor } from '../colors'
import type { Diff, Plan, Scenario } from '../types'
import { SKILL_RU } from '../types'

const officeIcon = L.divIcon({
  className: '',
  html:
    '<div style="width:18px;height:18px;border-radius:4px;background:#1d2430;' +
    'border:2px solid #fff;box-shadow:0 0 0 1px #1d2430"></div>',
  iconSize: [18, 18],
  iconAnchor: [9, 9],
})

function FitBounds({ scenario }: { scenario: Scenario }) {
  const map = useMap()
  useEffect(() => {
    const points: [number, number][] = scenario.orders
      .filter((o) => o.lat !== null && o.lon !== null)
      .map((o) => [o.lat as number, o.lon as number])
    if (scenario.office.lat !== null && scenario.office.lon !== null) {
      points.push([scenario.office.lat, scenario.office.lon])
    }
    if (points.length) map.fitBounds(L.latLngBounds(points), { padding: [30, 30] })
  }, [scenario.id, map])
  return null
}

interface Props {
  scenario: Scenario
  plan: Plan
  diff: Diff | null
  selectedOrder: string | null
  selectedEngineer: string | null
  onSelectOrder: (orderId: string | null) => void
}

export function MapView({
  scenario,
  plan,
  diff,
  selectedOrder,
  selectedEngineer,
  onSelectOrder,
}: Props) {
  const engineerIds = useMemo(() => scenario.engineers.map((e) => e.id), [scenario])
  const ordersById = useMemo(
    () => Object.fromEntries(scenario.orders.map((o) => [o.id, o])),
    [scenario],
  )
  const assignment = useMemo(() => {
    const map: Record<string, { engineerId: string; seq: number; start: string; locked: boolean }> =
      {}
    for (const route of plan.routes) {
      for (const stop of route.stops) {
        map[stop.order_id] = {
          engineerId: route.engineer_id,
          seq: stop.seq,
          start: stop.start,
          locked: stop.locked,
        }
      }
    }
    return map
  }, [plan])

  const changedOrders = useMemo(
    () => new Set(diff ? diff.changed.map((c) => c.order_id).concat(diff.added) : []),
    [diff],
  )

  const center: [number, number] = [
    scenario.office.lat ?? 55.75,
    scenario.office.lon ?? 37.62,
  ]

  const visible = (engineerId: string) =>
    selectedEngineer === null || selectedEngineer === engineerId

  return (
    <MapContainer center={center} zoom={11} className="leaflet-container" preferCanvas>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <FitBounds scenario={scenario} />

      {plan.routes
        .filter((route) => route.stops.length && visible(route.engineer_id))
        .map((route) => {
          const color = engineerColor(engineerIds, route.engineer_id)
          const path: [number, number][] = []
          const startOrder = ordersById[route.stops[0].order_id]
          if (scenario.office.lat !== null && scenario.office.lon !== null) {
            path.push([scenario.office.lat, scenario.office.lon])
          }
          if (startOrder) {
            for (const stop of route.stops) {
              const order = ordersById[stop.order_id]
              if (order?.lat != null && order.lon != null) path.push([order.lat, order.lon])
            }
          }
          return (
            <Polyline
              key={route.engineer_id}
              positions={path}
              pathOptions={{
                color,
                weight: selectedEngineer === route.engineer_id ? 4 : 2.5,
                opacity: 0.75,
              }}
            />
          )
        })}

      {scenario.orders
        .filter((order) => order.lat != null && order.lon != null)
        .map((order) => {
          const info = assignment[order.id]
          const assigned = Boolean(info)
          if (assigned && !visible(info.engineerId)) return null
          const color = assigned ? engineerColor(engineerIds, info.engineerId) : '#ffffff'
          const changed = changedOrders.has(order.id)
          return (
            <CircleMarker
              key={order.id}
              center={[order.lat as number, order.lon as number]}
              radius={selectedOrder === order.id ? 9 : order.priority === 'urgent' ? 7 : 5.5}
              pathOptions={{
                color: changed ? '#f0a500' : assigned ? '#ffffff' : '#c9513e',
                weight: changed ? 3 : selectedOrder === order.id ? 3 : 1.5,
                fillColor: color,
                fillOpacity: info?.locked ? 0.45 : 0.95,
                dashArray: order.geocode_quality === 'district' ? '3 3' : undefined,
              }}
              eventHandlers={{ click: () => onSelectOrder(order.id) }}
            >
              <Tooltip direction="top" offset={[0, -6]}>
                <div style={{ maxWidth: 260 }}>
                  <b>{order.id}</b>
                  {order.priority === 'urgent' && ' · срочная'}
                  <br />
                  {SKILL_RU[order.skill]} · {order.duration_min} мин
                  <br />
                  окно {order.window_start}–{order.window_end}
                  <br />
                  {order.address}
                  <br />
                  {assigned ? (
                    <>
                      <b>
                        {scenario.engineers.find((e) => e.id === info.engineerId)?.name}
                      </b>
                      , визит №{info.seq}, начало {info.start}
                    </>
                  ) : (
                    <b style={{ color: '#c9513e' }}>не назначена</b>
                  )}
                </div>
              </Tooltip>
            </CircleMarker>
          )
        })}

      {scenario.office.lat != null && scenario.office.lon != null && (
        <Marker position={[scenario.office.lat, scenario.office.lon]} icon={officeIcon}>
          <Tooltip direction="top" offset={[0, -10]}>
            Офис участка: {scenario.office.address}
          </Tooltip>
        </Marker>
      )}
    </MapContainer>
  )
}
