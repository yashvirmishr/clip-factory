import { useState } from 'react'
import { formatBytes, formatTime } from '../api'
import type { LearnState, SourceRow } from '../types'
import { LearningPanel } from './bits'

interface Props {
  sources: SourceRow[]
  selectedId: string | null
  learn: LearnState | null
  busy: boolean
  onSelect: (id: string) => void
  onIngest: (path: string) => void
  onDemo: () => void
  onSetup: () => void
}

export function Sidebar({
  sources,
  selectedId,
  learn,
  busy,
  onSelect,
  onIngest,
  onDemo,
  onSetup,
}: Props) {
  const [path, setPath] = useState('')

  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark">
          <span />
        </span>
        <span className="brand-name">Clip Factory</span>
        <span className="brand-sub">v0.1</span>
      </div>

      <div className="sidebar-scroll">
        <div className="sidebar-section">
          <div className="label" style={{ marginBottom: 8 }}>
            Sources
          </div>
          {sources.length === 0 ? (
            <p className="panel-note" style={{ color: 'var(--ink-3)' }}>
              Nothing ingested yet.
            </p>
          ) : null}
        </div>

        {sources.map((source) => (
          <button
            type="button"
            className="source-row"
            key={source.id}
            data-active={source.id === selectedId}
            onClick={() => onSelect(source.id)}
          >
            <div className="source-row-main">
              <span className="source-row-name">{source.name}</span>
            </div>
            <div className="source-row-meta">
              <span>{formatTime(source.duration)}</span>
              <span>·</span>
              <span>{formatBytes(source.size_bytes)}</span>
              {source.analyzed ? (
                <>
                  <span>·</span>
                  <span style={{ color: 'var(--tungsten)' }}>{source.clip_count} clips</span>
                </>
              ) : (
                <>
                  <span>·</span>
                  <span>not analyzed</span>
                </>
              )}
            </div>
          </button>
        ))}

        <div className="sidebar-section" style={{ paddingTop: 18 }}>
          <div className="label" style={{ marginBottom: 8 }}>
            Add a source
          </div>
          <input
            className="input"
            placeholder="C:\path\to\stream.mp4"
            value={path}
            onChange={(event) => setPath(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && path.trim()) {
                onIngest(path.trim())
                setPath('')
              }
            }}
          />
          <div style={{ display: 'flex', gap: 6, marginTop: 7 }}>
            <button
              type="button"
              className="btn sm"
              disabled={!path.trim() || busy}
              onClick={() => {
                onIngest(path.trim())
                setPath('')
              }}
            >
              Ingest
            </button>
            <button type="button" className="btn sm ghost" disabled={busy} onClick={onDemo}>
              Demo clip
            </button>
          </div>
        </div>
      </div>

      <div className="sidebar-foot">
        <LearningPanel learn={learn} />
        <button
          type="button"
          className="btn sm ghost"
          style={{ width: '100%', marginTop: 10 }}
          onClick={onSetup}
        >
          Hardware &amp; models
        </button>
      </div>
    </aside>
  )
}
