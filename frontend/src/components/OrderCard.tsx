import { useMap } from 'react-leaflet'

import { visitSteps, type VisitStep } from '../order-status'
import { displayAddress } from '../derive'
import { orderPoint } from '../geo'
import { goToPoint } from '../map-focus'
import { SKILL_RU, TRANSPORT_RU } from '../labels'
import type { Engineer, Order, Stop, Unassigned } from '../types'
import { RequiredToggle } from './common'
import '../order-card.css'


export interface OrderCardVisit {
  engineer: Engineer
  color: string
  n: number
  total: number
  stop: Stop | null
}

interface OrderCardProps {
  order: Order
  visit: OrderCardVisit | null
  unassigned: Unassigned | null
  now: number | null
  onSelectEngineer?: (engineerId: string | null) => void
  required?: boolean
  onToggleRequired?: () => void
}

export function PinIcon() {
  return (
    <svg className="oc-pin" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
      <path
        d="M12 22s7-6.2 7-12a7 7 0 1 0-14 0c0 5.8 7 12 7 12Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      <circle cx="12" cy="10" r="2.6" fill="currentColor" />
    </svg>
  )
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 12 12" width="8" height="8" aria-hidden="true">
      <path d="M2.5 6.4 5 8.8l4.5-5.2" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

interface StepRowProps {
  step: VisitStep
}

function StepRow({ step }: StepRowProps) {
  return (
    <li className={`oc-step ${step.state}`}>
      <span className="oc-dot">{step.state === 'done' && <CheckIcon />}</span>
      <div className="oc-step-body">
        <div className="oc-step-line">
          <span className="oc-step-label">{step.label}</span>
          {step.time && <span className="oc-step-time">{step.time}</span>}
        </div>
        {step.note && <div className="oc-step-note">{step.note}</div>}
      </div>
    </li>
  )
}

interface TimelineProps {
  stop: Stop
  now: number | null
}

function Timeline({ stop, now }: TimelineProps) {
  return (
    <>
      <ol className="oc-timeline">
        {visitSteps(stop, now).map((step) => (
          <StepRow key={step.key} step={step} />
        ))}
      </ol>
      {(stop.locked || stop.late_min > 0) && (
        <div className="oc-flags">
          {stop.locked && <span className="oc-flag frozen">зафиксирован</span>}
          {stop.late_min > 0 && <span className="oc-flag late">позже окна на {stop.late_min} мин</span>}
        </div>
      )}
    </>
  )
}

interface AddressProps {
  order: Order
}

function Address({ order }: AddressProps) {
  const map = useMap()
  const point = orderPoint(order)
  return (
    <div className="oc-address">
      <PinIcon />
      <div>
        {point ? (
          <button type="button" className="oc-link" onClick={() => goToPoint(map, point)}>
            {displayAddress(order.address)}
          </button>
        ) : (
          <span>{displayAddress(order.address)}</span>
        )}
        {order.district && <div className="oc-sub">{order.district}</div>}
      </div>
    </div>
  )
}

interface EngineerRowProps {
  visit: OrderCardVisit
  onSelectEngineer?: OrderCardProps['onSelectEngineer']
}

function EngineerRow({ visit, onSelectEngineer }: EngineerRowProps) {
  const map = useMap()
  const open = () => {
    map.closePopup()
    onSelectEngineer?.(visit.engineer.id)
  }
  return (
    <div className="oc-engineer">
      <span className="oc-swatch" style={{ background: visit.color }} />
      <div>
        <button type="button" className="oc-link" onClick={open}>
          {visit.engineer.name}
        </button>
        <div className="oc-sub">
          {TRANSPORT_RU[visit.engineer.transport]} · визит {visit.n} из {visit.total}
        </div>
      </div>
    </div>
  )
}

interface UnplacedProps {
  unassigned: Unassigned | null
}

function Unplaced({ unassigned }: UnplacedProps) {
  return (
    <div className="oc-unplaced">
      <div className="oc-unplaced-title">Не размещена</div>
      <div>{unassigned ? unassigned.detail : 'Вне плана'}</div>
    </div>
  )
}

export function OrderCard({ order, visit, unassigned, now, onSelectEngineer, required = false, onToggleRequired }: OrderCardProps) {
  return (
    <div className="oc">
      <div className="oc-head">
        <span className="oc-id">{order.id}</span>
        {order.priority === 'urgent' && <span className="oc-urgent">срочная</span>}
        {onToggleRequired && <RequiredToggle on={required} onToggle={onToggleRequired} />}
        <div className="oc-work">
          {order.work_type || SKILL_RU[order.skill]} · {order.duration_min} мин
        </div>
      </div>
      <Address order={order} />
      <div className="oc-window">
        <span className="oc-window-title">Окно клиента</span>
        <span className="oc-window-time">
          {order.window_start}–{order.window_end}
        </span>
      </div>
      {visit && <EngineerRow visit={visit} onSelectEngineer={onSelectEngineer} />}
      {visit?.stop && <Timeline stop={visit.stop} now={now} />}
      {!visit && <Unplaced unassigned={unassigned} />}
    </div>
  )
}

interface OrderHintProps {
  order: Order
  visit: OrderCardVisit | null
}

export function OrderHint({ order, visit }: OrderHintProps) {
  return (
    <div className="oc-hint">
      <b>{order.id}</b> · окно {order.window_start}–{order.window_end}
      <br />
      {visit ? (
        <>
          {visit.engineer.name}
          {visit.stop && `, ${visit.stop.start}`}
        </>
      ) : (
        <span className="oc-hint-warn">не размещена</span>
      )}
    </div>
  )
}
