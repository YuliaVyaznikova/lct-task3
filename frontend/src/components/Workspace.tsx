import type { ReactNode } from 'react'

interface WorkspaceProps {
  top: ReactNode
  left: ReactNode
  map: ReactNode
  mapOverlay: ReactNode
  right: ReactNode
  busy: boolean
}

export function Workspace({ top, left, map, mapOverlay, right, busy }: WorkspaceProps) {
  return (
    <div className={`workspace ${top ? 'with-top' : ''}`}>
      {top}
      <div className={`plan-grid ${busy ? 'is-busy' : ''}`}>
        {left}
        <div className="map-pane">
          {map}
          {mapOverlay}
        </div>
        {right}
      </div>
    </div>
  )
}
