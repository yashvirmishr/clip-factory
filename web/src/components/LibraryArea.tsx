import { useEffect, useMemo, useState, type JSX, type MouseEvent } from 'react'
import { api, formatBytes, formatTime } from '../api'
import type { Analysis, SourceRow } from '../types'
import { Icon } from '../workspace/Icon'
import './library.css'

export interface LibraryAreaProps {
  sources: SourceRow[]
  selectedId: string | null
  analysis: Analysis | null
  busy: boolean
  ingestPath: string
  onSelect: (source: SourceRow) => void
  onIngestPath: (value: string) => void
  onIngest: () => void
  onDemo: () => void
  onAnalyze: () => void
  onOpenClips: () => void
  onSourceMenu: (source: SourceRow, position: { x: number; y: number }) => void
  onRelinkSource: (source: SourceRow) => void
  onRemoveSource: (source: SourceRow) => void
  onOpenSetup: () => void
}

function formatFps(fps: number): string {
  if (!Number.isFinite(fps) || fps <= 0) return '—'
  return `${Math.round(fps * 100) / 100} fps`
}

function LibraryThumb({ source }: { source: SourceRow }): JSX.Element {
  const [broken, setBroken] = useState(!source.available)
  return (
    <span className="library-thumb" aria-hidden="true">
      {broken ? <Icon name="film" size={16} /> : null}
      {!broken ? (
        <video
          src={`${api.mediaUrl(source.id, true)}#t=4`}
          muted
          playsInline
          preload="metadata"
          tabIndex={-1}
          onError={() => setBroken(true)}
          onLoadedMetadata={(event) => {
            event.currentTarget.currentTime = Math.min(4, Math.max(0, source.duration - 1))
          }}
          onLoadedData={(event) => {
            const target = Math.min(4, Math.max(0, source.duration - 1))
            if (Math.abs(event.currentTarget.currentTime - target) > 0.5) event.currentTarget.currentTime = target
          }}
        />
      ) : null}
    </span>
  )
}

export function LibraryArea({
  sources,
  selectedId,
  analysis,
  busy,
  ingestPath,
  onSelect,
  onIngestPath,
  onIngest,
  onDemo,
  onAnalyze,
  onOpenClips,
  onSourceMenu,
  onRelinkSource,
  onRemoveSource,
  onOpenSetup,
}: LibraryAreaProps): JSX.Element {
  const [query, setQuery] = useState('')
  // null means "untouched": an empty library opens the card, a populated one stays closed.
  const [ingestTouched, setIngestTouched] = useState<boolean | null>(null)
  const openIngest = ingestTouched ?? sources.length === 0

  // Menu, palette and tour all route "add a source" through this event, so the
  // form is open and focused by the time the click lands.
  useEffect(() => {
    const focusIngest = () => {
      setIngestTouched(true)
      window.setTimeout(() => {
        const node = document.querySelector<HTMLInputElement>('[data-tour="ingest"]')
        node?.scrollIntoView({ block: 'nearest' })
        node?.focus()
        node?.select()
      }, 90)
    }
    window.addEventListener('clip-factory:focus-ingest', focusIngest)
    return () => window.removeEventListener('clip-factory:focus-ingest', focusIngest)
  }, [])

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return sources
    return sources.filter(
      (source) =>
        source.name.toLowerCase().includes(needle) || source.path.toLowerCase().includes(needle),
    )
  }, [sources, query])

  const totals = useMemo(
    () => ({
      analyzed: sources.filter((source) => source.analyzed).length,
      clips: sources.reduce((sum, source) => sum + source.clip_count, 0),
    }),
    [sources],
  )

  const selected = sources.find((source) => source.id === selectedId) ?? null
  const selectedAnalysis =
    selected && analysis && analysis.source.id === selected.id ? analysis : null

  const menuFromButton = (event: MouseEvent<HTMLButtonElement>, source: SourceRow) => {
    const rect = event.currentTarget.getBoundingClientRect()
    onSourceMenu(source, { x: rect.right - 4, y: rect.bottom + 2 })
  }

  return (
    <section className="library" aria-label="Library">
      <header className="library-head">
        <div className="library-head-main">
          <span className="library-eyebrow">LIBRARY</span>
          <h1 className="library-title">Sources</h1>
          <span className="library-count num">{sources.length}</span>
        </div>
        <div className="library-head-actions">
          <button
            type="button"
            className="library-btn primary"
            aria-expanded={openIngest}
            aria-controls="library-ingest"
            onClick={() => setIngestTouched(!openIngest)}
          >
            <Icon name="plus" size={13} />
            Add source
          </button>
          <button type="button" className="library-btn ghost" onClick={onDemo} disabled={busy}>
            <Icon name="sparkles" size={13} />
            Demo stream
          </button>
        </div>
      </header>

      <div className="library-body">
        <div className="library-list">
          <div className="library-search">
            <Icon name="search" size={14} />
            <input
              data-field="source-search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search sources"
              aria-label="Search sources"
              spellCheck={false}
            />
            {query ? (
              <button
                type="button"
                className="library-search-clear"
                aria-label="Clear search"
                onClick={() => setQuery('')}
              >
                <Icon name="x" size={12} />
              </button>
            ) : null}
          </div>

          <p className="library-summary">
            <span className="num">{sources.length}</span> sources
            <span aria-hidden="true">·</span>
            <span className="num">{totals.analyzed}</span> analyzed
            <span aria-hidden="true">·</span>
            <span className="num">{totals.clips}</span> clips
          </p>

          {openIngest ? (
            <form
              className="library-ingest"
              id="library-ingest"
              onSubmit={(event) => {
                event.preventDefault()
                if (ingestPath.trim() && !busy) onIngest()
              }}
            >
              <span className="library-ingest-label">Add a source</span>
              <label className="library-ingest-field">
                <Icon name="external" size={13} />
                <input
                  data-tour="ingest"
                  value={ingestPath}
                  onChange={(event) => onIngestPath(event.target.value)}
                  placeholder="C:\VODs\stream.mp4  ·  https://twitch.tv/videos/…"
                  aria-label="Path or URL to ingest"
                  spellCheck={false}
                />
              </label>
              <div className="library-ingest-actions">
                <button type="submit" className="library-btn primary" disabled={!ingestPath.trim() || busy}>
                  <Icon name="upload" size={13} />
                  Ingest
                </button>
                <button type="button" className="library-btn ghost" onClick={onDemo} disabled={busy}>
                  <Icon name="sparkles" size={13} />
                  Demo stream
                </button>
              </div>
              <p className="library-ingest-hint">A file path or a VOD URL. Nothing leaves this machine.</p>
            </form>
          ) : null}

          <div className="library-rows">
            {filtered.length === 0 ? (
              <p className="library-rows-empty">
                {sources.length === 0
                  ? 'No sources yet. Add a file path or a VOD URL to begin.'
                  : `No source matches “${query.trim()}”.`}
              </p>
            ) : (
              <div className="library-rows-list" role="list" aria-label="Library sources">
                {filtered.map((source) => {
                  const isSelected = source.id === selectedId
                  return (
                    <article
                      key={source.id}
                      role="listitem"
                      className="library-row"
                      data-selected={isSelected ? 'true' : undefined}
                    >
                      <button
                        type="button"
                        className="library-row-hit"
                        aria-current={isSelected ? 'true' : undefined}
                        onClick={() => onSelect(source)}
                        onContextMenu={(event) => {
                          event.preventDefault()
                          onSourceMenu(source, { x: event.clientX, y: event.clientY })
                        }}
                      >
                        <LibraryThumb source={source} />
                        <span className="library-row-text">
                          <span className="library-row-name" title={source.name}>
                            {source.name}
                            {!source.available ? (
                              <span className="library-row-missing">Missing</span>
                            ) : null}
                          </span>
                          <span className="library-row-meta">
                            <span className="num">{formatTime(source.duration)}</span>
                            <span aria-hidden="true">·</span>
                            <span className="num">{source.clip_count} clips</span>
                            <span aria-hidden="true">·</span>
                            {source.analyzed ? (
                              <span className="library-row-ready">
                                <i aria-hidden="true" />
                                <span>analyzed</span>
                              </span>
                            ) : (
                              <span className="library-row-idle">not analyzed</span>
                            )}
                          </span>
                        </span>
                      </button>
                      <button
                        type="button"
                        className="library-row-more"
                        aria-label={`Source actions for ${source.name}`}
                        title="Source actions"
                        onClick={(event) => menuFromButton(event, source)}
                      >
                        <Icon name="more" size={14} />
                      </button>
                    </article>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        <div className="library-detail">
          {!selected ? (
            <div className="library-empty">
              <span className="library-empty-icon">
                <Icon name="film" size={20} />
              </span>
              <p className="library-empty-title">No source selected</p>
              <p className="library-empty-copy">Choose a source on the left, or add one.</p>
            </div>
          ) : (
            <>
              <div className={selected.available ? 'library-player' : 'library-player library-player-missing'}>
                {selected.available ? (
                  <video
                    key={`${selected.id}:${selected.path}`}
                    controls
                    muted
                    preload="metadata"
                    src={api.mediaUrl(selected.id)}
                  />
                ) : (
                  <div className="library-missing">
                    <Icon name="alert" size={18} />
                    <p className="library-missing-title">This file is not where it was</p>
                    <p className="library-missing-copy">
                      It may have been moved or renamed. Relink it to keep its analysis and
                      clips, or remove it from the library.
                    </p>
                    <div className="library-missing-actions">
                      <button
                        type="button"
                        className="library-btn primary"
                        onClick={() => onRelinkSource(selected)}
                      >
                        <Icon name="search" size={13} />
                        Relink file
                      </button>
                      <button
                        type="button"
                        className="library-btn ghost"
                        onClick={() => onRemoveSource(selected)}
                      >
                        <Icon name="trash" size={13} />
                        Remove
                      </button>
                    </div>
                  </div>
                )}
              </div>

              <div className="library-detail-head">
                <h2 className="library-detail-name" title={selected.name}>
                  {selected.name}
                </h2>
                <p className="library-detail-path" title={selected.path}>
                  {selected.path}
                </p>
              </div>

              <div className="library-actions">
                <button
                  type="button"
                  className="library-btn primary"
                  disabled={busy || !selected.available}
                  title={selected.available ? undefined : 'Relink the file first'}
                  onClick={onAnalyze}
                >
                  <Icon name="activity" size={13} />
                  {selected.analyzed ? 'Re-analyze' : 'Analyze'}
                </button>
                <button type="button" className="library-btn ghost" onClick={onOpenClips}>
                  <Icon name="scissors" size={13} />
                  Open in Clips
                </button>
                <button
                  type="button"
                  className="library-btn ghost"
                  onClick={(event) => menuFromButton(event, selected)}
                >
                  <Icon name="more" size={13} />
                  Source actions
                </button>
              </div>

              <dl className="library-facts">
                <div className="library-fact">
                  <dt>Duration</dt>
                  <dd className="num">{formatTime(selected.duration)}</dd>
                </div>
                <div className="library-fact">
                  <dt>Resolution</dt>
                  <dd className="num">
                    {selected.width}×{selected.height}
                  </dd>
                </div>
                <div className="library-fact">
                  <dt>Frame rate</dt>
                  <dd className="num">{formatFps(selected.fps)}</dd>
                </div>
                <div className="library-fact">
                  <dt>Size</dt>
                  <dd className="num">{formatBytes(selected.size_bytes)}</dd>
                </div>
                <div className="library-fact">
                  <dt>Clips</dt>
                  <dd className="num">{selected.clip_count}</dd>
                </div>
                <div className="library-fact">
                  <dt>Analyzed</dt>
                  <dd className="num">{selected.analyzed ? 'Yes' : 'No'}</dd>
                </div>
                <div className="library-fact">
                  <dt>Speech</dt>
                  <dd className="num">{selectedAnalysis?.asr_backend || '—'}</dd>
                </div>
                <div className="library-fact">
                  <dt>Ranking</dt>
                  <dd className="num">{selectedAnalysis?.llm_backend || '—'}</dd>
                </div>
              </dl>

              {selectedAnalysis ? (
                <section className="library-analysis" aria-label="Clip quality">
                  <div className="library-analysis-head">
                    <span className="library-analysis-label">Clip quality</span>
                    <span className="library-pill num">
                      {Math.round(selectedAnalysis.reel_quality * 100)}% quality
                    </span>
                  </div>
                  {selectedAnalysis.warnings.length > 0 ? (
                    <ul className="library-warnings">
                      {selectedAnalysis.warnings.map((warning, index) => (
                        <li className="library-warning" key={`${index}-${warning}`}>
                          <Icon name="alert" size={13} />
                          <span>{warning}</span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  <p className="library-backends">
                    <span>
                      Speech <b>{selectedAnalysis.asr_backend || '—'}</b>
                    </span>
                    <span>
                      Ranking <b>{selectedAnalysis.llm_backend || '—'}</b>
                    </span>
                  </p>
                </section>
              ) : (
                <div className="library-note">
                  <p>Analyze this source to see clip quality.</p>
                  <button type="button" className="library-link" onClick={onOpenSetup}>
                    Hardware &amp; models
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  )
}
