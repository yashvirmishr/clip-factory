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
  native_schedule?: boolean
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
  retry: 'warn',
  error: 'danger',
  failed: 'danger',
  cancelling: 'warn',
  cancelled: '',
}

function localInput(ms: number): string {
  const date = new Date(ms)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
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
  const [platform, setPlatform] = useState('youtube')
  const [accountId, setAccountId] = useState('')
  const pickedPlatform = useRef(false)
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
  const [scheduleAt, setScheduleAt] = useState('')
  const [issues, setIssues] = useState<Array<{ code: string; message: string }>>([])
  const [checked, setChecked] = useState(false)
  const [busy, setBusy] = useState(false)
  const [jobs, setJobs] = useState<Array<Record<string, unknown>>>([])
  const [error, setError] = useState<string | null>(null)
  const notifyRef = useRef(onNotify)
  notifyRef.current = onNotify

  const supported = platforms.filter(
    (entry) => entry.adapter && (entry.platform === 'youtube' || entry.platform === 'x'),
  )
  const availableAccounts = accounts.filter((entry) => entry.platform === platform)
  const account = availableAccounts.find((entry) => entry.id === accountId) ?? availableAccounts[0] ?? null
  const limits = platforms.find((entry) => entry.platform === platform)
  const mediaPath = rendered?.path ?? ''
  const isYouTube = platform === 'youtube'
  const platformLabel = limits?.label ?? (isYouTube ? 'YouTube Shorts' : 'X')
  const bodyOptions = VISIBILITY.filter((option) =>
    isYouTube ? true : option.value === 'public',
  )

  const load = useCallback(async () => {
    try {
      const payload = await api.accounts()
      setAccounts(payload.accounts)
      setPlatforms(payload.platforms)
      setSecretReady(payload.secret_store?.available !== false)
      setStoreHint(payload.secret_store?.detail ?? '')
      if (!pickedPlatform.current) {
        const connected = payload.accounts.find(
          (entry) => entry.platform === 'youtube' || entry.platform === 'x',
        )
        if (connected) setPlatform(connected.platform)
      }
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
    const onFocus = () => {
      void load()
      void loadJobs()
    }
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [load, loadJobs])

  useEffect(() => {
    if (!availableAccounts.some((entry) => entry.id === accountId)) {
      setAccountId(availableAccounts[0]?.id ?? '')
    }
  }, [availableAccounts, accountId])

  useEffect(() => {
    setTitle(clip.llm?.title || clip.llm?.hook || '')
    setCaption(clip.llm?.hook || '')
    setHashtags('shorts')
    setIssues([])
  }, [clip.id, clip.llm?.title, clip.llm?.hook])

  useEffect(() => {
    setVisibility(platform === 'x' ? 'public' : 'private')
    setHashtags(platform === 'x' ? '' : 'shorts')
    setClientId('')
    setClientSecret('')
    setIssues([])
    setChecked(false)
  }, [platform])

  // Only an upload in flight is worth re-reading; a job scheduled for later
  // gets one timer for its due time instead of a poll every few seconds.
  const uploading = jobs.some(
    (job) =>
      (job.status === 'queued' || job.status === 'retry' || job.status === 'running') &&
      Number(job.scheduled_at ?? 0) <= Date.now() / 1000 + 1,
  )
  const nextScheduled = jobs.reduce((soonest, job) => {
    const when = Number(job.scheduled_at ?? 0)
    if ((job.status !== 'queued' && job.status !== 'retry') || when <= Date.now() / 1000) return soonest
    return Math.min(soonest, when)
  }, Number.POSITIVE_INFINITY)
  useEffect(() => {
    if (!uploading && !Number.isFinite(nextScheduled)) return
    const delay = uploading
      ? 2500
      : Math.max(1000, Math.min((nextScheduled - Date.now() / 1000) * 1000 + 3000, 3_600_000))
    const timer = window.setTimeout(() => void loadJobs(), delay)
    return () => window.clearTimeout(timer)
  }, [uploading, nextScheduled, loadJobs])

  const connect = async () => {
    if (!clientId.trim()) {
      setError(
        isYouTube
          ? 'Paste the OAuth client ID from your Google Cloud project first.'
          : 'Paste the OAuth 2.0 client ID from your X developer app first.',
      )
      return
    }
    setConnecting(true)
    setError(null)
    // Opened before the request so the browser does not treat it as a popup.
    const tab = window.open('', '_blank')
    try {
      const start = await api.connectAccount(platform, clientId.trim(), clientSecret.trim())
      if (tab) tab.location.href = start.url
      else window.location.href = start.url
      notifyRef.current(
        'info',
        isYouTube ? 'Finish the Google consent, then come back here.' : 'Finish the X consent, then come back here.',
      )
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
        platform,
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
        payload.ok ? `Fits ${platformLabel} limits.` : 'This draft needs changes before it can upload.',
      )
    } catch (failure) {
      setError((failure as Error).message)
    }
  }

  const publish = async () => {
    if (!account || !mediaPath) return
    const when = scheduleAt ? Math.floor(new Date(scheduleAt).getTime() / 1000) : 0
    if (scheduleAt && (!Number.isFinite(when) || when <= Date.now() / 1000)) {
      setError('Pick a publish time in the future.')
      return
    }
    setBusy(true)
    setError(null)
    setIssues([])
    try {
      await api.publish({
        platform,
        account_id: account.id,
        media_path: mediaPath,
        title,
        caption,
        hashtags: splitTags(hashtags),
        visibility,
        made_for_kids: madeForKids,
        source_id: sourceId,
        clip_id: clip.id,
        scheduled_at: when || undefined,
      })
      notifyRef.current(
        'ok',
        when && !limits?.native_schedule
          ? 'Scheduled. It uploads at that time while the app is running.'
          : when
            ? 'Scheduled with the platform. Progress is below.'
            : 'Queued for upload. Progress is below.',
      )
      setScheduleAt('')
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
          <h3>Send this clip to {platformLabel}</h3>
        </div>
        {account ? <span className="pill ok">{account.handle || account.display_name || 'connected'}</span> : null}
      </header>

      <div className="section-body stack-12">
        {!secretReady ? (
          <p className="warn-line">
            <Icon name="alert" size={13} />
            {storeHint || 'Tokens need the operating system credential store; publishing stays off.'}
          </p>
        ) : null}

        {supported.length > 1 ? (
          <Field label="Destination">
            <select
              aria-label="Publishing destination"
              value={platform}
              onChange={(event) => {
                pickedPlatform.current = true
                setPlatform(event.target.value)
              }}
            >
              {supported.map((entry) => (
                <option key={entry.platform} value={entry.platform}>
                  {entry.label}
                </option>
              ))}
            </select>
          </Field>
        ) : null}

        {availableAccounts.length > 1 ? (
          <Field label="Account">
            <select
              aria-label="Publishing account"
              value={account?.id ?? ''}
              onChange={(event) => setAccountId(event.target.value)}
            >
              {availableAccounts.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.display_name || entry.handle || entry.external_id || entry.id}
                </option>
              ))}
            </select>
          </Field>
        ) : null}

        {account ? (
          <div className="account-row">
            <span>
              <b>{account.display_name || `${platformLabel} account`}</b>
              <em>{account.handle || account.external_id || ''}</em>
            </span>
            <button
              type="button"
              className="btn ghost sm"
              onClick={async () => {
                await api.disconnectAccount(account.id)
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
              {isYouTube ? (
                <>
                  YouTube upload needs your own Google OAuth client. In Google Cloud, create an OAuth
                  client of type <b>Web application</b> and add this exact redirect URI:
                </>
              ) : (
                <>
                  X publishing needs your own developer app. Enable <b>OAuth 2.0</b> with a
                  confidential client and add this exact callback:
                </>
              )}
              {' '}
              <span className="copy-row">
                <code className="bake-path">{REDIRECT_HINT}</code>
                <button
                  type="button"
                  className="icon-btn icon-btn-sm"
                  aria-label="Copy callback URL"
                  title="Copy callback URL"
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(REDIRECT_HINT)
                      notifyRef.current('ok', 'Callback URL copied.')
                    } catch {
                      notifyRef.current('error', 'Could not copy the callback; select it manually.')
                    }
                  }}
                >
                  <Icon name="copy" size={12} />
                </button>
              </span>
            </p>
            <TextField
              label="Client ID"
              value={clientId}
              placeholder={isYouTube ? '…apps.googleusercontent.com' : 'X OAuth 2.0 client ID'}
              onChange={setClientId}
            />
            <TextField
              label="Client secret"
              type="password"
              value={clientSecret}
              placeholder="stored in the OS credential store"
              onChange={setClientSecret}
            />
            <button type="button" className="btn sm block" onClick={() => void connect()} disabled={connecting || !secretReady}>
              {connecting ? <Spinner label="" /> : <Icon name="external" size={13} />}
              Connect {platformLabel}
            </button>
          </div>
        )}

        {account ? (
          <>
            {!rendered ? (
              <p className="panel-note">
                Render this clip first — publishing uploads the finished MP4, not the source.
              </p>
            ) : null}

            {isYouTube ? (
              <TextField
                label="Title"
                value={title}
                valueLabel={`${title.length}/${limits?.title_limit ?? 100}`}
                maxLength={limits?.title_limit ?? 100}
                onChange={setTitle}
              />
            ) : null}

            <TextField
              label={isYouTube ? 'Description' : 'Post text'}
              value={caption}
              valueLabel={`${caption.length}/${limits?.caption_limit ?? 280}`}
              rows={3}
              maxLength={limits?.caption_limit ?? 280}
              onChange={setCaption}
            />

            <TextField
              label="Hashtags"
              value={hashtags}
              valueLabel={`${splitTags(hashtags).length}/${limits?.max_hashtags ?? 15}`}
              placeholder={isYouTube ? 'shorts, highlights' : 'clip, highlight'}
              onChange={setHashtags}
            />

            <div className="subtitle-controls">
              <Field label="Visibility">
                <select
                  aria-label="Visibility"
                  value={visibility}
                  onChange={(event) => setVisibility(event.target.value)}
                >
                  {bodyOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </Field>
              {isYouTube ? (
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
              ) : null}
            </div>

            <Field label="Schedule (optional)">
              <input
                type="datetime-local"
                aria-label="Scheduled publish time"
                value={scheduleAt}
                min={localInput(Date.now() + 60_000)}
                onChange={(event) => setScheduleAt(event.target.value)}
              />
            </Field>
            {scheduleAt ? (
              <p className="field-hint">
                {limits?.native_schedule
                  ? 'The platform holds the upload until this time; it goes up even if the app is closed.'
                  : 'The app keeps this queued and uploads only while it is running.'}
              </p>
            ) : null}

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
              disabled={busy || !secretReady || !mediaPath || !(isYouTube ? title : caption).trim()}
            >
              {busy ? <Spinner label="" /> : <Icon name="upload" size={14} />}
              {scheduleAt ? `Schedule for ${platformLabel}` : `Queue upload to ${platformLabel}`}
            </button>
            <p className="field-hint">
              {mediaPath
                ? `Uploads ${rendered?.filename ?? 'the rendered MP4'} · ${rendered?.duration.toFixed(1) ?? '—'}s · ${limits?.aspect ?? '9:16'}`
                : 'Drive the render above and the finished file appears here.'}
            </p>
            <button type="button" className="btn ghost sm block" onClick={() => void check()} disabled={!mediaPath}>
              {checked ? 'Check again' : `Check against ${platformLabel} limits`}
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
                    {status === 'error' || status === 'failed' || status === 'cancelled' ? (
                      <button type="button" className="chip" onClick={() => void retry(String(job.id))}>
                        Retry
                      </button>
                    ) : job.post_url ? (
                      <a href={String(job.post_url)} target="_blank" rel="noreferrer">
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
