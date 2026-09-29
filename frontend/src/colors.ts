import { createContext, useContext } from 'react'

import { startPlaces } from './geo'
import type { Scenario, Transport } from './types'

export type ColorMode = 'engineer' | 'office' | 'transport'

const TRANSPORT_COLORS: Record<Transport, string> = {
  car: '#1f63d1',
  foot: '#1d7f3e',
  bike: '#b06200',
  public: '#7d4cc9',
}

const PALETTE = [
  '#1f63d1',
  '#cc3a2d',
  '#1d7f3e',
  '#b06200',
  '#7d4cc9',
  '#0b7f93',
  '#b3367b',
  '#5b7500',
  '#8a5528',
  '#1d3c8f',
  '#9c1d45',
  '#565c64',
  '#b8472a',
  '#2d6aa8',
  '#357546',
]

export function engineerColor(engineerIds: string[], engineerId: string): string {
  const index = engineerIds.indexOf(engineerId)
  return PALETTE[(index < 0 ? 0 : index) % PALETTE.length]
}

function officeColors(scenario: Scenario): Record<string, string> {
  const colors: Record<string, string> = {}
  startPlaces(scenario).forEach((place, index) => {
    for (const engineer of place.engineers) colors[engineer.id] = PALETTE[index % PALETTE.length]
  })
  return colors
}

export function colorResolver(mode: ColorMode, scenario: Scenario): (engineerId: string) => string {
  const ids = scenario.engineers.map((engineer) => engineer.id)
  if (mode === 'office') {
    const byOffice = officeColors(scenario)
    return (id) => byOffice[id] ?? engineerColor(ids, id)
  }
  if (mode === 'transport') {
    const transports = Object.fromEntries(scenario.engineers.map((engineer) => [engineer.id, engineer.transport]))
    return (id) => TRANSPORT_COLORS[transports[id] as Transport] ?? engineerColor(ids, id)
  }
  return (id) => engineerColor(ids, id)
}

export const EngineerColorContext = createContext<(engineerId: string) => string>(() => PALETTE[0])

export function useEngineerColor(): (engineerId: string) => string {
  return useContext(EngineerColorContext)
}
