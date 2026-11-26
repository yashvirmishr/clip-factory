import { useCallback, useEffect, useRef, useState } from 'react'
import { api, formatTime } from '../api'
import type { Clip, Suggestion, SuggestionPreview } from '../types'
import { Icon } from '../workspace/Icon'
import { Spinner } from '../workspace/ui'

interface Props {
  sourceId: string
  clip: Clip
  onClipUpdated: (clip: Clip) => void
  onSeek: (seconds: number) => void
  onNotify: (kind: 'ok' | 'error' | 'info', message: string) => void
}

/**
 * A suggestion is a diagnosis, not an automatic edit. Every row carries the
 * quote or metric that produced it, and auto-fixes show the exact trim before
 * anything is saved. Undo restores the previous in/out points.
 */
export function CoachPanel({ sourceId, clip, onClipUpdated, onSeek, onNotify }: Props) {
  const [items, setItems] = useState<Suggestion[]>([])
  const [previewing, setPreviewing] = useState<string | null>(null)
  const [preview, setPreview] = useState<SuggestionPreview | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState<string | null>(null)
  const notifyRef = useRef(onNotify)
  notifyRef.current = onNotify

  const load = useCallback(async () => {
    try {
      const payload = await api.suggestions(sourceId, clip.id)
      setItems(payload.suggestions)
    } catch (failure) {
      setError((failure as Error).message)
    }
  }, [sourceId, clip.id])

  useEffect(() => {
    setPreview(null)
    setPreviewing(null)
    void load()
  }, [load])

  const showPreview = async (item: Suggestion) => {
    setBusy(`preview:${item.id}`)
    try {
      const payload = await api.previewSuggestion(sourceId, clip.id, item.id)
      setPreviewing(item.id)
      setPreview(payload.preview)
    } catch (failure) {
      notifyRef.current('error', (failure as Error).message)
    } finally {
      setBusy('')
    }
  }

  const apply = async (item: Suggestion) => {
    setBusy(`apply:${item.id}`)
    try {
      const payload = await api.applySuggestion(sourceId, clip.id, item.id)
      if (payload.candidate) onClipUpdated(payload.candidate)
      setPreview(null)
      setPreviewing(null)
      notifyRef.current('ok', 'Applied. Use Undo to put the clip back exactly as it was.')
      await load()
    } catch (failure) {
      notifyRef.current('error', (failure as Error).message)
    } finally {
      setBusy('')
    }
  }

  const undo = async (item: Suggestion) => {
    setBusy(`undo:${item.id}`)
    try {
      const payload = await api.undoSuggestion(sourceId, clip.id, item.id)
      if (payload.candidate) onClipUpdated(payload.candidate)
      notifyRef.current('info', 'Clip restored.')
      await load()
    } catch (failure) {
      notifyRef.current('error', (failure as Error).message)
    } finally {
      setBusy('')
    }
  }

  const dismiss = async (item: Suggestion) => {
    try {
      await api.dismissSuggestion(sourceId, clip.id, item.id)
      await load()
    } catch (failure) {
      notifyRef.current('error', (failure as Error).message)
    }
  }

  const open = items.filter((item) => item.status === 'open')
  const visible = items.filter((item) => item.status === 'open' || item.status === 'applied')

  return (
    <div className="inspector-scroll stack-14">
      <section className="inspector-section">
        <header className="section-head">
          <div>
            <span className="label">Coach</span>
            <h3>Evidence, then a fix</h3>
          </div>
          <span className="pill">{open.length} open</span>
        </header>
        <div className="section-body stack-12">
          <p className="field-hint">
            Suggestions only change the clip after you press Preview and apply. Every claim is tied to a timestamp or a measured feature.
          </p>
          {visible.length === 0 ? <p className="panel-empty">No quality issues found for this clip.</p> : null}
          {visible.map((item) => {
            const evidence = item.evidence[0]
            return (
              <article className="coach-card" key={item.id} data-tone={item.severity}>
                <header>
                  <Icon name={item.severity === 'warn' ? 'alert' : 'sparkles'} size={14} />
                  <b>{item.title}</b>
                  <button type="button" className="icon-btn icon-btn-sm" aria-label="Dismiss suggestion" onClick={() => void dismiss(item)}>
                    <Icon name="x" size={12} />
                  </button>
                </header>
                <p>{item.why}</p>
                {evidence ? (
                  <div className="coach-evidence">
                    {evidence.quote ? <q>{evidence.quote}</q> : null}
                    <div className="coach-evidence-meta">
                      {evidence.start !== null ? (
                        <button type="button" className="chip num" onClick={() => onSeek(evidence.start ?? 0)}>
                          {formatTime(evidence.start)}
                        </button>
                      ) : null}
                      {evidence.metric ? <span className="num">{evidence.label}: {String(evidence.value)}</span> : null}
                    </div>
                  </div>
                ) : null}
                <p className="coach-fix"><b>Fix:</b> {item.fix}</p>
                <div className="button-row">
                  <button type="button" className="btn ghost sm" onClick={() => void showPreview(item)} disabled={busy === `preview:${item.id}`}>
                    {busy === `preview:${item.id}` ? <Spinner label="" /> : <Icon name="search" size={12} />}
                    Preview
                  </button>
                  {item.status === 'applied' ? (
                    <button type="button" className="btn ghost sm" onClick={() => void undo(item)} disabled={busy === `undo:${item.id}`}>
                      Undo
                    </button>
                  ) : item.auto_fixable ? (
                    <button type="button" className="btn sm" onClick={() => void apply(item)} disabled={busy === `apply:${item.id}`}>
                      {busy === `apply:${item.id}` ? <Spinner label="" /> : <Icon name="check" size={12} />}
                      Apply
                    </button>
                  ) : (
                    <span className="field-hint">Manual edit</span>
                  )}
                </div>
                {previewing === item.id && preview ? (
                  <div className="coach-preview">
                    <div>
                      <span className="label">Before</span>
                      <p>{preview.before_text || '—'}</p>
                    </div>
                    <div>
                      <span className="label">After</span>
                      <p>{preview.after_text || '—'}</p>
                    </div>
                    {preview.duration_s ? <span className="field-hint num">{preview.duration_s.toFixed(1)}s</span> : null}
                  </div>
                ) : null}
              </article>
            )
          })}
        </div>
      </section>
      {error ? (
        <p className="warn-line">
          <Icon name="alert" size={13} />
          {error}
        </p>
      ) : null}
    </div>
  )
}
