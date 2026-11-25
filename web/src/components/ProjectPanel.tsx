import { useMemo, useState } from 'react'
import { api, formatBytes, formatTime } from '../api'
import type { Analysis, LearnState, SourceRow } from '../types'
import { Icon } from '../workspace/Icon'
import { Tabs } from '../workspace/Tabs'
import { IconButton } from '../workspace/ui'
import { LearningPanel } from './bits'

interface ProjectPanelProps {
  sources: SourceRow[]
  selectedId: string | null
  learn: LearnState | null
  analysis: Analysis | null
  busy: boolean
  compact: boolean
  tab: 'project' | 'insights'
  ingestPath: string
  onTab: (tab: 'project' | 'insights') => void
  onSelect: (source: SourceRow) => void
  onIngestPath: (value: string) => void
  onIngest: () => void
  onDemo: () => void
  onRefreshLearn: () => Promise<void>
  onOpenSetup: () => void
  onSourceMenu: (source: SourceRow, position: { x: number; y: number }) => void
  onCollapse: () => void
}

function SourceThumb({ source }: { source: SourceRow }) {
  const [broken, setBroken] = useState(false)
  return (
    <span className="source-thumb" aria-hidden="true">
      {broken ? <Icon name="film" size={16} /> : null}
      {!broken ? (
        <video
          src={`${api.mediaUrl(source.id)}#t=4`}
          muted
          playsInline
          preload="metadata"
          tabIndex={-1}
          onError={() => setBroken(true)}
          onLoadedMetadata={(event) => {
            event.currentTarget.currentTime = Math.min(4, Math.max(0, source.duration - 1))
          }}
        />
      ) : null}
    </span>
  )
}

export function ProjectPanel({
  sources,
  selectedId,
  learn,
  analysis,
  busy,
  compact,
  tab,
  ingestPath,
  onTab,
  onSelect,
  onIngestPath,
  onIngest,
  onDemo,
  onRefreshLearn,
  onOpenSetup,
  onSourceMenu,
  onCollapse,
}: ProjectPanelProps) {
  const [query, setQuery] = useState('')
  const [refreshing, setRefreshing] = useState(false)

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return sources
    return sources.filter((source) => source.name.toLowerCase().includes(needle))
  }, [sources, query])

  const totals = useMemo(() => {
    const duration = sources.reduce((sum, source) => sum + source.duration, 0)
    const clips = sources.reduce((sum, source) => sum + source.clip_count, 0)
    return { duration, clips, analyzed: sources.filter((source) => source.analyzed).length }
  }, [sources])

  const warningCount = analysis?.warnings.length ?? 0

  return (
    <aside className="project-panel" id="project-panel" aria-label="Project panel">
      <header className="panel-chrome">
        <span className="panel-eyebrow">Project</span>
        <span className="panel-count num">{sources.length}</span>
        <div className="panel-actions">
          {compact ? <IconButton icon="x" size="sm" label="Close project panel" onClick={onCollapse} /> : null}
          {!compact ? <IconButton icon="panel-left" size="sm" label="Collapse project panel" onClick={onCollapse} /> : null}
        </div>
      </header>

      <Tabs
        idPrefix="project"
        variant="panel"
        ariaLabel="Project panel sections"
        value={tab}
        onChange={(id) => onTab(id as 'project' | 'insights')}
        items={[
          { id: 'project', label: 'Sources', icon: 'folder', badge: sources.length },
          { id: 'insights', label: 'Insights', icon: 'activity', badge: warningCount || undefined },
        ]}
      />

      <div
        className="project-body"
        role="tabpanel"
        id={`project-panel-${tab}`}
        aria-labelledby={`project-tab-${tab}`}
      >
        {tab === 'project' ? (
          <>
            <div className="bin-search">
              <Icon name="search" size={14} />
              <input
                data-field="source-search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Filter sources"
                aria-label="Filter sources"
                spellCheck={false}
              />
              {query ? (
                <button type="button" className="bin-search-clear" onClick={() => setQuery('')} aria-label="Clear source filter">
                  <Icon name="x" size={12} />
                </button>
              ) : null}
            </div>

            <div className="bin-summary">
              <span className="num">{sources.length}</span> sources
              <span aria-hidden="true">·</span>
              <span className="num">{totals.analyzed}</span> analyzed
              <span aria-hidden="true">·</span>
              <span className="num">{totals.clips}</span> clips
            </div>

            <div className="source-list" role="list" aria-label="Sources">
              {filtered.length === 0 ? (
                <p className="panel-empty">
                  {sources.length === 0
                    ? 'No sources yet. Import a file or generate the demo stream below.'
                    : `No source matches “${query.trim()}”.`}
                </p>
              ) : (
                filtered.map((source) => (
                  <article
                    key={source.id}
                    className="source-row"
                    role="listitem"
                    data-selected={source.id === selectedId ? 'true' : undefined}
                    onContextMenu={(event) => {
                      event.preventDefault()
                      onSourceMenu(source, { x: event.clientX, y: event.clientY })
                    }}
                  >
                    <button
                      type="button"
                      className="source-hit"
                      aria-current={source.id === selectedId ? 'true' : undefined}
                      onClick={() => onSelect(source)}
                      onDoubleClick={() => onSourceMenu(source, { x: window.innerWidth / 2, y: window.innerHeight / 2 })}
                    >
                      <SourceThumb source={source} />
                      <span className="source-text">
                        <span className="source-name" title={source.name}>
                          {source.name}
                        </span>
                        <span className="source-meta">
                          <span className="num">{formatTime(source.duration)}</span>
                          <span aria-hidden="true">·</span>
                          <span className="num">{formatBytes(source.size_bytes)}</span>
                          <span aria-hidden="true">·</span>
                          {source.analyzed ? (
                            <span className="source-ready">
                              <i aria-hidden="true" />
                              <span className="num">{source.clip_count} clips</span>
                            </span>
                          ) : (
                            <span className="source-idle">not analyzed</span>
                          )}
                        </span>
                      </span>
                    </button>
                    <button
                      type="button"
                      className="source-more"
                      aria-label={`Source actions for ${source.name}`}
                      title="Source actions"
                      onClick={(event) => {
                        const rect = event.currentTarget.getBoundingClientRect()
                        onSourceMenu(source, { x: rect.right - 4, y: rect.bottom + 2 })
                      }}
                    >
                      <Icon name="more" size={14} />
                    </button>
                  </article>
                ))
              )}
            </div>

            <form
              className="ingest"
              onSubmit={(event) => {
                event.preventDefault()
                if (ingestPath.trim() && !busy) onIngest()
              }}
            >
              <div className="ingest-head">
                <span className="label">Add a source</span>
                <span className="ingest-hint">file or VOD URL</span>
              </div>
              <label className="ingest-field">
                <Icon name="external" size={13} />
                <input
                  data-field="ingest"
                  value={ingestPath}
                  onChange={(event) => onIngestPath(event.target.value)}
                  placeholder="C:\VODs\stream.mp4  ·  https://twitch.tv/videos/…"
                  aria-label="Path or URL to ingest"
                  spellCheck={false}
                />
              </label>
              <div className="ingest-actions">
                <button type="submit" className="btn primary" disabled={!ingestPath.trim() || busy}>
                  <Icon name="upload" size={13} />
                  Ingest
                </button>
                <button type="button" className="btn ghost" onClick={onDemo} disabled={busy}>
                  <Icon name="sparkles" size={13} />
                  Demo stream
                </button>
              </div>
            </form>
          </>
        ) : (
          <div className="insights">
            <LearningPanel learn={learn} />

            <section className="insight-card">
              <header>
                <span className="label">Reel telemetry</span>
                {analysis ? <span className="pill ok">{Math.round(analysis.reel_quality * 100)}% quality</span> : null}
              </header>
              {analysis ? (
                <dl className="insight-metrics">
                  <div>
                    <dt>ASR</dt>
                    <dd title={analysis.asr_backend}>{analysis.asr_backend || '—'}</dd>
                  </div>
                  <div>
                    <dt>Scorer</dt>
                    <dd title={analysis.llm_backend}>{analysis.llm_backend || '—'}</dd>
                  </div>
                  <div>
                    <dt>Duration</dt>
                    <dd className="num">{formatTime(analysis.duration_s)}</dd>
                  </div>
                  <div>
                    <dt>Candidates</dt>
                    <dd className="num">{analysis.candidates.length}</dd>
                  </div>
                </dl>
              ) : (
                <p className="panel-note">Analyze a source to see backend and reel-quality telemetry.</p>
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
                Decisions and hook edits build the local re-ranker. The dataset is plain JSONL; nothing
                is uploaded.
              </p>
              <div className="insight-actions">
                <button
                  type="button"
                  className="btn ghost"
                  disabled={refreshing}
                  onClick={async () => {
                    setRefreshing(true)
                    try {
                      await onRefreshLearn()
                    } finally {
                      setRefreshing(false)
                    }
                  }}
                >
                  <Icon name="refresh" size={13} />
                  {refreshing ? 'Refreshing…' : 'Refresh profile'}
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

      <footer className="project-foot">
        <button type="button" className="hardware-button" onClick={onOpenSetup}>
          <Icon name="sliders" size={14} />
          <span>Hardware &amp; models</span>
          <Icon name="chevron-right" size={13} />
        </button>
        <div className="project-foot-meta">
          <span className="status-dot" aria-hidden="true" />
          <span>Local first</span>
          <span className="num">v0.1</span>
        </div>
      </footer>
    </aside>
  )
}
