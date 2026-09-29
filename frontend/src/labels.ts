import type { Candidate, CandidateReasonCode, Engineer, EventKind, Objective, Order, ReasonCode, Skill, Transport } from './types'
import type { ColorMode } from './colors'

export const SKILL_RU: Record<Skill, string> = {
  local: 'Локальные работы',
  connection: 'Подключение и дозаказы',
  emergency: 'Аварийные работы',
}

export const TRANSPORT_RU: Record<Transport, string> = {
  car: 'автомобиль',
  foot: 'пешком',
  bike: 'велосипед',
  public: 'общественный транспорт',
}

export const SKILL_SHORT: Record<Skill, string> = { local: 'локальные', connection: 'подключение', emergency: 'авария' }

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

export const CANDIDATE_REASON: Record<CandidateReasonCode, string> = {
  NO_SKILL: 'нет навыка',
  NO_TRANSPORT: 'не тот транспорт',
  NO_EQUIPMENT: 'не хватит оборудования',
  WINDOW: 'не успеет к окну',
  SHIFT: 'не хватит смены',
  LUNCH: 'не встанет обед',
  CAPACITY: 'не помещается в маршрут',
}

export const engineerName = (engineers: Engineer[], id: string) => engineers.find((e) => e.id === id)?.name ?? id

export const candidateDeltaKm = (row: Candidate) => row.total_delta_km ?? row.added_km ?? 0

export const shiftedVisits = (row: Candidate) =>
  row.shifted.length ? `сдвинет ${row.shifted.length} ${plural(row.shifted.length, 'визит', 'визита', 'визитов')}` : 'без сдвигов'

const skillName = (skill: Skill) => SKILL_RU[skill].toLowerCase()

export function shortReason(code: ReasonCode, order: Order): string {
  const window = `${order.window_start}–${order.window_end}`
  switch (code) {
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
  }
}

export function effectiveTier(order: Order): number {
  return order.priority === 'urgent' ? 1 : order.priority_tier
}

export const TIER_LABEL: Record<number, string> = {
  1: 'Аварии и срочные',
  2: 'Подключения',
  3: 'Ремонт и дозаказ',
}

export const TIER_NAME: Record<number, string> = { 1: 'аварии', 2: 'подключения', 3: 'ремонт' }

export function plural(count: number, one: string, few: string, many: string): string {
  const mod10 = count % 10
  const mod100 = count % 100
  if (mod10 === 1 && mod100 !== 11) {
    return one
  }
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) {
    return few
  }
  return many
}

export function humanizeCodes(text: string): string {
  return text.replace(/«(local|connection|emergency|car|foot|bike|public)»/g, (_, code: string) => {
    if (code in SKILL_RU) {
      return `«${SKILL_RU[code as Skill]}»`
    }
    return `«${TRANSPORT_RU[code as Transport]}»`
  })
}

export const OBJECTIVE_LABEL: Record<Objective, string> = {
  auto: 'Автоматически',
  min_engineers: 'Меньше инженеров',
  min_distance: 'Меньше пробега',
  balanced: 'Равномерная загрузка',
}

export const percent = (part: number, whole: number) => (whole ? Math.round((part / whole) * 100) : 0)

export function km(value: number, digits = 1): string {
  return value.toLocaleString('ru-RU', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function signed(value: number, digits = 1): string {
  const rounded = Number(value.toFixed(digits))
  if (rounded === 0) {
    return '±0'
  }
  return (rounded > 0 ? '+' : '−') + km(Math.abs(rounded), digits)
}

export type ScheduleView = 'gantt' | 'routes' | 'both'

export const SCHEDULE_VIEWS: [ScheduleView, string][] = [
  ['gantt', 'Диаграмма'],
  ['routes', 'Маршруты'],
  ['both', 'Обе'],
]

export const COLOR_MODE_RU: Record<ColorMode, string> = {
  engineer: 'По инженерам',
  office: 'По офисам',
  transport: 'По транспорту',
}

export const MINE_TITLE = 'Мой вариант'

export const VARIANT_TITLE: Record<string, string> = {
  min_engineers: 'Меньше инженеров',
  min_distance: 'Меньший пробег',
  balanced: 'Ровная загрузка',
}

export const VARIANT_NOTE: Record<string, string> = {
  min_engineers: 'цель: меньше инженеров',
  min_distance: 'цель: короче маршруты',
  balanced: 'цель: ровная загрузка',
}
export const VARIANT_ORDER = ['min_engineers', 'min_distance', 'balanced']

export const EVENT_KIND_TITLE: Record<EventKind, string> = {
  urgent_order: 'Авария',
  new_order: 'Новая заявка',
  cancel_order: 'Отмена',
  engineer_unavailable: 'Инженер недоступен',
  engineer_delayed: 'Задержка',
}
