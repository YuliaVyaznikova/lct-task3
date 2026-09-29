import { useEffect, useState } from 'react'

function readChoice<T extends string | boolean>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const stored = localStorage.getItem(key)
    return allowed.find((option) => String(option) === stored) ?? fallback
  } catch {
    return fallback
  }
}

function writeChoice(key: string, value: string | boolean) {
  try {
    localStorage.setItem(key, String(value))
  } catch {
    return
  }
}

export function useStoredChoice<T extends string | boolean>(key: string, allowed: readonly T[], fallback: T) {
  const [value, setValue] = useState<T>(() => readChoice(key, allowed, fallback))
  useEffect(() => writeChoice(key, value), [key, value])
  return [value, setValue] as const
}
