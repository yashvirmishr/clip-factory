import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getPlayhead, setPlayhead, subscribePlayhead } from './playhead'

describe('playhead', () => {
  beforeEach(() => {
    vi.spyOn(Date, 'now')
  })

  afterEach(() => {
    vi.restoreAllMocks()
    // Reset the module-level store between tests.
    setPlayhead(0)
  })

  it('starts at zero', () => {
    expect(getPlayhead()).toBe(0)
  })

  it('moves forward', () => {
    setPlayhead(12.5)
    expect(getPlayhead()).toBe(12.5)
  })

  it('clamps NaN and keeps the previous value', () => {
    setPlayhead(5)
    setPlayhead(NaN)
    expect(getPlayhead()).toBe(5)
  })

  it('ignores a repeated value (no spurious notifications)', () => {
    const listener = vi.fn()
    const unsubscribe = subscribePlayhead(listener)
    setPlayhead(7)
    setPlayhead(7)
    setPlayhead(7)
    expect(listener).toHaveBeenCalledTimes(1)
    unsubscribe()
  })

  it('notifies every subscriber on every change', () => {
    const a = vi.fn()
    const b = vi.fn()
    subscribePlayhead(a)
    subscribePlayhead(b)
    setPlayhead(1)
    setPlayhead(2)
    expect(a).toHaveBeenCalledTimes(2)
    expect(b).toHaveBeenCalledTimes(2)
  })

  it('unsubscribe stops notifications', () => {
    const listener = vi.fn()
    const unsubscribe = subscribePlayhead(listener)
    unsubscribe()
    setPlayhead(3)
    expect(listener).not.toHaveBeenCalled()
  })

  it('returns an unsubscribe function', () => {
    const listener = vi.fn()
    const unsubscribe = subscribePlayhead(listener)
    expect(typeof unsubscribe).toBe('function')
    setPlayhead(4)
    expect(listener).toHaveBeenCalledTimes(1)
    unsubscribe()
    setPlayhead(5)
    expect(listener).toHaveBeenCalledTimes(1)
  })
})
