import { useEffect, useState, type ReactNode } from 'react'

import { engineerColor } from '../colors'
import type { Engineer } from '../types'

export function Disclosure({
  title,
  children,
  defaultOpen = false,
  className = '',
}: {
  title: ReactNode
  children: ReactNode
  defaultOpen?: boolean
  className?: string
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className={`disclosure ${open ? 'open' : ''} ${className}`}>
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

export function EngineerDot({ ids, id }: { ids: string[]; id: string }) {
  return <i className="dot" style={{ background: engineerColor(ids, id) }} aria-hidden />
}

export function EngineerName({
  engineers,
  id,
  onClick,
}: {
  engineers: Engineer[]
  id: string | null
  onClick?: (id: string) => void
}) {
  if (!id) return <span className="muted">не назначена</span>
  const ids = engineers.map((e) => e.id)
  const label = engineers.find((e) => e.id === id)?.name ?? id
  if (!onClick) {
    return (
      <span className="eng-name-inline">
        <EngineerDot ids={ids} id={id} />
        {label}
      </span>
    )
  }
  return (
    <button type="button" className="link eng-name-inline" onClick={() => onClick(id)}>
      <EngineerDot ids={ids} id={id} />
      {label}
    </button>
  )
}

export function LockIcon({ title }: { title?: string }) {
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
    if (startedAt === null) return
    const timer = window.setInterval(() => setNow(Date.now()), 250)
    return () => window.clearInterval(timer)
  }, [startedAt])
  return startedAt === null ? 0 : Math.max(0, (now - startedAt) / 1000)
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return <div className="empty-note">{children}</div>
}
