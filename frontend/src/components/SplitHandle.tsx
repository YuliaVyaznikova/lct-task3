import { useEffect, useState, type RefObject } from 'react'

const MIN_SHARE = 0.2
const MAX_SHARE = 0.85
const KEY_STEP = 0.05

const clamp = (share: number) => Math.min(MAX_SHARE, Math.max(MIN_SHARE, share))

function readShare(key: string, fallback: number): number {
  try {
    const stored = Number(localStorage.getItem(key))
    return stored ? clamp(stored) : fallback
  } catch {
    return fallback
  }
}

function writeShare(key: string, share: number) {
  try {
    localStorage.setItem(key, String(share))
  } catch {
    return
  }
}

export function useSplitShare(key: string, fallback: number) {
  const [share, setShare] = useState(() => readShare(key, fallback))
  useEffect(() => writeShare(key, share), [key, share])
  return [share, (next: number) => setShare(clamp(next)), () => setShare(fallback)] as const
}

interface SplitHandleProps {
  container: RefObject<HTMLElement>
  share: number
  onShare: (share: number) => void
  onReset: () => void
  label: string
}

export function SplitHandle({ container, share, onShare, onReset, label }: SplitHandleProps) {
  const [dragging, setDragging] = useState(false)

  const start = (event: React.PointerEvent<HTMLDivElement>) => {
    const box = container.current?.getBoundingClientRect()
    if (!box) {
      return
    }
    event.preventDefault()
    const handle = event.currentTarget
    handle.setPointerCapture(event.pointerId)
    setDragging(true)
    const move = (e: PointerEvent) => onShare((e.clientY - box.top) / box.height)
    const stop = () => {
      setDragging(false)
      handle.removeEventListener('pointermove', move)
      handle.removeEventListener('pointerup', stop)
      handle.removeEventListener('pointercancel', stop)
    }
    handle.addEventListener('pointermove', move)
    handle.addEventListener('pointerup', stop)
    handle.addEventListener('pointercancel', stop)
  }

  const onKey = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'ArrowUp') {
      onShare(share - KEY_STEP)
    } else if (event.key === 'ArrowDown') {
      onShare(share + KEY_STEP)
    } else if (event.key === 'Home') {
      onReset()
    } else {
      return
    }
    event.preventDefault()
  }

  return (
    <div
      className={`split-handle ${dragging ? 'dragging' : ''}`}
      role="separator"
      aria-orientation="horizontal"
      aria-label={label}
      aria-valuemin={MIN_SHARE * 100}
      aria-valuemax={MAX_SHARE * 100}
      aria-valuenow={Math.round(share * 100)}
      tabIndex={0}
      title={label}
      onPointerDown={start}
      onDoubleClick={onReset}
      onKeyDown={onKey}
    >
      <span />
    </div>
  )
}
