import { useCallback, useEffect, useState } from 'react'
import { api, formatTime } from '../api'
import type { Analysis, LearnState } from '../types'
import { Icon } from '../workspace/Icon'
import { Segmented } from '../workspace/ui'
import { AccountsPanel } from './AccountsPanel'
import { LearningPanel } from './bits'

type PublishTab = 'queue' | 'accounts' | 'insights'

interface PublishJob {
  id: string
  platform: string
  clip_id: string
  status: string
  stage: string
  progress: number
  attempts: number
  max_attempts: number
  post_url: string
  error: string
  created_at: number
  updated_at: number
}

interface PublishAreaProps {
  analysis: Analysis | null
  learn: LearnState | null
  onRefreshLearn: () => Promise<void>
  onNotify: (kind: 'ok' | 'error' | 'info', message: string) => void
  onOpenClips: () => void
}

const PLATFORM_LABEL: Record<string, string> = {
  youtube: 'YouTube',
  tiktok: 'TikTok',
  instagram: 'Instagram',
  x: 'X',
}

function when(seconds: number): string {
  if (!seconds) return '—'
  const date = new Date(seconds * 1000)
  const delta = (Date.now() - date.getTime()) / 1000
  if (delta < 60) return 'just now'
  if (delta < 3600) return `${Math.round(delta / 60)} min ago`
  if (delta < 86400) return `${Math.round(delta / 3600)} h ago`
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

/**
 * Publish is its own area because uploads are not a property of the clip you
 * happen to have selected: the queue outlives the selection.
 */
export function PublishArea({ analysis, learn, onRefreshLearn, onNotify, onOpenClips }: PublishAreaProps) {
  const [tab, setTab] = useState<PublishTab>('queue')
  const [jobs, setJobs] = useState<PublishJob[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)

  const load = useCallback(async (showSpinner = true) => {
    if (showSpinner) setRefreshing(true)
    try {
      const payload = await api.publishJobs(50)
      setJobs((payload.jobs as unknown as PublishJob[]) ?? [])
      setError('')
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setLoading(false)
      if (showSpinner) setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const active = jobs.some((job) => job.status === 'running' || job.status === 'queued' || job.status === 'retry')

  // Uploads advance server-side; follow them without making the user press
  // Refresh every few seconds. Manual refresh still works and shows a spinner.
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => void load(false), 5000)
    return () => window.clearInterval(timer)
  }, [active, load])

  const retry = async (job: PublishJob) => {
    try {
      await api.retryPublish(job.id)
      onNotify('ok', `${PLATFORM_LABEL[job.platform] ?? job.platform} retry queued.`)
      await load()
    } catch (failure) {
      onNotify('error', (failure as Error).message)
    }
  }

  const queued = jobs.filter((job) => job.status === 'queued' || job.status === 'retry' || job.status === 'running').length

  return (
    <section className="area area-publish" aria-label="Publish">
      <header className="area-head">
        <span className="area-eyebrow">Publish</span>
        <div className="area-title">
          <Segmented
            size="sm"
            ariaLabel="Publish sections"
            value={tab}
            onChange={(value) => setTab(value)}
            options={[
              { value: 'queue', label: 'Queue', count: queued || undefined },
              { value: 'accounts', label: 'Accounts' },
              { value: 'insights', label: 'Performance' },
            ]}
          />
        </div>
        <div className="area-actions">
          <span className="area-meta">
            {jobs.length === 0 ? 'No uploads yet' : `${jobs.length} upload${jobs.length === 1 ? '' : 's'}`}
          </span>
          <button type="button" className="btn sm ghost" disabled={refreshing} onClick={() => void load()}>
            <Icon name="refresh" size={13} />
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </header>

      <div className="publish-body">
        {tab === 'queue' ? (
          loading ? (
            <p className="panel-note publish-note">Reading the upload queue…</p>
          ) : error ? (
            <p className="panel-note publish-note">{error}</p>
          ) : jobs.length === 0 ? (
            <div className="publish-empty">
              <Icon name="upload" size={22} />
              <h2>Nothing has been uploaded yet</h2>
              <p>Render a clip, then publish it from the inspector. Uploads keep their place here even after you switch clips.</p>
              <button type="button" className="btn primary" onClick={onOpenClips}>
                <Icon name="film" size={13} />
                Open clips
              </button>
            </div>
          ) : (
            <div className="publish-table" role="table" aria-label="Upload queue">
              <div className="publish-row publish-head" role="row">
                <span role="columnheader">Clip</span>
                <span role="columnheader">Platform</span>
                <span role="columnheader">State</span>
                <span role="columnheader">Tries</span>
                <span role="columnheader">Created</span>
                <span role="columnheader" aria-label="Actions" />
              </div>
              {jobs.map((job) => (
                <div className="publish-row" role="row" key={job.id}>
                  <span className="publish-clip" role="cell">
                    <Icon name="film" size={12} />
                    {job.clip_id ? job.clip_id.slice(0, 8) : '—'}
                  </span>
                  <span role="cell">{PLATFORM_LABEL[job.platform] ?? job.platform}</span>
                  <span role="cell">
                    <span className="publish-state" data-status={job.status}>
                      {job.status === 'running' && job.stage ? `${job.status} · ${job.stage}` : job.status}
                    </span>
                    {job.error ? <span className="publish-error" title={job.error}>{job.error}</span> : null}
                  </span>
                  <span className="num" role="cell">
                    {job.attempts}/{job.max_attempts}
                  </span>
                  <span className="num publish-when" role="cell">{when(job.created_at)}</span>
                  <span className="publish-actions" role="cell">
                    {job.post_url ? (
                      <a className="btn sm ghost" href={job.post_url} target="_blank" rel="noreferrer">
                        <Icon name="external" size={12} />
                        Post
                      </a>
                    ) : null}
                    {job.status === 'failed' || job.status === 'error' ? (
                      <button type="button" className="btn sm ghost" onClick={() => void retry(job)}>
                        <Icon name="refresh" size={12} />
                        Retry
                      </button>
                    ) : null}
                  </span>
                </div>
              ))}
            </div>
          )
        ) : tab === 'accounts' ? (
          <div className="publish-scroll">
            <AccountsPanel onNotify={onNotify} />
          </div>
        ) : (
          <div className="publish-scroll publish-insights">
            <LearningPanel learn={learn} />

            <section className="insight-card">
              <header>
                <span className="label">Clip quality</span>
                {analysis ? <span className="pill ok">{Math.round(analysis.reel_quality * 100)}% quality</span> : null}
              </header>
              {analysis ? (
                <dl className="insight-metrics">
                  <div>
                    <dt>Speech</dt>
                    <dd title={analysis.asr_backend}>{analysis.asr_backend || '—'}</dd>
                  </div>
                  <div>
                    <dt>Ranking</dt>
                    <dd title={analysis.llm_backend}>{analysis.llm_backend || '—'}</dd>
                  </div>
                  <div>
                    <dt>Duration</dt>
                    <dd className="num">{formatTime(analysis.duration_s)}</dd>
                  </div>
                  <div>
                    <dt>Clips found</dt>
                    <dd className="num">{analysis.candidates.length}</dd>
                  </div>
                </dl>
              ) : (
                <p className="panel-note">Analyze a source to see what read the speech and how the clips ranked.</p>
              )}
            </section>

            {analysis?.warnings.length ? (
              <section className="insight-card">
                <header>
                  <span className="label">Warnings</span>
                  <span className="pill warn">{analysis.warnings.length}</span>
                </header>
                <div className="insight-warnings">
                  {analysis.warnings.map((warning) => (
                    <p className="warn-line" key={warning}>
                      <Icon name="alert" size={13} />
                      <span>{warning}</span>
                    </p>
                  ))}
                </div>
              </section>
            ) : null}

            <section className="insight-card">
              <header>
                <span className="label">Learning data</span>
              </header>
              <p className="panel-note">
                Decisions and hook edits build the local re-ranker. The dataset is plain JSONL; nothing is uploaded.
              </p>
              <div className="insight-actions">
                <button type="button" className="btn ghost" onClick={() => void onRefreshLearn()}>
                  <Icon name="refresh" size={13} />
                  Refresh profile
                </button>
                <a className="btn ghost" href="/api/learn/export" download="clip-factory-training.jsonl">
                  <Icon name="download" size={13} />
                  Export dataset
                </a>
              </div>
            </section>
          </div>
        )}
      </div>
    </section>
  )
}
