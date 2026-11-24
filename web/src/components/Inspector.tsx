import { useEffect, useRef, useState } from 'react'
import { api, formatTime } from '../api'
import type { Captions, Clip, Verdict } from '../types'
import { GateWarnings, Panel, ScoreBars, TruthList } from './bits'
import { ExportPanel } from './ExportPanel'
import { RenderPanel } from './RenderPanel'
import { TrimPanel } from './TrimPanel'

interface Props {
  sourceId: string
  clip: Clip | null
  mediaSrc: string
  verdict: Verdict | null
  onVerdict: (verdict: Verdict) => void
  onSeek: (seconds: number) => void
  onTime: (seconds: number) => void
  seekRequest: { seconds: number; nonce: number } | null
  onHookSaved: (clipId: string, hook: string) => void
  onClipUpdated: (clip: Clip) => void
  clipCount: number
}

const SEVERITY_COPY: Record<string, string> = {
  heuristic: 'No model installed — hooks and scores come from the deterministic stub scorer.',
  'llama-server': 'Scored by your local llama.cpp server.',
}

export function Inspector({
  sourceId,
  clip,
  mediaSrc,
  verdict,
  onVerdict,
  onSeek,
  onTime,
  seekRequest,
  onHookSaved,
  onClipUpdated,
  clipCount,
}: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [hook, setHook] = useState('')
  const [saving, setSaving] = useState(false)
  const [captions, setCaptions] = useState<Captions | null>(null)
  const [now, setNow] = useState(0)

  useEffect(() => {
    setHook(clip?.llm?.hook ?? '')
  }, [clip?.id, clip?.llm?.hook])

  // Seek the player to the clip in point whenever the selection changes.
  useEffect(() => {
    const node = videoRef.current
    if (!node || !clip) return
    node.currentTime = clip.start
    setNow(clip.start)
  }, [clip?.id])

  useEffect(() => {
    const node = videoRef.current
    if (!node || !seekRequest) return
    node.currentTime = seekRequest.seconds
    setNow(seekRequest.seconds)
  }, [seekRequest?.nonce])

  useEffect(() => {
    let cancelled = false
    setCaptions(null)
    if (!clip) return
    api
      .captions(sourceId, clip.id)
      .then((payload) => {
        if (!cancelled) setCaptions(payload)
      })
      .catch(() => {
        if (!cancelled) setCaptions(null)
      })
    return () => {
      cancelled = true
    }
  }, [sourceId, clip?.id])

  if (!clip) {
    return (
      <aside className="inspector">
        <header className="inspector-head">
          <span className="label">Inspector</span>
        </header>
        <div className="inspector-body">
          <p className="panel-note">
            Select a clip from the reel. Every clip carries its own scorecard, gate results and
            caption pages.
          </p>
        </div>
      </aside>
    )
  }

  const provider = clip.llm?.provider ?? 'none'
  const score = Math.round((clip.final || 0) * 100)

  const saveHook = async () => {
    const trimmed = hook.trim()
    if (!clip.llm || trimmed === clip.llm.hook) return
    setSaving(true)
    try {
      await api.setHook(sourceId, clip.id, trimmed)
      onHookSaved(clip.id, trimmed)
    } finally {
      setSaving(false)
    }
  }

  return (
    <aside className="inspector">
      <header className="inspector-head">
        <span className="label">Clip {clip.rank ? String(clip.rank).padStart(2, '0') : '—'}</span>
        <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)' }}>
          {formatTime(clip.start)}–{formatTime(clip.end)}
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
          <button
            type="button"
            className="btn sm"
            data-on={verdict === 'approve'}
            style={
              verdict === 'approve'
                ? { background: 'var(--tungsten)', borderColor: 'var(--tungsten)', color: '#100804' }
                : undefined
            }
            onClick={() => onVerdict(verdict === 'approve' ? 'undo' : 'approve')}
          >
            Approve
          </button>
          <button
            type="button"
            className="btn sm"
            style={
              verdict === 'reject'
                ? { borderColor: 'var(--alarm)', color: 'var(--alarm)' }
                : undefined
            }
            onClick={() => onVerdict(verdict === 'reject' ? 'undo' : 'reject')}
          >
            Reject
          </button>
        </div>
      </header>

      <div className="inspector-body reveal">
        <video
          ref={videoRef}
          className="player"
          src={mediaSrc}
          controls
          preload="metadata"
          onTimeUpdate={(event) => {
            const time = event.currentTarget.currentTime
            setNow(time)
            onTime(time)
            if (clip && time > clip.end + 0.25) event.currentTarget.pause()
          }}
          onSeeked={(event) => onTime(event.currentTarget.currentTime)}
        />

        <div className="field">
          <div style={{ display: 'flex', alignItems: 'baseline' }}>
            <span className="label">Hook</span>
            <span
              className="mono"
              style={{ marginLeft: 'auto', fontSize: 9.5, color: saving ? 'var(--tungsten)' : 'var(--ink-3)' }}
            >
              {saving ? 'saving…' : `${hook.trim().split(/\s+/).filter(Boolean).length} words`}
            </span>
          </div>
          <textarea
            className="hook-input"
            rows={2}
            value={hook}
            onChange={(event) => setHook(event.target.value)}
            onBlur={saveHook}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                event.currentTarget.blur()
              }
            }}
            placeholder="the on-screen text for the first three seconds"
          />
        </div>

        <Panel
          title="Score"
          aside={
            <span className="mono" style={{ fontSize: 15 }}>
              {String(score).padStart(3, '0')}
            </span>
          }
        >
          <ScoreBars signals={clip.signals} />
          <div style={{ display: 'flex', gap: 6, marginTop: 9, flexWrap: 'wrap' }}>
            <span className="pill">fused {(clip.fused * 100).toFixed(0)}</span>
            <span className="pill">llm {clip.llm?.score ?? '—'}</span>
            <span
              className={`pill${provider === 'llama-server' ? ' ok' : ''}`}
              title={SEVERITY_COPY[provider] ?? `provider: ${provider}`}
            >
              {provider}
            </span>
          </div>
        </Panel>

        <Panel title="Quality scorecard">
          <TruthList items={clip.scorecard} />
        </Panel>

        <Panel title="Gate warnings">
          <GateWarnings gates={clip.gates} />
        </Panel>

        <Panel
          title="Captions"
          aside={
            captions ? (
              <span className="mono" style={{ fontSize: 9.5, color: 'var(--ink-3)' }}>
                {captions.stats.pages} pages · {captions.stats.mean_cps} cps
              </span>
            ) : null
          }
        >
          {captions ? (
            <div className="pages">
              {captions.pages.map((page) => {
                const active = now >= page.start && now < page.end
                return (
                  <div className="page" key={page.index} data-active={active}>
                    <div className="page-words">
                      {page.words.map((word, index) => (
                        <button
                          type="button"
                          className="word"
                          key={`${page.index}-${index}`}
                          data-speaking={now >= word.start && now < word.end}
                          onClick={() => onSeek(word.start)}
                          title={`${formatTime(word.start)} → ${formatTime(word.end)}`}
                        >
                          {word.text}
                        </button>
                      ))}
                    </div>
                    <div className="page-foot">
                      <span>{page.cps} cps</span>
                      <span>{((page.end - page.start) || 0).toFixed(2)}s</span>
                      {page.warnings.map((warning) => (
                        <span className="warn" key={warning}>
                          {warning}
                        </span>
                      ))}
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <p className="panel-note">No caption pages for this clip.</p>
          )}
        </Panel>

        <TrimPanel
          sourceId={sourceId}
          clip={clip}
          onTrimmed={onClipUpdated}
          onSeek={onSeek}
        />

        <RenderPanel sourceId={sourceId} clipId={clip.id} />

        <ExportPanel sourceId={sourceId} clipCount={clipCount} />

        <div className="panel-note" style={{ color: 'var(--ink-3)' }}>
          Transcript window: “{clip.text.slice(0, 260)}
          {clip.text.length > 260 ? '…' : ''}”
        </div>
      </div>
    </aside>
  )
}
