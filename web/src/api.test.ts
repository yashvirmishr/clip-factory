import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, forgetCaptions, formatBytes, formatTime, formatTimecode } from './api'

describe('formatTime', () => {
  it('shows minutes and seconds for short clips', () => {
    expect(formatTime(0)).toBe('0:00')
    expect(formatTime(9.9)).toBe('0:09')
    expect(formatTime(65)).toBe('1:05')
  })

  it('adds an hour field and pads the rest', () => {
    expect(formatTime(3600)).toBe('1:00:00')
    expect(formatTime(3725)).toBe('1:02:05')
  })

  it('clamps nonsense to zero', () => {
    expect(formatTime(-4)).toBe('0:00')
    expect(formatTime(Number.NaN)).toBe('0:00')
  })
})

describe('formatTimecode', () => {
  it('uses a nominal integer rate for 29.97 footage', () => {
    expect(formatTimecode(0, 29.97)).toBe('00:00:00:00')
    expect(formatTimecode(1.5, 29.97)).toBe('00:00:01:15')
  })

  it('rolls frames into seconds, minutes and hours', () => {
    expect(formatTimecode(3661.5, 30)).toBe('01:01:01:15')
  })
})

let calls: string[] = []

function mockFetch(payload: unknown) {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      calls.push(String(url))
      return {
        ok: true,
        status: 200,
        statusText: 'OK',
        headers: { get: () => 'application/json' },
        json: async () => payload,
      } as unknown as Response
    }),
  )
}

const PAGES = { clip_id: 'c1', pages: [], stats: { pages: 0, mean_cps: 0, warnings: 0 } }

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('caption cache', () => {
  it('serves a repeated read of the same clip from memory', async () => {
    mockFetch(PAGES)
    await api.captions('cache-a', 'c1')
    await api.captions('cache-a', 'c1')
    expect(calls).toHaveLength(1)
  })

  it('keeps clips apart', async () => {
    mockFetch(PAGES)
    await api.captions('cache-b', 'c1')
    await api.captions('cache-b', 'c2')
    expect(calls).toHaveLength(2)
  })

  it('reads again after one clip is forgotten', async () => {
    mockFetch(PAGES)
    await api.captions('cache-c', 'c1')
    forgetCaptions('cache-c', 'c1')
    await api.captions('cache-c', 'c1')
    expect(calls).toHaveLength(2)
  })

  it('does not keep a read that was invalidated while it was in flight', async () => {
    calls = []
    let release: () => void = () => {}
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        calls.push(String(url))
        // Hold the first read open so a trim can land underneath it.
        if (calls.length === 1) await new Promise<void>((resolve) => (release = resolve))
        return {
          ok: true,
          status: 200,
          statusText: 'OK',
          headers: { get: () => 'application/json' },
          json: async () => PAGES,
        } as unknown as Response
      }),
    )

    const pending = api.captions('cache-e', 'c1')
    forgetCaptions('cache-e', 'c1')
    release()
    await pending

    await api.captions('cache-e', 'c1')
    expect(calls).toHaveLength(2)
  })

  it('forgets every clip of a source at once', async () => {
    mockFetch(PAGES)
    await api.captions('cache-d', 'c1')
    await api.captions('cache-d', 'c2')
    forgetCaptions('cache-d')
    await api.captions('cache-d', 'c1')
    await api.captions('cache-d', 'c2')
    expect(calls).toHaveLength(4)
  })
})

describe('formatBytes', () => {
  it('uses an em dash for nothing and scales to GB', () => {
    expect(formatBytes(0)).toBe('—')
    expect(formatBytes(500_000_000)).toBe('500 MB')
    expect(formatBytes(1_500_000_000)).toBe('1.50 GB')
  })
})
