import { useEffect, useRef, useState } from 'react'

import { km } from '../labels'
import type { SavedPlan } from '../types'

interface PlanStorageProps {
  onSave: (name: string) => Promise<void>
  onList: () => Promise<SavedPlan[]>
  onLoad: (item: SavedPlan) => Promise<void>
  onDelete: (id: string) => Promise<void>
  canSave: boolean
  onCopy: (() => void) | null
}

const stamp = (date: Date) =>
  date.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })

const defaultName = () => `План ${stamp(new Date())}`

const savedAt = (item: SavedPlan) => stamp(new Date(item.saved_at))

type Mode = 'menu' | 'save' | 'open' | null

export function PlanStorage({ onSave, onList, onLoad, onDelete, canSave, onCopy }: PlanStorageProps) {
  const [mode, setMode] = useState<Mode>(null)
  const [name, setName] = useState('')
  const [items, setItems] = useState<SavedPlan[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [doomed, setDoomed] = useState<string | null>(null)
  const box = useRef<HTMLSpanElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!mode) {
      return
    }
    const onDown = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) {
        setMode(null)
      }
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') {
        return
      }
      setMode(null)
      trigger.current?.focus()
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [mode])

  const refresh = () => onList().then(setItems).catch(() => setItems([]))

  const startSave = () => {
    setName(defaultName())
    setMode('save')
  }

  const startOpen = () => {
    setItems(null)
    setMode('open')
    void refresh()
  }

  const commitSave = async () => {
    const trimmed = name.trim()
    if (!trimmed || busy) {
      return
    }
    setBusy(true)
    try {
      await onSave(trimmed)
      setMode(null)
    } catch {
      return
    } finally {
      setBusy(false)
    }
  }

  const open = async (item: SavedPlan) => {
    setBusy(true)
    try {
      await onLoad(item)
      setMode(null)
    } catch {
      return
    } finally {
      setBusy(false)
    }
  }

  const remove = async (id: string) => {
    setBusy(true)
    try {
      await onDelete(id)
      setDoomed(null)
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  return (
    <span className="plan-storage" ref={box}>
      <button
        ref={trigger}
        type="button"
        className="icon vb-more"
        aria-label="Действия с планом"
        aria-haspopup="menu"
        aria-expanded={mode !== null}
        title="Действия с планом"
        onClick={() => setMode(mode === null ? 'menu' : null)}
      >
        <svg viewBox="0 0 16 16" className="glyph" aria-hidden>
          <circle cx="3" cy="8" r="1.5" fill="currentColor" />
          <circle cx="8" cy="8" r="1.5" fill="currentColor" />
          <circle cx="13" cy="8" r="1.5" fill="currentColor" />
        </svg>
      </button>
      {mode === 'menu' && (
        <div className="ps-pop ps-menu" role="menu" aria-label="Действия с планом">
          <button type="button" role="menuitem" disabled={!canSave} autoFocus onClick={startSave}>
            Сохранить выбранный вариант
          </button>
          {onCopy && (
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMode(null)
                onCopy()
              }}
            >
              Сделать копию выбранного варианта
            </button>
          )}
          <hr />
          <button type="button" role="menuitem" onClick={startOpen}>
            Открыть сохранённый план…
          </button>
        </div>
      )}
      {mode === 'save' && (
        <div className="ps-pop ps-save" role="dialog" aria-label="Сохранить план">
          <input
            autoFocus
            value={name}
            maxLength={80}
            aria-label="Название плана"
            onChange={(e) => setName(e.target.value)}
            onFocus={(e) => e.target.select()}
            onKeyDown={(e) => e.key === 'Enter' && void commitSave()}
          />
          <button type="button" className="primary small" disabled={busy || !name.trim()} onClick={() => void commitSave()}>
            Сохранить
          </button>
          <button type="button" className="ghost small" onClick={() => setMode(null)}>
            Отмена
          </button>
        </div>
      )}
      {mode === 'open' && (
        <div className="ps-pop" role="menu" aria-label="Сохранённые планы">
          {items === null && (
            <div className="ps-empty">
              <span className="spinner" aria-hidden />
            </div>
          )}
          {items?.length === 0 && <div className="ps-empty muted">Сохранённых планов нет</div>}
          {items?.map((item) => (
            <div key={item.id} className={`ps-row ${doomed === item.id ? 'doomed' : ''}`} role="menuitem">
              {doomed === item.id ? (
                <>
                  <span className="ps-ask">
                    Удалить <b>«{item.name}»</b>?
                  </span>
                  <button type="button" className="danger small" disabled={busy} onClick={() => void remove(item.id)}>
                    Удалить
                  </button>
                  <button type="button" className="ghost small" onClick={() => setDoomed(null)}>
                    Отмена
                  </button>
                </>
              ) : (
                <>
                  <button type="button" className="ps-open" disabled={busy} onClick={() => void open(item)}>
                    <b>{item.name}</b>
                    <span className="muted">
                      {savedAt(item)} · {item.metrics.assigned}/{item.metrics.orders_total} заявок · {item.metrics.engineers_used} инж. · {km(item.metrics.distance_total_km, 0)} км
                    </span>
                  </button>
                  <button type="button" className="icon ps-delete" onClick={() => setDoomed(item.id)} aria-label={`Удалить «${item.name}»`} title="Удалить">
                    <svg viewBox="0 0 16 16" className="glyph" aria-hidden>
                      <path d="M3.5 4.5h9M6.5 4.5V3h3v1.5M5 4.5l.5 8h5l.5-8" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </span>
  )
}
