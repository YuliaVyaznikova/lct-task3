import { useEffect, useRef, useState } from 'react'

export function useSnapshot<T>(value: T, intervalMs: number, resetKey: unknown): T {
  const [shown, setShown] = useState(value)
  const shownAt = useRef(0)
  const shownKey = useRef(resetKey)

  useEffect(() => {
    const show = () => {
      shownAt.current = Date.now()
      shownKey.current = resetKey
      setShown(value)
    }
    const waited = Date.now() - shownAt.current
    if (value === null || shownKey.current !== resetKey || waited >= intervalMs) {
      show()
      return
    }
    const timer = window.setTimeout(show, intervalMs - waited)
    return () => window.clearTimeout(timer)
  }, [value, resetKey, intervalMs])

  return shown
}
