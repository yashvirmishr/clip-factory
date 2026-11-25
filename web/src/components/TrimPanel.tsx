import { useEffect, useState } from 'react'
import { api, formatTimecode } from '../api'
import type { Clip } from '../types'
import { Icon } from '../workspace/Icon'

interface Props {
  sourceId: string
  clip: Clip
  fps: number
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
export function TrimPanel({ sourceId, clip, fps, onTrimmed, onSeek }: Props) {
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
    <details className="inspector-section inspector-fold">
      <summary className="section-head">
        <div>
          <span className="label">Trim</span>
          <h3>
            {formatTimecode(start, fps)} → {formatTimecode(end, fps)}
          </h3>
        </div>
        <span className="fold-tail">
          <span className="pill numeric">{duration.toFixed(1)}s</span>
          <Icon name="chevron-down" size={13} />
        </span>
      </summary>
      <div className="section-body stack-10">
        {(['start', 'end'] as const).map((edge) => (
          <div className="trim-row" key={edge}>
            <span className="trim-edge">{edge === 'start' ? 'IN' : 'OUT'}</span>
            <div className="trim-nudge">
              <button type="button" className="btn icon sm" onClick={() => nudge(edge, -NUDGE)} aria-label={`${edge} earlier`}>
                <Icon name="minus" size={12} />
              </button>
              <label className="trim-input">
                <span className="sr-only">{edge === 'start' ? 'In point' : 'Out point'}, seconds</span>
                <input
                  type="number"
                  step="0.1"
                  value={(edge === 'start' ? start : end).toFixed(1)}
                  onChange={(event) => {
                    const value = Number(event.target.value)
                    if (Number.isFinite(value)) {
                      if (edge === 'start') setStart(value)
                      else setEnd(value)
                    }
                  }}
                />
                <span>s</span>
              </label>
              <button type="button" className="btn icon sm" onClick={() => nudge(edge, NUDGE)} aria-label={`${edge} later`}>
                <Icon name="plus" size={12} />
              </button>
            </div>
            <button type="button" className="btn ghost sm" onClick={() => onSeek(edge === 'start' ? start : end)}>
              Show
            </button>
          </div>
        ))}

        <div className="trim-actions">
          <button
            type="button"
            className="btn sm primary"
            disabled={busy || !dirty || invalid}
            onClick={() => void apply()}
          >
            {busy ? 'Applying…' : 'Apply trim'}
          </button>
          <button type="button" className="btn sm ghost" disabled={busy || !dirty} onClick={reset}>
            Reset
          </button>
          <span className="toolbar-spacer" />
          <span className="field-hint">5–90s</span>
        </div>

        {invalid ? (
          <span className="warn-line">
            <Icon name="alert" size={13} />
            Clips must stay between {MIN_DURATION}s and {MAX_DURATION}s.
          </span>
        ) : null}
        {error ? (
          <span className="warn-line">
            <Icon name="alert" size={13} />
            {error}
          </span>
        ) : null}
      </div>
    </details>
  )
}
