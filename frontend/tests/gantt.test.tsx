import { describe, expect, it, vi } from 'vitest'

vi.mock('leaflet', () => ({
  default: { divIcon: () => ({}) },
}))
vi.mock('react-leaflet', () => ({}))

import { renderToString } from 'react-dom/server'
import { Gantt } from '../src/components/Gantt'
import type { Plan, Scenario } from '../src/types'

const scenario: Scenario = {
  region: 'test',
  office: { address: 'Офис', lat: 55.7, lon: 37.6 },
  engineers: [
    {
      id: 'E1',
      name: 'Инженер 1',
      skills: ['local'],
      transport: 'car',
      shift_start: '09:00',
      shift_end: '18:00',
      start: { address: 'Офис', lat: 55.7, lon: 37.6 },
    },
  ],
  orders: [
    {
      id: 'V-001',
      external_id: '74198',
      address: 'Улица 1, дом 2',
      address_normalized: 'Улица 1, дом 2',
      district: 'Центр',
      lat: 55.71,
      lon: 37.61,
      geocode_quality: 'exact',
      skill: 'local',
      work_type: 'Подключение',
      description: '',
      duration_min: 60,
      window_start: '10:00',
      window_end: '12:00',
      priority: 'normal',
      priority_tier: 2,
      required_transport: null,
      attributes: {},
    },
    {
      id: 'V-002',
      external_id: '',
      address: 'Улица 3, дом 4',
      address_normalized: 'Улица 3, дом 4',
      district: 'Центр',
      lat: 55.72,
      lon: 37.62,
      geocode_quality: 'exact',
      skill: 'local',
      work_type: 'Ремонт',
      description: '',
      duration_min: 45,
      window_start: '14:00',
      window_end: '16:00',
      priority: 'normal',
      priority_tier: 2,
      required_transport: null,
      attributes: {},
    },
  ],
} as unknown as Scenario

const plan: Plan = {
  id: 'p1',
  region: 'test',
  created_at: '2026-09-29T10:00:00Z',
  routes: [
    {
      engineer_id: 'E1',
      distance_km: 10,
      duration_min: 180,
      stops: [
        {
          order_id: 'V-001',
          seq: 1,
          travel_km: 5,
          travel_min: 15,
          arrival: '10:00',
          wait_min: 0,
          start: '10:00',
          finish: '11:00',
          locked: false,
          late_min: 0,
          departure: '11:00',
        },
        {
          order_id: 'V-002',
          seq: 2,
          travel_km: 5,
          travel_min: 15,
          arrival: '14:00',
          wait_min: 0,
          start: '14:00',
          finish: '14:45',
          locked: false,
          late_min: 0,
          departure: '14:45',
        },
      ],
      break: {
        start: '13:00',
        finish: '14:00',
      },
    },
  ],
  metrics: {
    assigned: 2,
    unassigned: 0,
    distance_total_km: 10,
    engineers_used: 1,
  },
} as unknown as Plan

const noop = () => {}

describe('gantt view', () => {
  it('отображает внешний номер заказа и сохраняет системный id в подсказке', () => {
    const html = renderToString(
      <Gantt
        scenario={scenario}
        plan={plan}
        now={null}
        nowLabel=""
        selectedOrder={null}
        selectedEngineer={null}
        changed={new Set()}
        unavailable={new Set()}
        onSelectOrder={noop}
        onSelectEngineer={noop}
        onDropVisit={noop}
        onCarryVisit={noop}
        carried={null}
        dropTarget={null}
      />,
    )

    expect(html).toContain('<span class="g-order-id">V-001</span>')
    expect(html).not.toContain('<span class="g-order-id">74198</span>')
    expect(html).toContain('<span class="g-order-id">V-002</span>')
    expect(html).toContain('title="V-001 · 10:00–11:00 · выгрузка 74198"')
  })

  it('оборачивает содержимое блока визита в span', () => {
    const html = renderToString(
      <Gantt
        scenario={scenario}
        plan={plan}
        now={null}
        nowLabel=""
        selectedOrder={null}
        selectedEngineer={null}
        changed={new Set()}
        unavailable={new Set()}
        onSelectOrder={noop}
        onSelectEngineer={noop}
        onDropVisit={noop}
        onCarryVisit={noop}
        carried={null}
        dropTarget={null}
      />,
    )

    expect(html).toContain('<span class="g-work-content">')
    expect(html).not.toContain('<div class="g-work-content">')
  })

  it('отображает иконку обеда и надпись', () => {
    const html = renderToString(
      <Gantt
        scenario={scenario}
        plan={plan}
        now={null}
        nowLabel=""
        selectedOrder={null}
        selectedEngineer={null}
        changed={new Set()}
        unavailable={new Set()}
        onSelectOrder={noop}
        onSelectEngineer={noop}
        onDropVisit={noop}
        onCarryVisit={noop}
        carried={null}
        dropTarget={null}
      />,
    )

    expect(html).toContain('class="g-lunch"')
    expect(html).toContain('class="g-lunch-icon"')
    expect(html).toContain('<span class="g-lunch-label">обед</span>')
    expect(html).not.toContain('🍽️')
  })

  it('в подробном режиме выводит тип работы и адрес', () => {
    const html = renderToString(
      <Gantt
        scenario={scenario}
        plan={plan}
        now={null}
        nowLabel=""
        selectedOrder={null}
        selectedEngineer={null}
        changed={new Set()}
        unavailable={new Set()}
        onSelectOrder={noop}
        onSelectEngineer={noop}
        onDropVisit={noop}
        onCarryVisit={noop}
        carried={null}
        dropTarget={null}
        detailed
      />,
    )

    expect(html).toContain('g-work detailed')
    expect(html).toContain('class="g-work-detail"')
    expect(html).toContain('Подключение')
    expect(html).toContain('Улица 1, дом 2')
  })
})
