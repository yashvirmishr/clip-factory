import { lazy, memo, Suspense, useEffect, useRef, useState } from 'react'
import { api, formatTimecode } from '../api'
import type { Captions, Clip, Verdict } from '../types'
import { Icon } from '../workspace/Icon'
import { Tabs } from '../workspace/Tabs'
import { usePlayhead } from '../workspace/playhead'
import { Spinner } from '../workspace/ui'
import { GateWarnings, ScoreBars, TruthList } from './bits'
import type { RenderedClip } from './PublishPanel'
import { RenderPanel, type RenderRequest } from './RenderPanel'
import { TrimPanel } from './TrimPanel'

// The four tab panels are the bulk of the inspector's code and none of them is
// needed to paint the shell. Loading them on the first tab visit keeps the
// initial bundle smaller without changing what a tab does once opened.
const CoachPanel = lazy(() => import('./CoachPanel').then((m) => ({ default: m.CoachPanel })))
const ExportPanel = lazy(() => import('./ExportPanel').then((m) => ({ default: m.ExportPanel })))
const PublishPanel = lazy(() => import('./PublishPanel').then((m) => ({ default: m.PublishPanel })))
const SubtitleStudio = lazy(() =>
  import('./SubtitleStudio').then((m) => ({ default: m.SubtitleStudio })),
)

function PanelFallback({ label }: { label: string }) {
  return (
    <div className="panel-loading">
      <Spinner label={label} />
    </div>
  )
}

export type InspectorTab = 'properties' | 'captions' | 'coach' | 'output'

interface InspectorProps {
  sourceId: string
  clip: Clip | null
  captions: Captions | null
  captionsLoading: boolean
  verdict: Verdict | undefined
  fps: number
  tab: InspectorTab
  clipCount: number
  hasSource: boolean
  renderRequest: RenderRequest | null
  onTab: (tab: InspectorTab) => void
  onVerdict: (verdict: Verdict) => void
  onSeek: (seconds: number) => void
  onHookSaved: (clipId: string, hook: string) => void
  onClipUpdated: (clip: Clip) => void
  onNotify: (kind: 'ok' | 'error' | 'info', message: string) => void
  onFloat?: () => void
}

export const Inspector = memo(function Inspector({
  sourceId,
  clip,
  captions,
  captionsLoading,
  verdict,
  fps,
  tab,
  clipCount,
  hasSource,
  renderRequest,
  onTab,
  onVerdict,
  onSeek,
  onHookSaved,
  onClipUpdated,
  onNotify,
  onFloat,
}: InspectorProps) {
  const playhead = usePlayhead()
  const [hook, setHook] = useState('')
  const [rendered, setRendered] = useState<RenderedClip | null>(null)
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const saveRef = useRef<() => Promise<void>>(async () => {})

  useEffect(() => {
    setHook(clip?.llm?.hook ?? '')
    setSaveState('idle')
  }, [clip?.id, clip?.llm?.hook])

  if (!clip) {
    return (
      <aside className="inspector" aria-label="Clip inspector" data-tour="verdict">
        <header className="panel-chrome">
          <span className="panel-eyebrow">Inspector</span>
          <span className="panel-count">No selection</span>
        </header>
        <div className="work-empty inspector-empty">
          <span className="work-empty-mark" aria-hidden="true">
            <Icon name="sliders" size={22} />
          </span>
          <h2>{hasSource ? 'No clip selected.' : 'Nothing to inspect.'}</h2>
          <p>
            {hasSource
              ? 'Pick a clip in the list or a block on the timeline. Its scorecard, hook, captions and output settings live here.'
              : 'Import a source, run the analysis, then select a clip to open its properties.'}
          </p>
        </div>
      </aside>
    )
  }

  const provider = clip.llm?.provider ?? 'none'
  const score = Math.round((clip.final || 0) * 100)
  const words = clip.features?.word_count ?? clip.text.split(/\s+/).filter(Boolean).length
  const dirty = hook.trim() !== (clip.llm?.hook ?? '')
  const canEditHook = Boolean(clip.llm)

  const saveHook = async () => {
    if (!clip.llm) return
    const trimmed = hook.trim()
    if (!trimmed || trimmed === clip.llm.hook) return
    setSaveState('saving')
    try {
      await api.setHook(sourceId, clip.id, trimmed)
      onHookSaved(clip.id, trimmed)
      setSaveState('saved')
    } catch (failure) {
      setSaveState('error')
      onNotify('error', (failure as Error).message)
    }
  }
  saveRef.current = saveHook

  return (
    <aside className="inspector" aria-label="Clip inspector" data-tour="verdict">
      <header className="inspector-head">
        <div className="inspector-id">
          <span className="clip-badge">CLIP {clip.rank ? String(clip.rank).padStart(2, '0') : '—'}</span>
          <span className="num inspector-time">
            {formatTimecode(clip.start, fps)} → {formatTimecode(clip.end, fps)}
          </span>
        </div>
        <div className="inspector-actions">
          {onFloat ? (
            <button
              type="button"
              className="icon-btn icon-btn-sm inspector-float"
              aria-label="Float inspector"
              title="Float inspector"
              onClick={onFloat}
            >
              <Icon name="external" size={14} />
            </button>
          ) : null}
          <button
            type="button"
            className="btn sm verdict-approve"
            data-on={verdict === 'approve' ? 'true' : undefined}
            onClick={() => onVerdict(verdict === 'approve' ? 'undo' : 'approve')}
            title="Approve clip (A)"
          >
            <Icon name="check" size={13} />
            {verdict === 'approve' ? 'Approved' : 'Approve'}
          </button>
          <button
            type="button"
            className="btn sm verdict-reject"
            data-on={verdict === 'reject' ? 'true' : undefined}
            onClick={() => onVerdict(verdict === 'reject' ? 'undo' : 'reject')}
            title="Reject clip (X)"
          >
            <Icon name="x" size={13} />
            {verdict === 'reject' ? 'Rejected' : 'Reject'}
          </button>
        </div>
      </header>

      <Tabs
        idPrefix="inspector"
        variant="panel"
        ariaLabel="Inspector sections"
        value={tab}
        onChange={(id) => onTab(id as InspectorTab)}
        items={[
          { id: 'properties', label: 'Properties', icon: 'sliders' },
          { id: 'captions', label: 'Captions', icon: 'captions', badge: captions?.stats.pages },
          { id: 'coach', label: 'Coach', icon: 'sparkles' },
          { id: 'output', label: 'Output', icon: 'download' },
        ]}
      />

      <div
        className="inspector-body"
        role="tabpanel"
        id={`inspector-panel-${tab}`}
        aria-labelledby={`inspector-tab-${tab}`}
      >
        {tab === 'properties' ? (
          <div className="inspector-scroll stack-14">
            <section className="score-hero">
              <div
                className="score-ring"
                style={{ background: `conic-gradient(var(--accent) ${Math.max(0, Math.min(100, score))}%, var(--line-strong) 0)` }}
                role="img"
                aria-label={`Final score ${score} out of 100`}
              >
                <span className="num">{score}</span>
              </div>
              <div className="score-hero-copy">
                <span className="label">Final score</span>
                <p>{clip.llm?.reason || 'No scoring reason recorded for this clip.'}</p>
                <div className="chip-row">
                  <span className="pill" title="Score from the found moments">
                    fused <span className="num">{(clip.fused * 100).toFixed(0)}</span>
                  </span>
                  <span className="pill" title="Model score">
                    model <span className="num">{clip.llm?.score ?? '—'}</span>
                  </span>
                  <span className="pill" data-tone={provider === 'llama-server' ? 'ok' : 'warn'}>
                    {provider}
                  </span>
                </div>
              </div>
            </section>

            <section className="inspector-section">
              <header className="section-head">
                <div>
                  <span className="label">Hook</span>
                  <h3>The first three seconds</h3>
                </div>
                <span className="field-hint">
                  {saveState === 'saving'
                    ? 'Saving…'
                    : saveState === 'saved'
                      ? 'Saved'
                      : saveState === 'error'
                        ? 'Save failed'
                        : `${hook.trim().split(/\s+/).filter(Boolean).length} words`}
                </span>
              </header>
              <div className="section-body">
                <textarea
                  className="hook-input"
                  rows={3}
                  value={hook}
                  disabled={!canEditHook}
                  onChange={(event) => {
                    setHook(event.target.value)
                    setSaveState('idle')
                  }}
                  onBlur={() => void saveRef.current()}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault()
                      event.currentTarget.blur()
                    }
                    if (event.key === 'Escape') {
                      event.preventDefault()
                      setHook(clip.llm?.hook ?? '')
                      setSaveState('idle')
                      event.currentTarget.blur()
                    }
                  }}
                  placeholder="The on-screen text for the first three seconds"
                />
                <div className="hook-actions">
                  <span className="field-hint">
                    {canEditHook ? 'Enter saves · Shift+Enter adds a line' : 'Hook editing needs a scored clip.'}
                  </span>
                  <button
                    type="button"
                    className="btn sm ghost"
                    disabled={!dirty || saveState === 'saving' || !canEditHook}
                    onClick={() => void saveHook()}
                  >
                    <Icon name="save" size={13} />
                    Save hook
                  </button>
                </div>
              </div>
            </section>

            <section className="inspector-section">
              <header className="section-head">
                <div>
                  <span className="label">What it noticed</span>
                  <h3>Why the score moved</h3>
                </div>
              </header>
              <div className="section-body stack-10">
                <ScoreBars signals={clip.signals} />
                <dl className="fact-grid">
                  <div>
                    <dt>Duration</dt>
                    <dd className="num">{(clip.end - clip.start).toFixed(1)}s</dd>
                  </div>
                  <div>
                    <dt>Words</dt>
                    <dd className="num">{words}</dd>
                  </div>
                  <div>
                    <dt>Words / sec</dt>
                    <dd className="num">{(clip.features?.words_per_sec ?? 0).toFixed(2)}</dd>
                  </div>
                  <div>
                    <dt>Speech</dt>
                    <dd className="num">{Math.round((clip.features?.speech_coverage ?? 0) * 100)}%</dd>
                  </div>
                </dl>
              </div>
            </section>

            <details className="inspector-section inspector-fold">
              <summary className="section-head">
                <div>
                  <span className="label">Quality scorecard</span>
                  <h3>What the judge looked for</h3>
                </div>
                <span className="fold-tail">
                  <span className="pill numeric">
                    {clip.scorecard.filter((item) => item.passed).length}/{clip.scorecard.length}
                  </span>
                  <Icon name="chevron-down" size={13} />
                </span>
              </summary>
              <div className="section-body">
                {clip.scorecard.length ? (
                  <TruthList items={clip.scorecard} />
                ) : (
                  <p className="panel-note">No scorecard items were recorded.</p>
                )}
              </div>
            </details>

            <details className="inspector-section inspector-fold" open={clip.blocked}>
              <summary className="section-head">
                <div>
                  <span className="label">Checks</span>
                  <h3>Blocking rules</h3>
                </div>
                <span className="fold-tail">
                  {clip.blocked ? <span className="pill danger">blocked</span> : <span className="pill ok">clear</span>}
                  <Icon name="chevron-down" size={13} />
                </span>
              </summary>
              <div className="section-body">
                <GateWarnings gates={clip.gates} />
              </div>
            </details>

            <TrimPanel
              sourceId={sourceId}
              clip={clip}
              fps={fps}
              onTrimmed={onClipUpdated}
              onSeek={onSeek}
            />

            <details className="transcript-details">
              <summary>
                <span className="label">Transcript window</span>
                <Icon name="chevron-down" size={13} />
              </summary>
              <p>{clip.text || 'No transcript words were retained for this window.'}</p>
            </details>
          </div>
        ) : tab === 'captions' ? (
          <div className="inspector-scroll stack-14">
            <Suspense fallback={<PanelFallback label="Opening the caption studio" />}>
              <SubtitleStudio
                sourceId={sourceId}
                clipId={clip.id}
                pages={captions?.pages ?? []}
                captionsFont={captions?.font}
                onNotify={onNotify}
              />
            </Suspense>
            <div className="caption-stats">
              <div>
                <span className="label">Pages</span>
                <b className="num">{captions?.stats.pages ?? '—'}</b>
              </div>
              <div>
                <span className="label">Mean CPS</span>
                <b className="num">{captions?.stats.mean_cps ?? '—'}</b>
              </div>
              <div>
                <span className="label">Warnings</span>
                <b className="num">{captions?.stats.warnings ?? '—'}</b>
              </div>
            </div>

            {captionsLoading ? (
              <div className="panel-loading">
                <Spinner label="Loading caption pages" />
              </div>
            ) : captions ? (
              <div className="caption-pages">
                {captions.pages.map((page) => {
                  const active = playhead >= page.start && playhead < page.end
                  return (
                    <article className="caption-page" key={page.index} data-active={active ? 'true' : undefined}>
                      <header>
                        <span className="num caption-page-time">
                          {formatTimecode(page.start, fps)}
                        </span>
                        <span className="caption-page-meta num">{page.cps} cps</span>
                        <span className="toolbar-spacer" />
                        <Icon name="captions" size={12} />
                      </header>
                      <p className="caption-words">
                        {page.words.map((word, index) => (
                          <button
                            type="button"
                            key={`${page.index}-${index}`}
                            className="caption-word"
                            data-speaking={playhead >= word.start && playhead < word.end ? 'true' : undefined}
                            onClick={() => onSeek(word.start)}
                            title={`${formatTimecode(word.start, fps)} → ${formatTimecode(word.end, fps)}`}
                          >
                            {word.text}
                          </button>
                        ))}
                      </p>
                      <footer>
                        <span className="num">{(page.end - page.start).toFixed(2)}s</span>
                        <span className="caption-lines">{page.lines.join(' / ')}</span>
                        {page.warnings.map((warning) => (
                          <span className="warn" key={warning}>{warning}</span>
                        ))}
                      </footer>
                    </article>
                  )
                })}
              </div>
            ) : (
              <div className="panel-note">No caption pages were generated for this clip.</div>
            )}
          </div>
        ) : tab === 'coach' ? (
          <Suspense fallback={<PanelFallback label="Opening the coach" />}>
            <CoachPanel
              sourceId={sourceId}
              clip={clip}
              onClipUpdated={onClipUpdated}
              onSeek={onSeek}
              onNotify={onNotify}
            />
          </Suspense>
        ) : (
          <div className="inspector-scroll stack-14" data-tour="render">
            <RenderPanel
              sourceId={sourceId}
              clipId={clip.id}
              rank={clip.rank}
              request={renderRequest}
              onNotify={onNotify}
              onRendered={setRendered}
            />
            <Suspense fallback={<PanelFallback label="Opening export and publishing" />}>
              <ExportPanel
                sourceId={sourceId}
                clipId={clip?.id ?? null}
                clipCount={clipCount}
                onNotify={onNotify}
              />
              <PublishPanel sourceId={sourceId} clip={clip} rendered={rendered} onNotify={onNotify} />
            </Suspense>
            <p className="panel-note">
              Rendered masters are cached locally. Handoff timelines reference the original source;
              move the source and the NLE will ask to relink.
            </p>
          </div>
        )}
      </div>
    </aside>
  )
})
