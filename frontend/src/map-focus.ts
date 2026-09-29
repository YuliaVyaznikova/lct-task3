import L from 'leaflet'

import type { LatLon } from './geo'

const PAN_SECONDS = 0.3
const PULSE_MS = 2400
const EDGE_PX = 24

const PIN_HTML =
  '<span class="fp-ring"></span><svg class="fp-pin" viewBox="0 0 28 38" aria-hidden="true"><path d="M14 37C14 37 26 23.6 26 13.5A12 12 0 1 0 2 13.5C2 23.6 14 37 14 37Z"/><circle cx="14" cy="13.5" r="4.6"/></svg>'
const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

function isOnScreen(map: L.Map, target: L.LatLng): boolean {
  const point = map.latLngToContainerPoint(target)
  const size = map.getSize()
  return point.x >= EDGE_PX && point.y >= EDGE_PX && point.x <= size.x - EDGE_PX && point.y <= size.y - EDGE_PX
}

function isNear(map: L.Map, target: L.LatLng): boolean {
  const size = map.getSize()
  const offset = map.latLngToContainerPoint(target).distanceTo(size.divideBy(2))
  return offset <= Math.max(size.x, size.y)
}

function pulse(map: L.Map, target: L.LatLng): void {
  const ring = L.marker(target, {
    icon: L.divIcon({ className: 'focus-pulse', html: PIN_HTML, iconSize: [0, 0] }),
    interactive: false,
    keyboard: false,
    zIndexOffset: 4000,
  }).addTo(map)
  window.setTimeout(() => ring.remove(), PULSE_MS)
}

export function goToPoint(map: L.Map, point: LatLon): void {
  const target = L.latLng(point)
  if (!isOnScreen(map, target)) {
    if (isNear(map, target) && !reducedMotion()) {
      map.panTo(target, { animate: true, duration: PAN_SECONDS })
    } else {
      map.setView(target, map.getZoom(), { animate: false })
    }
  }
  pulse(map, target)
}
