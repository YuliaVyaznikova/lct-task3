import type { Engineer, Skill, Transport } from './types'

export interface EngineerFilter {
  skills: Skill[]
  transports: Transport[]
}

export const NO_FILTER: EngineerFilter = { skills: [], transports: [] }

export const isFiltering = (filter: EngineerFilter): boolean => filter.skills.length > 0 || filter.transports.length > 0

export function matchesFilter(engineer: Engineer, filter: EngineerFilter): boolean {
  const skillOk = !filter.skills.length || filter.skills.some((skill) => engineer.skills.includes(skill))
  const transportOk = !filter.transports.length || filter.transports.includes(engineer.transport)
  return skillOk && transportOk
}

export const toggled = <T,>(items: T[], item: T): T[] =>
  items.includes(item) ? items.filter((other) => other !== item) : [...items, item]

export function dimmedEngineerIds(engineers: Engineer[], filter: EngineerFilter): Set<string> {
  if (!isFiltering(filter)) {
    return new Set()
  }
  return new Set(engineers.filter((engineer) => !matchesFilter(engineer, filter)).map((engineer) => engineer.id))
}
