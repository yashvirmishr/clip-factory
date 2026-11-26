import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { Clip } from '../types'
import { Icon } from '../workspace/Icon'
import { Field, Spinner, TextField } from '../workspace/ui'

interface Account {
  id: string
  platform: string
  handle?: string
  display_name?: string
  external_id?: string
}

interface Platform {
  platform: string
  label: string
  min_duration_s: number
  max_duration_s: number
  caption_limit: number
  title_limit: number
  max_hashtags: number
  aspect: string
  connected: number
  adapter: boolean
}

export interface RenderedClip {
  path?: string
  filename: string
  duration: number
  bytes?: number
}

interface Props {
  sourceId: string
  clip: Clip
  rendered: RenderedClip | null
  onNotify: (kind: 'ok' | 'error' | 'info', message: string) => void
}

const REDIRECT_HINT = 'http://127.0.0.1:8756/api/connections/callback'

const VISIBILITY = [
  { value: 'private', label: 'Private' },
  { value: 'unlisted', label: 'Unlisted' },
  { value: 'public', label: 'Public' },
]

const JOB_TONE: Record<string, string> = {
  queued: 'warn',
  running: 'warn',
  done: 'ok',
  failed: 'danger',
  cancelled: '',
}

function splitTags(value: string): string[] {
  return value
    .split(/[\s,]+/)
    .map((tag) => tag.replace(/^#/, '').trim())
    .filter(Boolean)
}

/**
 * Publishing is the one flow in the app that leaves the machine, so it states
 * its needs plainly: a connected account, a rendered file, and metadata that
 * fits the platform. Validation runs on the server with the same limits the
 * upload enforces - a client-side copy of those numbers would drift.
 */
export function PublishPanel({ sourceId, clip, rendered, onNotify }: Props) {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [platforms, setPlatforms] = useState<Platform[]>([])
  const [secretReady, setSecretReady] = useState(true)
  const [storeHint, setStoreHint] = useState('')
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [connecting, setConnecting] = useState(false)
  const [title, setTitle] = useState('')
  const [caption, setCaption] = useState('')
  const [hashtags, setHashtags] = useState('')
  const [visibility, setVisibility] = useState('private')
  const [madeForKids, setMadeForKids] = useState(false)
  const [issues, setIssues] = useState<Array<{ code: string; message: string }>>([])
  const [checked, setChecked] = useState(false)
  const [busy, setBusy] = useState(false)
  const [jobs, setJobs] = useState<Array<Record<string, unknown>>>([])
  const [error, setError] = useState<string | null>(null)
  const notifyRef = useRef(onNotify)
  notifyRef.current = onNotify

  const youtube = accounts.find((account) => account.platform === 'youtube') ?? null
  const limits = platforms.find((platform) => platform.platform === 'youtube')
  const mediaPath = rendered?.path ?? ''

  const load = useCallback(async () => {
    try {
      const payload = await api.accounts()
      setAccounts(payload.accounts)
      setPlatforms(payload.platforms)
      setSecretReady(payload.secret_store?.available !== false)
      setStoreHint(payload.secret_store?.hint ?? '')
    } catch (failure) {
      setError((failure as Error).message)
    }
  }, [])

  const loadJobs = useCallback(async () => {
    try {
      const payload = await api.publishJobs()
      setJobs(payload.jobs)
    } catch {
      /* the queue is optional context; a failure here is not the panel's job */
    }
  }, [])

  useEffect(() => {
    void load()
    void loadJobs()
  }, [load, loadJobs])

  useEffect(() => {
    setTitle(clip.llm?.title || clip.llm?.hook || '')
    setCaption(clip.llm?.hook || '')
    setHashtags('shorts')
    setIssues([])
  }, [clip.id, clip.llm?.title, clip.llm?.hook])

  // Only an upload in flight is worth re-reading; keyed on that flag so the
  // timer is not torn down and recreated on every result.
  const uploading = jobs.some((job) => job.status === 'queued' || job.status === 'running')
  useEffect(() => {
    if (!uploading) return
    const timer = window.setInterval(() => void loadJobs(), 2500)
    return () => window.clearInterval(timer)
  }, [uploading, loadJobs])

  const connect = async () => {
    if (!clientId.trim()) {
      setError('Paste the OAuth client ID from your Google Cloud project first.')
      return
    }
    setConnecting(true)
    setError(null)
    // Opened before the request so the browser does not treat it as a popup.
    const tab = window.open('', '_blank')
    try {
      const start = await api.connectAccount('youtube', clientId.trim(), clientSecret.trim())
      if (tab) tab.location.href = start.url
      else window.location.href = start.url
      notifyRef.current('info', 'Finish the Google consent, then come back here.')
    } catch (failure) {
      tab?.close()
      setError((failure as Error).message)
      notifyRef.current('error', (failure as Error).message)
    } finally {
      setConnecting(false)
    }
  }

  const check = async () => {
    if (!rendered) return
    setError(null)
    try {
      // Validate only: this route never enqueues an upload.
      const payload = await api.validatePublish({
        platform: 'youtube',
        media_path: mediaPath,
        title,
        caption,
        hashtags: splitTags(hashtags),
        visibility,
        made_for_kids: madeForKids,
      })
      setIssues(payload.issues.map((issue) => ({ code: issue.code, message: issue.remedy || issue.message })))
      setChecked(true)
      notifyRef.current(
        payload.ok ? 'ok' : 'error',
        payload.ok ? 'Fits YouTube Shorts limits.' : 'This draft needs changes before it can upload.',
      )
    } catch (failure) {
      setError((failure as Error).message)
    }
  }

  const publish = async () => {
    if (!youtube || !mediaPath) return
    setBusy(true)
    setError(null)
    setIssues([])
    try {
      await api.publish({
        platform: 'youtube',
        account_id: youtube.id,
        media_path: mediaPath,
        title,
        caption,
        hashtags: splitTags(hashtags),
        visibility,
        made_for_kids: madeForKids,
        source_id: sourceId,
        clip_id: clip.id,
      })
      notifyRef.current('ok', 'Queued for upload. Progress is below.')
      void loadJobs()
    } catch (failure) {
      const message = (failure as Error).message
      setError(message)
      notifyRef.current('error', message)
    } finally {
      setBusy(false)
    }
  }

  const retry = async (jobId: string) => {
    try {
      await api.retryPublish(jobId)
      void loadJobs()
    } catch (failure) {
      setError((failure as Error).message)
    }
  }

  return (
    <section className="inspector-section">
      <header className="section-head">
        <div>
          <span className="label">Publish</span>
          <h3>Send this clip to YouTube</h3>
        </div>
        {youtube ? <span className="pill ok">{youtube.handle || youtube.display_name || 'connected'}</span> : null}
      </header>

      <div className="section-body stack-12">
        {!secretReady ? (
          <p className="warn-line">
            <Icon name="alert" size={13} />
            {storeHint || 'Tokens need the operating system credential store; publishing stays off.'}
          </p>
        ) : null}

        {youtube ? (
          <div className="account-row">
            <span>
              <b>{youtube.display_name || 'YouTube channel'}</b>
              <em>{youtube.handle || youtube.external_id || ''}</em>
            </span>
            <button
              type="button"
              className="btn ghost sm"
              onClick={async () => {
                await api.disconnectAccount(youtube.id)
                await load()
                notifyRef.current('info', 'Account disconnected.')
              }}
            >
              Disconnect
            </button>
          </div>
        ) : (
          <div className="publish-connect">
            <p className="field-hint">
              YouTube upload needs your own Google OAuth client. In Google Cloud, create an OAuth
              client of type <b>Web application</b> and add this exact redirect URI:
              <code className="bake-path">{REDIRECT_HINT}</code>
            </p>
            <TextField
              label="Client ID"
              value={clientId}
              placeholder="…apps.googleusercontent.com"
              onChange={setClientId}
            />
            <TextField
              label="Client secret"
              type="password"
              value={clientSecret}
              placeholder="stored in the OS credential store"
              onChange={setClientSecret}
            />
            <button type="button" className="btn sm block" onClick={() => void connect()} disabled={connecting}>
              {connecting ? <Spinner label="" /> : <Icon name="external" size={13} />}
              Connect YouTube
            </button>
          </div>
        )}

        {youtube ? (
          <>
            {!rendered ? (
              <p className="panel-note">
                Render this clip first — publishing uploads the finished MP4, not the source.
              </p>
            ) : null}

            <TextField
              label="Title"
              value={title}
              valueLabel={`${title.length}/${limits?.title_limit ?? 100}`}
              maxLength={limits?.title_limit ?? 100}
              onChange={setTitle}
            />

            <TextField
              label="Description"
              value={caption}
              valueLabel={`${caption.length}/${limits?.caption_limit ?? 5000}`}
              rows={3}
              maxLength={limits?.caption_limit ?? 5000}
              onChange={setCaption}
            />

            <TextField
              label="Hashtags"
              value={hashtags}
              valueLabel={`${splitTags(hashtags).length}/${limits?.max_hashtags ?? 15}`}
              placeholder="shorts, highlights"
              onChange={setHashtags}
            />

            <div className="subtitle-controls">
              <Field label="Visibility">
                <select
                  aria-label="Visibility"
                  value={visibility}
                  onChange={(event) => setVisibility(event.target.value)}
                >
                  {VISIBILITY.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Audience">
                <button
                  type="button"
                  className="chip"
                  data-on={madeForKids}
                  onClick={() => setMadeForKids((value) => !value)}
                  title="YouTube requires this to be declared"
                >
                  {madeForKids ? 'Made for kids' : 'Not for kids'}
                </button>
              </Field>
            </div>

            {issues.length ? (
              <ul className="publish-issues">
                {issues.map((issue) => (
                  <li key={issue.code}>{issue.message}</li>
                ))}
              </ul>
            ) : null}

            <button
              type="button"
              className="btn primary block"
              onClick={() => void publish()}
              disabled={busy || !mediaPath || !title.trim()}
            >
              {busy ? <Spinner label="" /> : <Icon name="upload" size={14} />}
              Queue upload
            </button>
            <p className="field-hint">
              {mediaPath
                ? `Uploads ${rendered?.filename ?? 'the rendered MP4'} · ${rendered?.duration.toFixed(1) ?? '—'}s · ${limits?.aspect ?? '9:16'}`
                : 'Drive the render above and the finished file appears here.'}
            </p>
            <button type="button" className="btn ghost sm block" onClick={() => void check()} disabled={!mediaPath}>
              {checked ? 'Check again' : 'Check against YouTube limits'}
            </button>
            {checked && !issues.length ? (
              <p className="field-hint">{limits ? `Fits ${limits.label}: ${limits.aspect}, ${limits.min_duration_s}–${limits.max_duration_s}s.` : 'Fits the platform limits.'}</p>
            ) : null}
          </>
        ) : null}

        {error ? (
          <p className="warn-line">
            <Icon name="alert" size={13} />
            {error}
          </p>
        ) : null}

        {jobs.length ? (
          <div className="publish-jobs">
            <span className="label">Recent uploads</span>
            {jobs.map((job) => {
              const status = String(job.status ?? '')
              return (
                <div className="bake-row" key={String(job.id)}>
                  <span className="bake-name">
                    {String(job.platform ?? 'youtube')} · {status}
                    {job.error ? ` · ${String(job.error).slice(0, 60)}` : ''}
                  </span>
                  <span className={`pill ${JOB_TONE[status] ?? ''}`}>
                    {status === 'failed' || status === 'cancelled' ? (
                      <button type="button" className="chip" onClick={() => void retry(String(job.id))}>
                        Retry
                      </button>
                    ) : job.url ? (
                      <a href={String(job.url)} target="_blank" rel="noreferrer">
                        Open
                      </a>
                    ) : (
                      '—'
                    )}
                  </span>
                </div>
              )
            })}
          </div>
        ) : null}
      </div>
    </section>
  )
}
