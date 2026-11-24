import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, formatTime, pollUntilDone } from './api'
import type { SourceInfo } from './types'
import { ClipCard } from './components/ClipCard'
import { Inspector } from './components/Inspector'
import { SetupModal } from './components/SetupModal'
import { Sidebar } from './components/Sidebar'
import { Waveform } from './components/Waveform'
import type {
  Analysis,
  Clip,
  Hardware,
  JobState,
  LearnState,
  Peaks,
  SourceRow,
  Verdict,
} from './types'

const PHASES = [
  { id: 'audio', label: 'Audio', stages: ['audio'] },
  { id: 'transcribe', label: 'Transcribe', stages: ['transcribe', 'align'] },
  { id: 'signals', label: 'Signals', stages: ['windows', 'signals', 'gates'] },
  { id: 'score', label: 'Score', stages: ['score'] },
  { id: 'select', label: 'Select', stages: ['select', 'done'] },
]

interface Toast {
  id: number
  kind: 'ok' | 'error' | 'info'
  message: string
}

const REJECT_REASONS = ['boring', 'confusing', 'cut off', 'spoiler', 'off topic', 'duplicate']

function phaseStates(job: JobState | null): Record<string, string> {
  if (!job) return {}
  const finished = job.status === 'done'
  const index = PHASES.findIndex((phase) => phase.stages.includes(job.stage))
  return Object.fromEntries(
    PHASES.map((phase, i) => {
      if (finished) return [phase.id, 'done']
      if (index === -1) return [phase.id, 'idle']
      if (i < index) return [phase.id, 'done']
      if (i === index) return [phase.id, 'active']
      return [phase.id, 'idle']
    }),
  )
}

export default function App() {
  const [sources, setSources] = useState<SourceRow[]>([])
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [learn, setLearn] = useState<LearnState | null>(null)
  const [peaks, setPeaks] = useState<Peaks | null>(null)
  const [job, setJob] = useState<JobState | null>(null)
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null)
  const [verdicts, setVerdicts] = useState<Record<string, Verdict>>({})
  const [rejecting, setRejecting] = useState<string | null>(null)
  const [playhead, setPlayhead] = useState(0)
  const [seekRequest, setSeekRequest] = useState<{ seconds: number; nonce: number } | null>(null)
  const [setupOpen, setSetupOpen] = useState(false)
  const [hardware, setHardware] = useState<Hardware | null>(null)
  const [hardwareError, setHardwareError] = useState<string | null>(null)
  const [toasts, setToasts] = useState<Toast[]>([])
  const [ingestPath, setIngestPath] = useState('')
  const toastId = useRef(0)

  const pushToast = useCallback((kind: Toast['kind'], message: string) => {
    const id = (toastId.current += 1)
    setToasts((current) => [...current, { id, kind, message }])
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id))
    }, 4600)
  }, [])

  const refreshSources = useCallback(async () => {
    try {
      setSources(await api.sources())
    } catch (error) {
      pushToast('error', `Could not list sources: ${(error as Error).message}`)
    }
  }, [pushToast])

  const refreshLearn = useCallback(async () => {
    try {
      setLearn(await api.learn())
    } catch {
      /* the learning panel simply stays empty */
    }
  }, [])

  useEffect(() => {
    void refreshSources()
    void refreshLearn()
    void api.health().catch(() => undefined)
  }, [refreshSources, refreshLearn])

  const selectSource = useCallback(
    async (sourceId: string) => {
      setSelectedSourceId(sourceId)
      setAnalysis(null)
      setPeaks(null)
      setSelectedClipId(null)
      setVerdicts({})
      setPlayhead(0)
      try {
        const payload = await api.analysis(sourceId)
        setAnalysis(payload)
        const first = payload.candidates.find((clip) => clip.rank)
        setSelectedClipId(first?.id ?? null)
        setPeaks(await api.peaks(sourceId))
      } catch {
        /* not analyzed yet - the centre pane offers the analyze action */
      }
    },
    [],
  )

  // Job polling
  useEffect(() => {
    if (!job || (job.status !== 'running' && job.status !== 'queued')) return
    const timer = window.setInterval(async () => {
      try {
        const next = await api.job(job.id)
        setJob(next)
        if (next.status === 'done' && next.analysis) {
          setAnalysis(next.analysis)
          const first = next.analysis.candidates.find((clip) => clip.rank)
          setSelectedClipId(first?.id ?? null)
          if (selectedSourceId) {
            try {
              setPeaks(await api.peaks(selectedSourceId))
            } catch {
              /* peaks are optional */
            }
          }
          void refreshSources()
          pushToast('ok', `${first ? 'Clips ready' : 'Analysis finished with no clips'}`)
        }
        if (next.status === 'error') {
          pushToast('error', next.error || 'Analysis failed')
        }
      } catch (error) {
        pushToast('error', `Lost contact with the analysis job: ${(error as Error).message}`)
      }
    }, 650)
    return () => window.clearInterval(timer)
  }, [job?.id, job?.status, selectedSourceId, refreshSources, pushToast])

  const runAnalyze = useCallback(
    async (force: boolean) => {
      if (!selectedSourceId) return
      try {
        pushToast('info', force ? 'Re-analyzing…' : 'Analyzing…')
        setJob(await api.analyze(selectedSourceId, { limit: 10, force }))
      } catch (error) {
        pushToast('error', `Could not start analysis: ${(error as Error).message}`)
      }
    },
    [selectedSourceId, pushToast],
  )

  const handleIngest = useCallback(
    async (path: string) => {
      const isUrl = /^https?:\/\//i.test(path.trim())
      try {
        if (isUrl) {
          // A download is not a request: it runs as a job so a 2 h VOD does not
          // hold an HTTP connection open for ten minutes.
          pushToast('info', 'Fetching that VOD…')
          const job = await api.ingestUrl(path.trim())
          const finished = await pollUntilDone(job.id)
          if (finished.status === 'error') {
            pushToast('error', `Download failed: ${finished.error || 'unknown error'}`)
            return
          }
          const source = (finished as unknown as { analysis?: SourceInfo }).analysis
          await refreshSources()
          if (source?.id) await selectSource(source.id)
          pushToast('ok', `Ingested ${source?.name ?? 'the video'}`)
          return
        }
        const source = await api.ingest(path)
        await refreshSources()
        await selectSource(source.id)
        pushToast('ok', `Ingested ${source.name}`)
      } catch (error) {
        pushToast('error', `Ingest failed: ${(error as Error).message}`)
      }
    },
    [refreshSources, selectSource, pushToast],
  )

  const handleDemo = useCallback(async () => {
    try {
      pushToast('info', 'Building a demo stream…')
      const source = await api.createDemo()
      await refreshSources()
      await selectSource(source.id)
      pushToast('ok', 'Demo stream ready — press Analyze')
    } catch (error) {
      pushToast('error', `Demo failed: ${(error as Error).message}`)
    }
  }, [refreshSources, selectSource, pushToast])

  const clips = useMemo<Clip[]>(
    () =>
      (analysis?.candidates ?? [])
        .filter((clip) => Boolean(clip.rank))
        .sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99)),
    [analysis],
  )

  const selectedClip = useMemo(
    () => clips.find((clip) => clip.id === selectedClipId) ?? clips[0] ?? null,
    [clips, selectedClipId],
  )

  const handleVerdict = useCallback(
    async (clipId: string, verdict: Verdict, reason = '') => {
      if (!selectedSourceId) return
      // A rejection carries the label that matters most, so ask for one word
      // before recording it. Skipping is allowed and costs nothing.
      if (verdict === 'reject' && reason === '') {
        setRejecting(clipId)
        return
      }
      setRejecting(null)
      setVerdicts((current) => {
        const next = { ...current }
        if (verdict === 'undo') delete next[clipId]
        else next[clipId] = verdict
        return next
      })
      if (verdict === 'undo') return
      try {
        const result = await api.decide(selectedSourceId, clipId, verdict, reason)
        setLearn(result.state)
      } catch (error) {
        pushToast('error', `Feedback not saved: ${(error as Error).message}`)
      }
    },
    [selectedSourceId, pushToast],
  )

  const handleHookSaved = useCallback(
    (clipId: string, hook: string) => {
      setAnalysis((current) => {
        if (!current) return current
        return {
          ...current,
          candidates: current.candidates.map((clip) =>
            clip.id === clipId && clip.llm
              ? { ...clip, llm: { ...clip.llm, hook } }
              : clip,
          ),
        }
      })
      void refreshLearn()
    },
    [refreshLearn],
  )

  const handleClipUpdated = useCallback((updated: Clip) => {
    setAnalysis((current) => {
      if (!current) return current
      return {
        ...current,
        candidates: current.candidates.map((clip) =>
          clip.id === updated.id ? updated : clip,
        ),
      }
    })
  }, [])

  const seekClip = useCallback((seconds: number) => {    setSeekRequest({ seconds, nonce: Date.now() })
    setPlayhead(seconds)
  }, [])

  // Keyboard triage
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target && ['INPUT', 'TEXTAREA'].includes(target.tagName)) return
      if (event.key === 'Escape') {
        setSetupOpen(false)
        setRejecting(null)
      }
      if (!clips.length) return
      const index = clips.findIndex((clip) => clip.id === selectedClip?.id)
      if (event.key === 'j' || event.key === 'ArrowDown') {
        event.preventDefault()
        const next = clips[Math.min(clips.length - 1, index + 1)]
        if (next) setSelectedClipId(next.id)
      }
      if (event.key === 'k' || event.key === 'ArrowUp') {
        event.preventDefault()
        const next = clips[Math.max(0, index - 1)]
        if (next) setSelectedClipId(next.id)
      }
      if ((event.key === 'a' || event.key === 'x') && selectedClip) {
        event.preventDefault()
        const verdict: Verdict = event.key === 'a' ? 'approve' : 'reject'
        void handleVerdict(selectedClip.id, verdicts[selectedClip.id] === verdict ? 'undo' : verdict)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [clips, selectedClip, verdicts, handleVerdict])

  const openSetup = useCallback(async () => {
    setSetupOpen(true)
    setHardwareError(null)
    try {
      setHardware(await api.hardware())
    } catch (error) {
      setHardwareError(`Hardware probe failed: ${(error as Error).message}`)
    }
  }, [])

  const busy = Boolean(job && (job.status === 'running' || job.status === 'queued'))
  const phases = phaseStates(job)
  const activeSource = sources.find((source) => source.id === selectedSourceId) ?? null
  const mediaSrc = selectedSourceId ? api.mediaUrl(selectedSourceId) : ''

  return (
    <div className="app">
      <Sidebar
        sources={sources}
        selectedId={selectedSourceId}
        learn={learn}
        busy={busy}
        onSelect={(id) => void selectSource(id)}
        onIngest={(path) => void handleIngest(path)}
        onDemo={() => void handleDemo()}
        onSetup={() => void openSetup()}
      />

      <div className="stage">
        <header className="topbar">
          <div className="topbar-title">
            <h1>{activeSource?.name ?? 'No source'}</h1>
            {activeSource ? (
              <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>
                {formatTime(activeSource.duration)} · {activeSource.width}×{activeSource.height}
                {activeSource.fps ? ` · ${activeSource.fps.toFixed(2)} fps` : ''}
              </span>
            ) : null}
          </div>

          <div className="telemetry">
            <span>
              <span className={`dot${busy ? ' busy' : ''}`} />
              {busy ? job?.stage || 'working' : 'idle'}
            </span>
            <span>
              ASR <b>{analysis?.asr_backend ?? '—'}</b>
            </span>
            <span>
              LLM <b>{analysis?.llm_backend ?? '—'}</b>
            </span>
            {analysis ? (
              <span>
                reel <b>{(analysis.reel_quality * 100).toFixed(0)}%</b>
              </span>
            ) : null}
            {selectedSourceId ? (
              <button
                type="button"
                className="btn sm"
                disabled={busy}
                onClick={() => void runAnalyze(Boolean(analysis))}
              >
                {analysis ? 'Re-analyze' : 'Analyze'}
              </button>
            ) : null}
          </div>
        </header>

        {job ? (
          <div className="stagebar">
            {PHASES.map((phase) => (
              <span className="phase" key={phase.id} data-state={phases[phase.id] ?? 'idle'}>
                <span className="tick" />
                {phase.label}
              </span>
            ))}
            <span className="job-detail">
              {job.status === 'error'
                ? job.error
                : `${Math.round(job.pct * 100)}% · ${job.detail || job.stage}`}
            </span>
            <div className="progress-track" style={{ width: `${Math.round(job.pct * 100)}%` }} />
          </div>
        ) : null}

        <div className="work">
          <section className="centre">
            {!selectedSourceId ? (
              <div className="empty">
                <div className="empty-inner">
                  <h2>
                    Drop a stream.
                    <br />
                    <em>Get clips.</em>
                  </h2>
                  <p>
                    Everything runs on this machine. Transcription, moment detection and scoring
                    never touch a network — the only model is the one you install.
                  </p>
                  <div className="dropzone">
                    <span className="label">Local file path</span>
                    <div className="dropzone-row">
                      <input
                        className="input"
                        placeholder="C:\VODs\stream.mp4  ·  https://twitch.tv/videos/…"
                        value={ingestPath}
                        onChange={(event) => setIngestPath(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter' && ingestPath.trim()) {
                            void handleIngest(ingestPath.trim())
                            setIngestPath('')
                          }
                        }}
                      />
                      <button
                        type="button"
                        className="btn primary"
                        disabled={!ingestPath.trim() || busy}
                        onClick={() => {
                          void handleIngest(ingestPath.trim())
                          setIngestPath('')
                        }}
                      >
                        Ingest
                      </button>
                    </div>
                    <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)' }}>
                      or
                    </span>
                    <button type="button" className="btn" disabled={busy} onClick={() => void handleDemo()}>
                      Generate a demo stream
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <>
                {peaks ? (
                  <div className="wave-wrap reveal">
                    <div className="wave-head">
                      <span className="label">Source</span>
                      <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-2)' }}>
                        {formatTime(playhead)} / {formatTime(activeSource?.duration ?? 0)}
                      </span>
                      <div className="wave-legend">
                        <span className="legend-key">
                          <i className="legend-swatch" /> candidate
                        </span>
                        <span className="legend-key">
                          <i className="legend-swatch chat" /> playhead
                        </span>
                      </div>
                    </div>
                    <Waveform
                      peaks={peaks}
                      duration={activeSource?.duration ?? 1}
                      clips={clips}
                      playhead={playhead}
                      onSeek={seekClip}
                    />
                  </div>
                ) : null}

                {analysis ? (
                  <>
                    <div className="reel-head reveal reveal-1">
                      <h2>The reel</h2>
                      <span className="reel-count">
                        {clips.length} clips · quality {(analysis.reel_quality * 100).toFixed(0)}%
                      </span>
                      <span style={{ marginLeft: 'auto' }} className="mono">
                        <span style={{ fontSize: 9.5, color: 'var(--ink-3)' }}>
                          J/K move · A approve · X reject
                        </span>
                      </span>
                    </div>
                    {analysis.warnings.length ? (
                      <div className="reveal reveal-1" style={{ padding: '0 16px 9px' }}>
                        {analysis.warnings.map((warning) => (
                          <div className="warn-line" key={warning} style={{ fontSize: 11 }}>
                            <span className="mono" style={{ fontSize: 9, opacity: 0.8 }}>
                              ▲
                            </span>
                            <span style={{ color: 'var(--ink-2)' }}>{warning}</span>
                          </div>
                        ))}
                      </div>
                    ) : null}
                    {rejecting ? (
                      <div className="reason-bar reveal">
                        <span className="label">Why reject?</span>
                        {REJECT_REASONS.map((reason) => (
                          <button
                            type="button"
                            className="btn sm"
                            key={reason}
                            onClick={() => void handleVerdict(rejecting, 'reject', reason)}
                          >
                            {reason}
                          </button>
                        ))}
                        <button
                          type="button"
                          className="btn sm ghost"
                          style={{ marginLeft: 'auto' }}
                          onClick={() => void handleVerdict(rejecting, 'reject', 'unspecified')}
                        >
                          Skip
                        </button>
                      </div>
                    ) : null}
                    <div className="reel reveal reveal-2">
                      {clips.length === 0 ? (
                        <div className="panel">
                          <div className="panel-body">
                            <p className="panel-note">
                              Every candidate failed a quality gate, so nothing was selected. That is
                              the anti-garbage layer working — check the warnings above and try a
                              source with clearer speech.
                            </p>
                          </div>
                        </div>
                      ) : (
                        clips.map((clip) => (
                          <ClipCard
                            key={clip.id}
                            clip={clip}
                            mediaSrc={mediaSrc}
                            selected={clip.id === selectedClip?.id}
                            verdict={verdicts[clip.id] ?? null}
                            onSelect={() => setSelectedClipId(clip.id)}
                            onVerdict={(verdict) => void handleVerdict(clip.id, verdict)}
                          />
                        ))
                      )}
                    </div>
                  </>
                ) : (
                  <div className="empty">
                    <div className="empty-inner">
                      <h2>
                        Ready to <em>cut</em>.
                      </h2>
                      <p>
                        {activeSource?.name} is ingested. Run the analysis to transcribe it, find
                        candidate moments and score them.
                      </p>
                      <button
                        type="button"
                        className="btn primary"
                        disabled={busy}
                        onClick={() => void runAnalyze(false)}
                      >
                        {busy ? 'Analyzing…' : 'Analyze this source'}
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </section>

          <Inspector
            sourceId={selectedSourceId ?? ''}
            clip={selectedClip}
            mediaSrc={mediaSrc}
            verdict={selectedClip ? verdicts[selectedClip.id] ?? null : null}
            onVerdict={(verdict) => {
              if (selectedClip) void handleVerdict(selectedClip.id, verdict)
            }}
            onSeek={seekClip}
            onTime={setPlayhead}
            seekRequest={seekRequest}
            onHookSaved={handleHookSaved}
            onClipUpdated={handleClipUpdated}
            clipCount={analysis?.candidates.filter((clip) => clip.rank).length ?? 0}
          />
        </div>
      </div>

      {setupOpen ? (
        <SetupModal
          hardware={hardware}
          error={hardwareError}
          onClose={() => setSetupOpen(false)}
          onRefresh={() => void openSetup()}
        />
      ) : null}

      <div className="toast-stack">
        {toasts.map((toast) => (
          <div className="toast" key={toast.id} data-kind={toast.kind}>
            {toast.message}
          </div>
        ))}
      </div>
    </div>
  )
}
