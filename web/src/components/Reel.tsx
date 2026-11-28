import { memo } from 'react'
import { api } from '../api'
import type { Analysis, Clip, Verdict } from '../types'
import { Icon } from '../workspace/Icon'
import { IconButton, Segmented, Spinner } from '../workspace/ui'
import { ClipCard } from './ClipCard'

export type ClipFilter = 'all' | 'approved' | 'rejected' | 'pending'
export type ClipSort = 'rank' | 'score' | 'duration'
export type ClipView = 'list' | 'grid'

export const REJECT_REASONS = ['boring', 'confusing', 'cut off', 'spoiler', 'off topic', 'duplicate']

interface ReelProps {
  clips: Clip[]
  counts: Record<ClipFilter, number>
  sourceId: string | null
  mediaSrc: string
  selectedId: string | null
  verdicts: Record<string, Verdict>
  filter: ClipFilter
  sort: ClipSort
  view: ClipView
  query: string
  hasSource: boolean
  analysis: Analysis | null
  busy: boolean
  onFilter: (filter: ClipFilter) => void
  onSort: (sort: ClipSort) => void
  onView: (view: ClipView) => void
  onQuery: (query: string) => void
  onSelect: (clipId: string) => void
  onOpen: (clip: Clip) => void
  onVerdict: (clipId: string, verdict: Verdict) => void
  onMenu: (clip: Clip, position: { x: number; y: number }) => void
  onAnalyze: () => void
  onDemo: () => void
  onTour?: () => void
  onImport: () => void
}

export const Reel = memo(function Reel({
  clips,
  counts,
  sourceId,
  mediaSrc,
  selectedId,
  verdicts,
  filter,
  sort,
  view,
  query,
  hasSource,
  analysis,
  busy,
  onFilter,
  onSort,
  onView,
  onQuery,
  onSelect,
  onOpen,
  onVerdict,
  onMenu,
  onAnalyze,
  onDemo,
  onTour,
  onImport,
}: ReelProps) {
  const warningCount = analysis?.warnings.length ?? 0
  const isFiltered = filter !== 'all' || query.trim().length > 0

  return (
    <div className="reel" data-tour="clips">
      <div className="tab-toolbar reel-toolbar">
        <Segmented
          size="sm"
          ariaLabel="Filter clips by verdict"
          value={filter}
          onChange={onFilter}
          options={[
            { value: 'all', label: 'All', count: counts.all },
            { value: 'approved', label: 'Approved', count: counts.approved || undefined },
            { value: 'rejected', label: 'Rejected', count: counts.rejected || undefined },
            { value: 'pending', label: 'Unreviewed', count: counts.pending || undefined },
          ]}
        />

        <label className="field field-search reel-search">
          <Icon name="search" size={13} />
          <input
            data-field="clip-search"
            value={query}
            onChange={(event) => onQuery(event.target.value)}
            placeholder="Find a hook"
            aria-label="Search clips"
            spellCheck={false}
          />
          {query ? (
            <button type="button" className="field-clear" onClick={() => onQuery('')} aria-label="Clear clip search">
              <Icon name="x" size={11} />
            </button>
          ) : null}
        </label>

        <span className="toolbar-spacer" />

        <label className="select-wrap" title="Sort clips">
          <Icon name="sort" size={13} />
          <select
            value={sort}
            onChange={(event) => onSort(event.target.value as ClipSort)}
            aria-label="Sort clips"
          >
            <option value="rank">Rank</option>
            <option value="score">Score</option>
            <option value="duration">Duration</option>
          </select>
          <Icon name="chevron-down" size={12} />
        </label>

        <div className="view-toggle">
          <IconButton
            icon={view === 'list' ? 'grid' : 'list'}
            size="sm"
            label={view === 'list' ? 'Switch to grid view' : 'Switch to list view'}
            onClick={() => onView(view === 'list' ? 'grid' : 'list')}
          />
        </div>
      </div>

      {warningCount ? (
        <details className="reel-warnings">
          <summary>
            <Icon name="alert" size={13} />
            <span>
              {warningCount} pipeline {warningCount === 1 ? 'warning' : 'warnings'}
            </span>
            <Icon name="chevron-down" size={13} />
          </summary>
          <div className="reel-warnings-body">
            {analysis?.warnings.map((warning) => (
              <p key={warning}>{warning}</p>
            ))}
          </div>
        </details>
      ) : null}

      <div className="reel-scroll">
        {!hasSource ? (
          <div className="work-empty">
            <span className="work-empty-mark" aria-hidden="true">
              <Icon name="film" size={22} />
            </span>
            <h2>No source yet.</h2>
            <p>
              Add a recording in Library, or generate the demo stream, to see the pipeline end to
              end.
            </p>
            <div className="work-empty-actions">
              <button type="button" className="btn primary" onClick={onImport} disabled={busy}>
                <Icon name="upload" size={14} />
                Import a recording
              </button>
              <button type="button" className="btn ghost" onClick={onDemo} disabled={busy}>
                <Icon name="sparkles" size={14} />
                Generate demo stream
              </button>
              {onTour ? (
                <button type="button" className="btn ghost" onClick={onTour}>
                  Take the tour
                </button>
              ) : null}
            </div>
          </div>
        ) : !analysis && busy ? (
          <div className="work-empty">
            <Spinner label="Analyzing source" />
            <h2>Reading the tape.</h2>
            <p>Audio, words and scores are being prepared. The clip list fills in by itself.</p>
          </div>
        ) : !analysis ? (
          <div className="work-empty">
            <span className="work-empty-mark" aria-hidden="true">
              <Icon name="sparkles" size={22} />
            </span>
            <h2>This source is unread.</h2>
            <p>
              Analysis reads the speech, scores the moments and fills this list. If it
              falls back to a stand-in transcript, it says so here.
            </p>
            <div className="work-empty-actions">
              <button type="button" className="btn primary" onClick={onAnalyze}>
                <Icon name="sparkles" size={14} />
                Analyze source
              </button>
            </div>
          </div>
        ) : clips.length === 0 ? (
          <div className="work-empty">
            <span className="work-empty-mark" aria-hidden="true">
              <Icon name="filter" size={22} />
            </span>
            <h2>{isFiltered ? 'No clips match this view.' : 'No clip passed the checks.'}</h2>
            <p>
              {isFiltered
                ? 'Clear the filter and search to see the full reel again.'
                : 'Every clip failed a check. Read the warnings above, then re-analyze with a stronger model.'}
            </p>
            <div className="work-empty-actions">
              {isFiltered ? (
                <button
                  type="button"
                  className="btn ghost"
                  onClick={() => {
                    onFilter('all')
                    onQuery('')
                  }}
                >
                  Clear filters
                </button>
              ) : (
                <button type="button" className="btn ghost" onClick={onAnalyze}>
                  <Icon name="refresh" size={14} />
                  Re-analyze
                </button>
              )}
            </div>
          </div>
        ) : (
          <>
            <div className="reel-list" data-view={view} role="list" aria-label="Ranked clips">
              {clips.map((clip) => (
                <ClipCard
                  key={clip.id}
                  clip={clip}
                  thumbSrc={
                    sourceId
                      ? api.thumbUrl(sourceId, clip.start + Math.min(2.5, (clip.end - clip.start) / 3))
                      : mediaSrc
                  }
                  fallbackSrc={mediaSrc}
                  selected={clip.id === selectedId}
                  verdict={verdicts[clip.id]}
                  view={view}
                  onSelect={onSelect}
                  onOpen={onOpen}
                  onVerdict={onVerdict}
                  onMenu={onMenu}
                />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
})
