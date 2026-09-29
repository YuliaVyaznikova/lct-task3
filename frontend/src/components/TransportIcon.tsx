import { TRANSPORT_RU } from '../labels'
import type { Transport } from '../types'

const PATHS: Record<Transport, string> = {
  car: 'M5 11l1.5-4.5A2 2 0 0 1 8.4 5h7.2a2 2 0 0 1 1.9 1.5L19 11m-14 0h14a1 1 0 0 1 1 1v4H4v-4a1 1 0 0 1 1-1zm1 5v2m12-2v2M7.5 13.5h.01M16.5 13.5h.01',
  foot: 'M13 4.5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0zM9.5 20l1.5-6-2-2 1-4.5 3 1 2 3M11 14l2.5 2.5L14 20',
  bike: 'M6 18a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm12 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 15l3-6h5l4 6M9 9L7.5 7H6m5 2l2 6',
  public: 'M6 4h12a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM5 11h14M8 20l1.5-3M16 20l-1.5-3M8.5 14h.01M15.5 14h.01',
}

interface TransportIconProps {
  transport: Transport
}

export function TransportIcon({ transport }: TransportIconProps) {
  return (
    <svg className="transport-icon" viewBox="0 0 24 24" role="img" aria-label={TRANSPORT_RU[transport]}>
      <title>{TRANSPORT_RU[transport]}</title>
      <path d={PATHS[transport]} />
    </svg>
  )
}
