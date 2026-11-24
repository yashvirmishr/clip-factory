import { useEffect, useState } from 'react'
import { api, formatTime } from '../api'
import type { Clip } from '../types'

interface Props {
  sourceId: string
  clip: Clip
  onTrimmed: (clip: Clip) => void
  onSeek: (seconds: number) => void
}

const MIN_DURATION = 5
const MAX_DURATION = 90
const NUDGE = 0.5

/**
 * Trim is the edit every clipper needs and almost none explain.
 *
 * Two rules keep this honest rather than decorative: the clip can never leave
 * its own source, and it can never become shorter than the minimum the gates
 * judge. The server enforces both again — the disabled states here are a hint,
 * not the guarantee.
 */
export function TrimPanel({ sourceId, clip, onTrimmed, onSeek }: Props) {
  const [start, setStart] = useState(clip.start)
  const [end, setEnd] = useState(clip.end)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setStart(clip.start)
    setEnd(clip.end)
    setError(null)
  }, [clip.id, clip.start, clip.end])

  const duration = Math.max(0, end - start)
  const dirty = Math.abs(start - clip.start) > 0.001 || Math.abs(end - clip.end) > 0.001
  const invalid = duration < MIN_DURATION || duration > MAX_DURATION

  const nudge = (edge: 'start' | 'end', delta: number) => {
    if (edge === 'start') setStart((value) => Math.max(0, Math.min(value + delta, end - MIN_DURATION)))
    else setEnd((value) => Math.min(value + delta, start + MAX_DURATION))
  }

  const apply = async () => {
    setBusy(true)
    setError(null)
    try {
      const updated = await api.trimClip(sourceId, clip.id, start, end)
      onTrimmed(updated)
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const reset = () => {
    setStart(clip.start)
    setEnd(clip.end)
    setError(null)
  }

  return (
    <section className="panel">
      <header className="panel-head">
        <span className="label" style={{ color: 'var(--ink-2)' }}>
          Trim
        </span>
        <span className="mono" style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-3)' }}>
          {formatTime(start)} → {formatTime(end)} · {duration.toFixed(1)}s
        </span>
      </header>
      <div className="panel-body" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {(['start', 'end'] as const).map((edge) => (
          <div key={edge} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span className="label" style={{ width: 34 }}>
              {edge === 'start' ? 'IN' : 'OUT'}
            </span>
            <button className="btn sm" type="button" onClick={() => nudge(edge, -NUDGE)} aria-label={`${edge} earlier`}>
              −
            </button>
            <input
              className="mono"
              type="number"
              step="0.1"
              value={edge === 'start' ? start : end}
              onChange={(event) => {
                const value = Number(event.target.value)
                if (Number.isFinite(value)) {
                  if (edge === 'start') setStart(value)
                  else setEnd(value)
                }
              }}
              style={{
                width: 82,
                background: 'var(--raised)',
                border: '1px solid var(--seam)',
                borderRadius: 4,
                color: 'var(--ink)',
                padding: '3px 6px',
                fontSize: 11,
              }}
            />
            <button className="btn sm" type="button" onClick={() => nudge(edge, NUDGE)} aria-label={`${edge} later`}>
              +
            </button>
            <button
              className="btn sm"
              type="button"
              style={{ marginLeft: 'auto' }}
              onClick={() => onSeek(edge === 'start' ? start : end)}
            >
              Show
            </button>
          </div>
        ))}

        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <button
            className="btn sm primary"
            type="button"
            disabled={busy || !dirty || invalid}
            onClick={() => void apply()}
          >
            {busy ? 'applying…' : 'Apply trim'}
          </button>
          <button className="btn sm" type="button" disabled={busy || !dirty} onClick={reset}>
            Reset
          </button>
        </div>

        {invalid ? (
          <span className="warn-line">
            Clips must stay between {MIN_DURATION}s and {MAX_DURATION}s.
          </span>
        ) : null}
        {error ? <span className="warn-line">{error}</span> : null}
      </div>
    </section>
  )
}
