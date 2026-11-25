import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'

const VERSION = 1

function readStored<T>(key: string, base: T): T {
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) return base
    const parsed = JSON.parse(raw) as { v?: number; data?: T }
    if (parsed.v !== VERSION || parsed.data === undefined) return base
    if (
      typeof base === 'object' &&
      base !== null &&
      !Array.isArray(base) &&
      typeof parsed.data === 'object' &&
      parsed.data !== null &&
      !Array.isArray(parsed.data)
    ) {
      return { ...base, ...parsed.data }
    }
    return parsed.data
  } catch {
    return base
  }
}

/**
 * Layout is a product feature, not an accident. Widths, collapsed panels,
 * floating frames and tab selection survive a reload and stay in sync across
 * windows of the same app.
 */
export function usePersistentState<T>(
  key: string,
  initial: T | (() => T),
): [T, Dispatch<SetStateAction<T>>] {
  const initialRef = useRef(initial)
  const [value, setValue] = useState<T>(() => {
    const base =
      typeof initialRef.current === 'function'
        ? (initialRef.current as () => T)()
        : initialRef.current
    return readStored(key, base)
  })

  const timer = useRef<number | undefined>(undefined)

  useEffect(() => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      try {
        window.localStorage.setItem(key, JSON.stringify({ v: VERSION, data: value }))
      } catch {
        /* storage full or blocked; the session still works */
      }
    }, 140)
    return () => window.clearTimeout(timer.current)
  }, [key, value])

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== key || !event.newValue) return
      try {
        const parsed = JSON.parse(event.newValue) as { v?: number; data?: T }
        if (parsed.v === VERSION && parsed.data !== undefined) setValue(parsed.data)
      } catch {
        /* ignore malformed writes */
      }
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [key])

  return [value, setValue]
}
