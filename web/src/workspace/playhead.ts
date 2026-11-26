import { useSyncExternalStore } from 'react'

/**
 * The playhead is written on every media `timeupdate` (four times a second, and
 * faster while scrubbing). Keeping it in React state at the App root re-rendered
 * the whole workspace for a moving 1 px line; this store lets the three places
 * that actually draw the time subscribe on their own.
 */

type Listener = () => void

let current = 0
const listeners = new Set<Listener>()

export function getPlayhead(): number {
  return current
}

export function setPlayhead(next: number): void {
  if (!Number.isFinite(next) || next === current) return
  current = next
  for (const listener of listeners) listener()
}

export function subscribePlayhead(listener: Listener): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function getServerPlayhead(): number {
  return 0
}

export function usePlayhead(): number {
  return useSyncExternalStore(subscribePlayhead, getPlayhead, getServerPlayhead)
}
