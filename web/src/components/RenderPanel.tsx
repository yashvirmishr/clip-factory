import { useEffect, useRef, useState } from 'react'
import { api, watchJob } from '../api'
import { Icon } from '../workspace/Icon'
import { getCaptionPreset, setCaptionPreset } from '../workspace/captionPreset'
import { Segmented, Spinner } from '../workspace/ui'

interface Preset {
  key: string
  label: string
  font: string
  size: number
  karaoke: string
}

interface RenderResult {
  url: string
  filename: string
  /** Absolute local path; publishing uploads this, not the URL. */
  path?: string
  duration: number
  bytes?: number
  encoder?: string
  pages?: number
  cached?: boolean
  crop?: { method: string; crop_w: number; knots: number[][]; confidence: number } | null
}

export interface RenderRequest {
  clipId: string
  nonce: number
}

const FRAMINGS = [
  { value: 'auto', label: 'Auto' },
  { value: 'blur', label: 'Blur pad' },
  { value: 'crop', label: 'Crop' },
]

const FRAMING_HINT: Record<string, string> = {
  auto: 'Tracks the subject and cuts a 9:16 column per shot.',
  blur: 'Fits the full frame over a blurred fill.',
  crop: 'Centre crop with no tracking.',
}

interface RenderPanelProps {
  sourceId: string
  clipId: string
  rank: number | null
  request: RenderRequest | null
  onNotify: (kind: 'ok' | 'error' | 'info', message: string) => void
  /** Lifts the finished file to the publish panel, which uploads by path. */
  onRendered?: (result: RenderResult | null) => void
}

export function RenderPanel({ sourceId, clipId, rank, request, onNotify, onRendered }: RenderPanelProps) {
  const [presets, setPresets] = useState<Preset[]>([])
  const [preset, setPreset] = useState(getCaptionPreset)
  const [clipStyle, setClipStyle] = useState<string | null>(null)
  const [framing, setFraming] = useState('auto')
  const [faceHint, setFaceHint] = useState('')
  const [plan, setPlan] = useState<{
    method: string
    crop_w: number
    knots: [number, number][]
    confidence: number
  } | null>(null)
  const [planState, setPlanState] = useState<'idle' | 'loading' | 'empty' | 'error'>('idle')
  const [status, setStatus] = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const [pct, setPct] = useState(0)
  const [detail, setDetail] = useState('')
  const [result, setResult] = useState<RenderResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const notified = useRef<number>(0)
  const notifyRef = useRef(onNotify)
  notifyRef.current = onNotify
  const renderedRef = useRef(onRendered)
  renderedRef.current = onRendered

  useEffect(() => {
    api
      .renderPresets()
      .then((list) => {
        setPresets(list)
        if (list.length) setPreset((current) => (list.some((item) => item.key === current) ? current : list[0].key))
      })
      .catch(() => setPresets([]))
    // Face tracking is opt-in and may be unavailable; say so once, next to the
    // control, rather than failing a render later.
    api
      .framingStatus()
      .then((status) => setFaceHint(status.available ? '' : status.hint))
      .catch(() => setFaceHint(''))
  }, [])

  useEffect(() => {
    setResult(null)
    setStatus('idle')
    setPct(0)
    setError(null)
    setJobId(null)
    setPlan(null)
    setPlanState('idle')
    setClipStyle(null)
    renderedRef.current?.(null)
    // The clip's saved style wins over this panel's fallback preset. Say which
    // one is in force rather than letting the chip disagree with the render.
    api
      .captionStyle(sourceId, clipId)
      .then((payload) => {
        const own =
          Object.keys(payload.overrides ?? {}).length > 0 ||
          (payload.preset && payload.preset !== getCaptionPreset())
        setClipStyle(own ? payload.label : null)
      })
      .catch(() => setClipStyle(null))
  }, [sourceId, clipId])

  useEffect(() => {
    if (status !== 'running' || !jobId) return
    return watchJob(
      jobId,
      (job) => {
        setPct(job.pct)
        setDetail(job.detail || job.stage)
        if (job.status === 'done') {
          const payload = (job as unknown as { analysis?: RenderResult }).analysis
          setResult(payload ?? null)
          renderedRef.current?.(payload ?? null)
          setStatus('done')
          notifyRef.current('ok', `Clip ${rank ?? ''} rendered — ready to download.`)
        } else if (job.status === 'cancelled') {
          setStatus('idle')
          setPct(0)
          setDetail('')
          notifyRef.current('info', 'Render cancelled.')
        } else if (job.status === 'error') {
          const message = job.error || 'Render failed.'
          setError(message)
          setStatus('error')
          notifyRef.current('error', message)
        }
      },
      750,
    )
  }, [status, jobId, rank])

  // Showing the plan before a render is the difference between "auto framing is
  // broken" and "auto framing chose the door, not the person".
  const checkPlan = async () => {
    setPlanState('loading')
    try {
      const payload = await api.framingPlan(sourceId, clipId)
      setPlan(payload.plan)
      setPlanState(payload.plan ? 'idle' : 'empty')
    } catch (failure) {
      setPlan(null)
      setPlanState('error')
      notifyRef.current('error', (failure as Error).message)
    }
  }

  const cancel = async () => {
    if (!jobId) return
    try {
      await api.cancelJob(jobId)
      notifyRef.current('info', 'Stopping after the current step…')
    } catch (failure) {
      notifyRef.current('error', (failure as Error).message)
    }
  }

  const start = async (force = false) => {
    setStatus('running')
    setPct(0)
    setError(null)
    setResult(null)
    try {
      const job = await api.renderClip(sourceId, clipId, preset, framing, force)
      setJobId(job.id)
    } catch (failure) {
      setError((failure as Error).message)
      setStatus('error')
      notifyRef.current('error', (failure as Error).message)
    }
  }

  useEffect(() => {
    if (!request || request.clipId !== clipId) return
    if (notified.current === request.nonce) return
    notified.current = request.nonce
    if (status === 'running') return
    void start()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request?.nonce, clipId])

  const running = status === 'running'

  return (
    <section className="inspector-section">
      <header className="section-head">
        <div>
          <span className="label">Render</span>
          <h3>Vertical master · 1080 × 1920</h3>
        </div>
        {result?.encoder ? <span className="pill ok">{result.encoder}</span> : null}
      </header>

      <div className="section-body stack-12">
        <div className="field-block">
          <span className="field-label">Caption preset</span>
          {presets.length ? (
            <div className="chip-row" role="group" aria-label="Caption preset">
              {presets.map((item) => (
                <button
                  type="button"
                  key={item.key}
                  className="chip"
                  data-on={preset === item.key}
                  disabled={running}
                  title={`${item.font} · ${item.size}px · ${item.karaoke}`}
                  onClick={() => {
                    setCaptionPreset(item.key)
                    setPreset(item.key)
                  }}
                >
                  {item.label}
                </button>
              ))}
            </div>
          ) : (
            <span className="panel-note">Default preset - the preset service is offline.</span>
          )}
          {clipStyle ? (
            <span className="field-hint">
              This clip has its own saved style ({clipStyle}) from Captions. It wins over the
              preset above.
            </span>
          ) : null}
        </div>

        <div className="field-block">
          <span className="field-label">Framing</span>
          <Segmented
            size="sm"
            ariaLabel="Framing strategy"
            value={framing}
            onChange={setFraming}
            options={FRAMINGS}
          />
          <span className="field-hint">{FRAMING_HINT[framing]}</span>
          {framing === 'auto' && faceHint ? <span className="field-hint">{faceHint}</span> : null}
          {framing === 'auto' ? (
            <div className="framing-plan">
              <div className="framing-plan-head">
                <button
                  type="button"
                  className="btn ghost sm"
                  onClick={() => void checkPlan()}
                  disabled={planState === 'loading' || running}
                >
                  <Icon name="eye" size={12} />
                  {planState === 'loading' ? 'Reading the shot…' : 'Inspect framing'}
                </button>
                {plan ? (
                  <span className="field-hint num">
                    {plan.method} · {plan.knots.length} knots · {Math.round(plan.confidence * 100)}%
                  </span>
                ) : null}
              </div>
              {plan && plan.knots.length ? (
                <svg
                  className="framing-plot"
                  viewBox="0 0 100 28"
                  role="img"
                  aria-label={`Crop path with ${plan.knots.length} knots, ${plan.crop_w} pixel wide column`}
                >
                  {(() => {
                    const last = plan.knots[plan.knots.length - 1][0] || 1
                    const peak = Math.max(1, ...plan.knots.map(([, x]) => x))
                    const points = plan.knots
                      .map(([t, x]) => `${(t / last) * 98 + 1},${27 - (x / peak) * 24}`)
                      .join(' ')
                    return (
                      <>
                        <line x1="0" y1="27" x2="100" y2="27" strokeWidth="0.4" className="framing-axis" />
                        <polyline points={points} strokeWidth="1.4" fill="none" className="framing-line" />
                      </>
                    )
                  })()}
                </svg>
              ) : null}
              {planState === 'empty' ? (
                <span className="field-hint">
                  The clip could not be sampled, so the render uses a still centre crop.
                </span>
              ) : null}
            </div>
          ) : null}
        </div>

        {running ? (
          <div className="render-progress" role="status">
            <div className="meter" aria-hidden="true">
              <i style={{ width: `${Math.round(pct * 100)}%` }} />
            </div>
            <div className="render-progress-meta">
              <span>
                <Spinner label="" /> {detail || 'Starting render'}
              </span>
              <span className="num">{Math.round(pct * 100)}%</span>
            </div>
            <button type="button" className="btn ghost sm" onClick={() => void cancel()}>
              Cancel render
            </button>
          </div>
        ) : (
          <button type="button" className="btn primary block" onClick={() => void start(status === 'done')}>
            <Icon name="sparkles" size={14} />
            {status === 'done' ? 'Render again' : 'Render clip'}
          </button>
        )}

        {error ? (
          <p className="warn-line">
            <Icon name="alert" size={13} />
            {error}
          </p>
        ) : null}

        {result ? (
          <div className="render-result">
            <video src={result.url} controls preload="metadata" aria-label={`Rendered clip ${rank ?? ''}`} />
            <dl className="render-facts">
              <div>
                <dt>Duration</dt>
                <dd className="num">{result.duration.toFixed(1)}s</dd>
              </div>
              <div>
                <dt>Captions</dt>
                <dd className="num">{result.pages !== undefined ? `${result.pages} pages` : 'burned in'}</dd>
              </div>
              <div>
                <dt>Framing</dt>
                <dd>{result.crop ? `${result.crop.knots.length} knots` : 'static'}</dd>
              </div>
              <div>
                <dt>Source</dt>
                <dd>{result.cached ? 'cached' : 'fresh'}</dd>
              </div>
            </dl>
            <div className="render-actions">
              <a className="btn primary sm" href={result.url} download={result.filename}>
                <Icon name="download" size={13} />
                Download MP4
              </a>
              <a className="btn ghost sm" href={result.url} target="_blank" rel="noreferrer">
                <Icon name="external" size={13} />
                Open
              </a>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  )
}
