import { useEffect, useState, type ReactNode } from 'react'

import { cx } from '../classes'
import { useEngineerColor } from '../colors'
import { engineerName } from '../labels'
import type { Engineer } from '../types'

interface DisclosureProps {
  title: ReactNode
  children: ReactNode
}

export function Disclosure({ title, children }: DisclosureProps) {
  const [open, setOpen] = useState(false)
  return (
    <div className={`disclosure ${open ? 'open' : ''}`}>
      <button type="button" className="disclosure-toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className="chevron" aria-hidden>
          ▸
        </span>
        {title}
      </button>
      {open && <div className="disclosure-body">{children}</div>}
    </div>
  )
}

interface EngineerDotProps {
  id: string
}

export function EngineerDot({ id }: EngineerDotProps) {
  const colorOf = useEngineerColor()
  return <i className="dot" style={{ background: colorOf(id) }} aria-hidden />
}

interface EngineerNameProps {
  engineers: Engineer[]
  id: string | null
  onClick?: (id: string) => void
}

export function EngineerName({
  engineers,
  id,
  onClick,
}: EngineerNameProps) {
  if (!id) {
    return <span className="muted">не назначена</span>
  }
  const label = engineerName(engineers, id)
  if (!onClick) {
    return (
      <span className="eng-name-inline">
        <EngineerDot id={id} />
        {label}
      </span>
    )
  }
  return (
    <button type="button" className="link eng-name-inline" onClick={() => onClick(id)}>
      <EngineerDot id={id} />
      {label}
    </button>
  )
}

interface LockIconProps {
  title?: string
}

export function StopGlyph() {
  return (
    <svg className="stop-glyph" viewBox="0 0 16 16" aria-hidden>
      <path d="M3 3l10 10M13 3L3 13" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" />
    </svg>
  )
}

export function LockIcon({ title }: LockIconProps) {
  return (
    <svg className="lock" viewBox="0 0 12 12" width="11" height="11" aria-label={title} role="img">
      {title && <title>{title}</title>}
      <rect x="2" y="5.2" width="8" height="5.8" rx="1.2" fill="currentColor" />
      <path d="M3.8 5.4V3.9a2.2 2.2 0 0 1 4.4 0v1.5" fill="none" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  )
}

export function useElapsed(startedAt: number | null): number {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (startedAt === null) {
      return
    }
    const timer = window.setInterval(() => setNow(Date.now()), 250)
    return () => window.clearInterval(timer)
  }, [startedAt])
  return startedAt === null ? 0 : Math.max(0, (now - startedAt) / 1000)
}

interface AddressLinkProps {
  children: ReactNode
  onGo: () => void
}

export function AddressLink({ children, onGo }: AddressLinkProps) {
  const go = (e: { stopPropagation: () => void }) => {
    e.stopPropagation()
    onGo()
  }
  return (
    <span
      role="link"
      tabIndex={0}
      className="addr-link"
      onClick={go}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          go(e)
        }
      }}
    >
      {children}
    </span>
  )
}

interface RequiredToggleProps {
  on: boolean
  onToggle: () => void
  compact?: boolean
}

export function RequiredToggle({ on, onToggle, compact = false }: RequiredToggleProps) {
  const label = on ? 'Обязательная' : 'Сделать обязательной'
  const toggle = (e: { stopPropagation: () => void }) => {
    e.stopPropagation()
    onToggle()
  }
  return (
    <span
      role="button"
      tabIndex={0}
      aria-pressed={on}
      aria-label={label}
      title={label}
      className={cx('req-toggle', on && 'on', compact && 'compact')}
      onClick={toggle}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          toggle(e)
        }
      }}
    >
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="M6 2h4l-.5 4 2.5 2.5V10H4V8.5L6.5 6zM8 10v4.5" fill={on ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      </svg>
      {!compact && <span>{label}</span>}
    </span>
  )
}
