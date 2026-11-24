import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

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

const FRAMINGS = [
  { id: 'auto', label: 'Auto' },
  { id: 'blur', label: 'Blur pad' },
  { id: 'crop', label: 'Crop' },
]

const FRAMING_HINT: Record<string, string> = {
  auto: 'Follows the subject and cuts a 9:16 column per shot',
  blur: 'Full picture fitted over a blurred fill',
  crop: 'Centre crop, no tracking',
}

/**
 * Render is the one stage that costs real wall-clock time, so it reports its
 * own progress and never blocks the reel.
 */
export function RenderPanel({ sourceId, clipId }: { sourceId: string; clipId: string }) {
  const [presets, setPresets] = useState<Preset[]>([])
  const [preset, setPreset] = useState('hormozi')
  const [framing, setFraming] = useState('auto')
  const [status, setStatus] = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const [pct, setPct] = useState(0)
  const [detail, setDetail] = useState('')
  const [result, setResult] = useState<RenderResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const jobRef = useRef<string | null>(null)

  useEffect(() => {
    api
      .renderPresets()
      .then((list) => {
        setPresets(list)
        if (list.length && !list.some((item) => item.key === preset)) setPreset(list[0].key)
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
        } else if (job.status === 'error') {
          setError(job.error)
          setStatus('error')
        }
      } catch (failure) {
        setError((failure as Error).message)
        setStatus('error')
      }
    }, 500)
    return () => window.clearInterval(timer)
  }, [status])

  const start = async () => {
    setStatus('running')
    setPct(0)
    setError(null)
    setResult(null)
    try {
      const job = await api.renderClip(sourceId, clipId, preset, framing)
      jobRef.current = job.id
    } catch (failure) {
      setError((failure as Error).message)
      setStatus('error')
    }
  }

  const running = status === 'running'

  return (
    <section className="panel">
      <header className="panel-head">
        <span className="label" style={{ color: 'var(--ink-2)' }}>
          Render 1080×1920
        </span>
        {result?.encoder ? (
          <span style={{ marginLeft: 'auto' }} className="pill">
            {result.encoder}
          </span>
        ) : null}
      </header>
      <div className="panel-body" style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
        <div className="chip-row">
          {presets.map((item) => (
            <button
              type="button"
              key={item.key}
              className="chip"
              data-on={preset === item.key}
              disabled={running}
              onClick={() => setPreset(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="chip-row">
          {FRAMINGS.map((item) => (
            <button
              type="button"
              key={item.id}
              className="chip"
              data-on={framing === item.id}
              disabled={running}
              title={FRAMING_HINT[item.id]}
              onClick={() => setFraming(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)' }}>
          {FRAMING_HINT[framing]}
        </span>

        {running ? (
          <>
            <div className="meter">
              <i style={{ width: `${Math.round(pct * 100)}%` }} />
            </div>
            <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)' }}>
              {detail || 'starting'} · {Math.round(pct * 100)}%
            </span>
          </>
        ) : (
          <button type="button" className="btn primary" onClick={() => void start()}>
            {status === 'done' ? 'Render again' : 'Render clip'}
          </button>
        )}

        {error ? <span className="warn-line">{error}</span> : null}

        {result ? (
          <div className="render-result">
            <video src={result.url} controls preload="metadata" />
            <div className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>
              {result.duration}s · {result.pages ?? 0} caption pages
              {result.crop ? ` · ${result.crop.knots.length} framing knots` : ''}
              {result.cached ? ' · cached' : ''} ·{' '}
              <a href={result.url} download={result.filename} style={{ color: 'var(--tungsten)' }}>
                download
              </a>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  )
}
