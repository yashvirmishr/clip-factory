import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { Icon } from '../workspace/Icon'
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
  duration: number
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
}

export function RenderPanel({ sourceId, clipId, rank, request, onNotify }: RenderPanelProps) {
  const [presets, setPresets] = useState<Preset[]>([])
  const [preset, setPreset] = useState('hormozi')
  const [framing, setFraming] = useState('auto')
  const [status, setStatus] = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const [pct, setPct] = useState(0)
  const [detail, setDetail] = useState('')
  const [result, setResult] = useState<RenderResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const jobRef = useRef<string | null>(null)
  const notified = useRef<number>(0)
  const notifyRef = useRef(onNotify)
  notifyRef.current = onNotify

  useEffect(() => {
    api
      .renderPresets()
      .then((list) => {
        setPresets(list)
        if (list.length) setPreset((current) => (list.some((item) => item.key === current) ? current : list[0].key))
      })
      .catch(() => setPresets([]))
  }, [])

  useEffect(() => {
    setResult(null)
    setStatus('idle')
    setPct(0)
    setError(null)
    jobRef.current = null
  }, [clipId])

  useEffect(() => {
    if (status !== 'running') return
    const timer = window.setInterval(async () => {
      const id = jobRef.current
      if (!id) return
      try {
        const job = await api.job(id)
        setPct(job.pct)
        setDetail(job.detail || job.stage)
        if (job.status === 'done') {
          const payload = (job as unknown as { analysis?: RenderResult }).analysis
          setResult(payload ?? null)
          setStatus('done')
          notifyRef.current('ok', `Clip ${rank ?? ''} rendered — ready to download.`)
        } else if (job.status === 'error') {
          setError(job.error)
          setStatus('error')
          notifyRef.current('error', job.error || 'Render failed.')
        }
      } catch (failure) {
        setError((failure as Error).message)
        setStatus('error')
        notifyRef.current('error', (failure as Error).message)
      }
    }, 500)
    return () => window.clearInterval(timer)
  }, [status, rank])

  const start = async (force = false) => {
    setStatus('running')
    setPct(0)
    setError(null)
    setResult(null)
    try {
      const job = await api.renderClip(sourceId, clipId, preset, framing, force)
      jobRef.current = job.id
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
                  onClick={() => setPreset(item.key)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          ) : (
            <span className="panel-note">Default preset — the preset service is offline.</span>
          )}
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
