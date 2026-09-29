import { useCallback, useEffect, useState } from 'react'

import type { ColorMode } from './colors'
import type { QueueFilter } from './components/JobQueue'
import type { CandidatePreview, MapFocus } from './components/MapView'
import type { PlaceFocusTarget } from './components/PlaceCard'
import { NO_FILTER, type EngineerFilter } from './engineer-filter'
import type { LatLon } from './geo'
import type { Selection } from './types'

const isTextControl = (target: EventTarget | null) => target instanceof HTMLInputElement || target instanceof HTMLSelectElement

export function useMapInteraction() {
  const [selection, setSelection] = useState<Selection>(null)
  const [candidate, setCandidate] = useState<CandidatePreview | null>(null)
  const [focus, setFocus] = useState<MapFocus | null>(null)
  const [placeFocus, setPlaceFocus] = useState<PlaceFocusTarget | null>(null)
  const [queueFilter, setQueueFilter] = useState<QueueFilter>('all')
  const [colorMode, setColorMode] = useState<ColorMode>('engineer')
  const [hoverEngineer, setHoverEngineer] = useState<string | null>(null)
  const [engineerFilter, setEngineerFilter] = useState<EngineerFilter>(NO_FILTER)

  const selectedOrder = selection?.kind === 'order' ? selection.id : null
  const selectedEngineer = selection?.kind === 'engineer' ? selection.id : null

  const selectOrder = useCallback((id: string | null) => setSelection(id ? { kind: 'order', id } : null), [])
  const selectEngineer = useCallback((id: string | null) => setSelection(id ? { kind: 'engineer', id } : null), [])
  const clearSelection = useCallback(() => setSelection(null), [])

  const clearMap = useCallback(() => {
    setCandidate(null)
    setSelection(null)
    setFocus(null)
  }, [])

  const focusOrder = useCallback((id: string) => {
    setCandidate(null)
    setSelection({ kind: 'order', id })
    setFocus((current) => ({ orderId: id, nonce: (current?.nonce ?? 0) + 1 }))
  }, [])

  const focusPlace = useCallback(
    (point: LatLon) => setPlaceFocus((current) => ({ point, nonce: (current?.nonce ?? 0) + 1 })),
    [],
  )

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isTextControl(event.target)) {
        setSelection(null)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (!selectedOrder) {
      setCandidate(null)
    }
  }, [selectedOrder])

  return {
    selectedOrder,
    selectedEngineer,
    candidate,
    setCandidate,
    focus,
    placeFocus,
    queueFilter,
    setQueueFilter,
    colorMode,
    setColorMode,
    hoverEngineer,
    setHoverEngineer,
    engineerFilter,
    setEngineerFilter,
    selectOrder,
    selectEngineer,
    clearSelection,
    clearMap,
    focusOrder,
    focusPlace,
  }
}
