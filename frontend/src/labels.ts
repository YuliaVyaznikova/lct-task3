import type { Engineer, Order, ReasonCode, Skill, Transport } from './types'
import { SKILL_RU, TRANSPORT_RU } from './types'

export const REASON_LABEL: Record<ReasonCode, string> = {
  NO_SKILL: 'Нет инженера с нужным навыком',
  NO_TRANSPORT: 'Нет инженера с нужным транспортом',
  NO_EQUIPMENT: 'Не хватает оборудования',
  SHIFT_MISMATCH: 'Окно не укладывается в смены',
  UNREACHABLE: 'Слишком далеко, не успеть к окну',
  CAPACITY: 'Не удалось разместить в этом расчёте',
  NO_COORDS: 'Адрес не найден на карте',
  CANCELLED: 'Заявка отменена',
  ENGINEER_UNAVAILABLE: 'Исполнитель выбыл',
  MANUAL: 'Снята с маршрута вручную',
}

export const REASON_IS_RULE: Record<ReasonCode, boolean> = {
  NO_SKILL: true,
  NO_TRANSPORT: true,
  NO_EQUIPMENT: true,
  SHIFT_MISMATCH: true,
  UNREACHABLE: true,
  CAPACITY: false,
  NO_COORDS: true,
  CANCELLED: true,
  ENGINEER_UNAVAILABLE: false,
  MANUAL: true,
}

export function reasonLabel(code: string): string {
  return REASON_LABEL[code as ReasonCode] ?? `Не назначена (${code})`
}

const skillName = (skill: Skill) => SKILL_RU[skill].toLowerCase()

export function shortReason(code: string, order: Order | undefined, engineers: Engineer[]): string {
  if (!order) return reasonLabel(code)
  const window = `${order.window_start}–${order.window_end}`
  switch (code as ReasonCode) {
    case 'NO_SKILL':
      return `Ни у одного инженера на смене нет навыка «${skillName(order.skill)}».`
    case 'NO_TRANSPORT':
      return `Заявке нужен транспорт «${
        order.required_transport ? TRANSPORT_RU[order.required_transport] : 'любой'
      }», а у инженеров с нужным навыком его нет.`
    case 'NO_EQUIPMENT':
      return 'Для заявки нужно больше оборудования, чем бригада берёт с собой утром.'
    case 'SHIFT_MISMATCH':
      return `Окно ${window} и ${order.duration_min} мин работы не укладываются в смены подходящих инженеров.`
    case 'UNREACHABLE':
      return `Адрес слишком далеко: никто из подходящих инженеров не успевает к ${order.window_end}.`
    case 'CAPACITY':
      return `Инженеры с нужным навыком есть, но в окно ${window} заявка не встала без опозданий на других адресах.`
    case 'NO_COORDS':
      return 'Адрес не удалось найти на карте. Уточните его, и заявку можно будет планировать.'
    case 'CANCELLED':
      return 'Заявка отменена и в плане больше не участвует.'
    case 'ENGINEER_UNAVAILABLE':
      return 'Исполнитель выбыл, а замену в этом расчёте найти не удалось.'
    case 'MANUAL':
      return 'Диспетчер снял заявку с маршрута. Её можно назначить обратно вручную.'
    default:
      return reasonLabel(code)
  }
}

export function effectiveTier(order: Order): number {
  return order.priority === 'urgent' ? 1 : order.priority_tier ?? 3
}

export const TIER_LABEL: Record<number, string> = {
  1: 'Аварии и срочные',
  2: 'Подключения',
  3: 'Ремонт и дозаказ',
}

export const TIER_SHORT: Record<number, string> = {
  1: 'П1',
  2: 'П2',
  3: 'П3',
}

export function plural(count: number, one: string, few: string, many: string): string {
  const mod10 = count % 10
  const mod100 = count % 100
  if (mod10 === 1 && mod100 !== 11) return one
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few
  return many
}

export function humanizeCodes(text: string): string {
  return text.replace(/«(local|connection|emergency|car|foot|bike|public)»/g, (_, code: string) => {
    if (code in SKILL_RU) return `«${SKILL_RU[code as Skill]}»`
    return `«${TRANSPORT_RU[code as Transport]}»`
  })
}

export function staticMismatch(order: Order, engineer: Engineer): string {
  if (!engineer.skills.includes(order.skill)) return `нет навыка «${skillName(order.skill)}»`
  if (order.required_transport && order.required_transport !== engineer.transport) {
    return `нужен транспорт «${TRANSPORT_RU[order.required_transport]}»`
  }
  return ''
}

export const OBJECTIVE_LABEL: Record<string, string> = {
  auto: 'автоматически',
  min_engineers: 'меньше инженеров',
  min_distance: 'меньше пробега',
  balanced: 'равномерная загрузка',
}

export function km(value: number, digits = 1): string {
  return value.toLocaleString('ru-RU', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function signed(value: number, digits = 1): string {
  const rounded = Number(value.toFixed(digits))
  if (rounded === 0) return '±0'
  return (rounded > 0 ? '+' : '−') + km(Math.abs(rounded), digits)
}
