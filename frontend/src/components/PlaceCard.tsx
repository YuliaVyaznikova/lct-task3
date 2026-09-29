import { useEffect } from 'react'
import { useMap } from 'react-leaflet'
import L from 'leaflet'

import type { LatLon } from '../geo'
import { plural, TRANSPORT_RU } from '../labels'
import { goToPoint } from '../map-focus'
import type { Engineer } from '../types'
import { PLACE_GLYPH } from './mapIcons'
import { PinIcon } from './OrderCard'

export const PLACE_TITLE = { office: 'Офис', base: 'База' } as const

interface PlaceMarkProps {
  kind: keyof typeof PLACE_GLYPH
}

export function PlaceMark({ kind }: PlaceMarkProps) {
  return <span className={`place-mark inline ${kind}`} dangerouslySetInnerHTML={{ __html: PLACE_GLYPH[kind] }} />
}

export interface PlaceFocusTarget {
  point: LatLon
  nonce: number
}

interface PlaceFocusProps {
  focus: PlaceFocusTarget | null
}

export function PlaceFocus({ focus }: PlaceFocusProps) {
  const map = useMap()
  useEffect(() => {
    if (focus) {
      goToPoint(map, focus.point)
    }
  }, [focus?.nonce])
  return null
}

interface PlaceCardProps {
  title: string
  address: string
  point: LatLon
  engineers: Engineer[]
  colorOf: (engineerId: string) => string
  onSelectEngineer?: (engineerId: string | null) => void
}

interface EngineerLineProps {
  engineer: Engineer
  color: string
  onOpen: () => void
}

function EngineerLine({ engineer, color, onOpen }: EngineerLineProps) {
  return (
    <li className="oc-engineer">
      <span className="oc-swatch" style={{ background: color }} />
      <div>
        <button type="button" className="oc-link" onClick={onOpen}>
          {engineer.name}
        </button>
        <div className="oc-sub">
          {TRANSPORT_RU[engineer.transport]} · смена {engineer.shift_start}–{engineer.shift_end}
        </div>
      </div>
    </li>
  )
}

export function PlaceCard({ title, address, point, engineers, colorOf, onSelectEngineer }: PlaceCardProps) {
  const map = useMap()
  const open = (engineerId: string) => {
    map.closePopup()
    onSelectEngineer?.(engineerId)
  }
  return (
    <div className="oc">
      <div className="oc-head">
        <span className="oc-id">{title}</span>
      </div>
      <div className="oc-address">
        <PinIcon />
        <button type="button" className="oc-link" onClick={() => goToPoint(map, point)}>
          {address}
        </button>
      </div>
      <div className="pc-crew">
        <div className="oc-sub">
          Выезжают отсюда: {engineers.length} {plural(engineers.length, 'инженер', 'инженера', 'инженеров')}
        </div>
        <ul className="pc-list">
          {engineers.map((engineer) => (
            <EngineerLine key={engineer.id} engineer={engineer} color={colorOf(engineer.id)} onOpen={() => open(engineer.id)} />
          ))}
        </ul>
      </div>
    </div>
  )
}

interface OfficeButtonProps {
  point: LatLon | null
}

export function OfficeButton({ point }: OfficeButtonProps) {
  const map = useMap()
  useEffect(() => {
    if (!point) {
      return
    }
    const control = new L.Control({ position: 'topleft' })
    control.onAdd = () => {
      const bar = L.DomUtil.create('div', 'leaflet-bar office-control')
      const button = L.DomUtil.create('a', '', bar)
      button.href = '#'
      button.title = 'К офису'
      button.setAttribute('role', 'button')
      button.setAttribute('aria-label', 'К офису')
      button.innerHTML = PLACE_GLYPH.office
      L.DomEvent.disableClickPropagation(bar)
      L.DomEvent.on(button, 'click', (event) => {
        L.DomEvent.preventDefault(event)
        goToPoint(map, point)
      })
      return bar
    }
    control.addTo(map)
    return () => {
      control.remove()
    }
  }, [map, point?.[0], point?.[1]])
  return null
}
