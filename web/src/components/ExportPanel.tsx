import { useEffect, useRef, useState } from 'react'
import { api, watchJob } from '../api'
import { getCaptionPreset } from '../workspace/captionPreset'
import { Icon } from '../workspace/Icon'
import { Spinner } from '../workspace/ui'

interface Props {
  sourceId: string
  clipId?: string | null
  clipCount: number
  onNotify?: (kind: 'ok' | 'error' | 'info', message: string) => void
}

interface BakeResult {
  folder: string
  baked: number
  failed: number
  clips: Array<{ id: string; name: string; file?: string; error?: string }>
}

const CAPTION_FORMATS = [
  { id: 'srt', label: 'SRT', hint: 'Every editor and player reads it' },
  { id: 'vtt', label: 'VTT', hint: 'Web players and YouTube uploads' },
  { id: 'ass', label: 'ASS', hint: 'Keeps the caption styling' },
]

const FORMATS = [
  { id: 'bundle', label: 'Bundle', extension: '.zip', hint: 'Everything below, plus any renders' },
  { id: 'otio', label: 'OTIO', extension: '.otio', hint: 'Resolve, Premiere (adapter), FilmCraft' },
  { id: 'fcpxml', label: 'FCP X', extension: '.fcpxml', hint: 'Final Cut Pro X, and Resolve' },
  { id: 'fcp7xml', label: 'FCP7 XML', extension: '.xml', hint: 'Native import in Premiere and Resolve' },
  { id: 'edl', label: 'EDL', extension: '.edl', hint: 'Universal fallback; cannot go offline' },
]

/**
 * Two different jobs live here: describing the edit for an NLE, and finishing
 * the clips so no editor is needed at all. They are separate on purpose - a
 * timeline that references a source is cheap, and a bake costs a full render
 * per clip. Conflating them is how people wait an hour for a file they did not
 * ask for.
 */
export function ExportPanel({ sourceId, clipId, clipCount, onNotify }: Props) {
  const [approvedOnly, setApprovedOnly] = useState(false)
  const [bake, setBake] = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const [pct, setPct] = useState(0)
  const [detail, setDetail] = useState('')
  const [result, setResult] = useState<BakeResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const notifyRef = useRef(onNotify)
  notifyRef.current = onNotify
  const suffix = approvedOnly ? '&approved_only=true' : ''
  const preset = getCaptionPreset()

  useEffect(() => {
    api
      .lastBake(sourceId)
      .then((payload) => {
        if (!payload.exists) return
        setResult({
          folder: payload.folder,
          baked: payload.baked ?? 0,
          failed: payload.failed ?? 0,
          clips: payload.clips ?? [],
        })
        setBake('done')
      })
      .catch(() => setBake('idle'))
  }, [sourceId])

  useEffect(() => {
    if (bake !== 'running' || !jobId) return
    return watchJob(
      jobId,
      (job) => {
        setPct(job.pct)
        setDetail(job.detail || job.stage)
        if (job.status === 'done') {
          const payload = (job as unknown as { analysis?: BakeResult }).analysis
          setResult(payload ?? null)
          setBake('done')
          notifyRef.current?.('ok', `${payload?.baked ?? 0} clips baked.`)
        } else if (job.status === 'cancelled') {
          setBake('idle')
          setPct(0)
          setDetail('')
          notifyRef.current?.('info', 'Bake cancelled.')
        } else if (job.status === 'error') {
          const message = job.error || 'Bake failed.'
          setError(message)
          setBake('error')
          notifyRef.current?.('error', message)
        }
      },
      750,
    )
  }, [bake, jobId])

  const cancelBake = async () => {
    if (!jobId) return
    try {
      await api.cancelJob(jobId)
      notifyRef.current?.('info', 'Stopping after the current clip…')
    } catch (failure) {
      notifyRef.current?.('error', (failure as Error).message)
    }
  }

  const startBake = async () => {
    setBake('running')
    setPct(0)
    setError(null)
    try {
      const job = await api.bakeReel(sourceId, preset, 'auto', approvedOnly)
      setJobId(job.id)
    } catch (failure) {
      setError((failure as Error).message)
      setBake('error')
      notifyRef.current?.('error', (failure as Error).message)
    }
  }

  return (
    <section className="inspector-section">
      <header className="section-head">
        <div>
          <span className="label">Handoff</span>
          <h3>Send the reel to an editor</h3>
        </div>
        <span className="pill numeric">{clipCount} clips</span>
      </header>
      <div className="section-body stack-10">
        <div className="format-grid">
          {FORMATS.map((format) => (
            <a
              key={format.id}
              className="format-card"
              title={format.hint}
              href={`/api/sources/${sourceId}/export?format=${format.id}${suffix}`}
              download
            >
              <span className="format-icon">
                <Icon name={format.id === 'bundle' ? 'download' : 'timeline'} size={15} />
              </span>
              <span className="format-copy">
                <b>{format.label}</b>
                <span>{format.extension}</span>
              </span>
              <Icon name="arrow-up-right" size={13} />
            </a>
          ))}
        </div>
        <label className="url-sheet-check">
          <input
            type="checkbox"
            checked={approvedOnly}
            onChange={(event) => setApprovedOnly(event.target.checked)}
          />
          <span>
            Approved clips only
            <em>Leave this off to export the whole ranked reel.</em>
          </span>
        </label>
        <p className="field-hint">
          A timeline of the whole reel with each hook, plus SRT caption pages. Media is referenced,
          never copied — an offline clip means the source moved.
        </p>
      </div>

      <div className="section-body stack-10">
        <span className="label">
          {clipId ? 'Captions for this clip' : 'Captions for the whole reel'}
        </span>
        <div className="format-grid">
          {CAPTION_FORMATS.map((format) => (
            <a
              key={format.id}
              className="format-card"
              title={format.hint}
              href={
                clipId
                  ? `/api/sources/${sourceId}/clips/${clipId}/subtitles?format=${format.id}&preset=${preset}`
                  : `/api/sources/${sourceId}/subtitles?format=${format.id}&preset=${preset}`
              }
              download
            >
              <span className="format-icon">
                <Icon name="captions" size={15} />
              </span>
              <span className="format-copy">
                <b>{format.label}</b>
                <span>{clipId ? 'this clip' : 'zip of all clips'}</span>
              </span>
              <Icon name="download" size={13} />
            </a>
          ))}
        </div>
        <p className="field-hint">
          The same pages the render burns, so retyping them in the editor cannot drift from the
          video.
        </p>
      </div>

      <div className="section-body stack-10">
        <span className="label">Finished files</span>
        <p className="field-hint">
          Bakes every clip at 1080 × 1920 with its captions burned in — nothing to import
          afterwards. Already-rendered clips are reused, so a second bake is quick.
        </p>
        {bake === 'running' ? (
          <div className="render-progress" role="status">
            <div className="meter" aria-hidden="true">
              <i style={{ width: `${Math.round(pct * 100)}%` }} />
            </div>
            <div className="render-progress-meta">
              <span>
                <Spinner label="" /> {detail || 'Starting the bake'}
              </span>
              <span className="num">{Math.round(pct * 100)}%</span>
            </div>
            <button type="button" className="btn ghost sm" onClick={() => void cancelBake()}>
              Cancel bake
            </button>
          </div>
        ) : (
          <button type="button" className="btn block" onClick={() => void startBake()}>
            <Icon name="download" size={14} />
            {bake === 'done' ? 'Bake again' : 'Bake reel to MP4s'}
          </button>
        )}

        {error ? (
          <p className="warn-line">
            <Icon name="alert" size={13} />
            {error}
          </p>
        ) : null}

        {result && bake === 'done' ? (
          <div className="bake-result">
            <p className="panel-note">
              {result.baked} of {result.baked + result.failed} clips baked
              {result.failed ? ` · ${result.failed} failed` : ''}. Folder:{' '}
              <code className="bake-path">{result.folder}</code>
            </p>
            <button
              type="button"
              className="btn ghost sm"
              onClick={async () => {
                try {
                  await api.revealFolder(result.folder)
                } catch (failure) {
                  notifyRef.current?.('error', (failure as Error).message)
                }
              }}
            >
              <Icon name="external" size={12} />
              Open folder
            </button>
            <div className="bake-list">
              {result.clips.map((clip) => (
                <div className="bake-row" key={clip.id}>
                  <span className="bake-name">{clip.name}</span>
                  {clip.file ? (
                    <a
                      className="btn ghost sm"
                      href={api.bakeFileUrl(sourceId, clip.file)}
                      download={clip.file}
                    >
                      <Icon name="download" size={12} />
                      MP4
                    </a>
                  ) : (
                    <span className="warn" title={clip.error}>
                      failed
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  )
}
