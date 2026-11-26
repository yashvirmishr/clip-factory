import { memo } from 'react'
import { formatTime } from '../api'
import { Icon } from './Icon'
import { usePlayhead } from './playhead'
import { IconButton } from './ui'

interface StatusBarProps {
  busy: boolean
  statusLabel: string
  statusDetail?: string
  progress: number | null
  sourceName: string | null
  duration: number
  clipLabel: string | null
  asrBackend: string | null
  llmBackend: string | null
  chatMessages: number | null
  compact: boolean
  rightOpen: boolean
  onToggleRight: () => void
  onOpenShortcuts: () => void
  themeName: string
  themeSwatch: string
  onOpenThemes: () => void
}

export const StatusBar = memo(function StatusBar({
  busy,
  statusLabel,
  statusDetail,
  progress,
  sourceName,
  duration,
  clipLabel,
  asrBackend,
  llmBackend,
  chatMessages,
  compact,
  rightOpen,
  onToggleRight,
  onOpenShortcuts,
  themeName,
  themeSwatch,
  onOpenThemes,
}: StatusBarProps) {
  const playhead = usePlayhead()
  return (
    <footer className="statusbar">
      <div className="status-left">
        <span className="status-dot" data-busy={busy ? 'true' : undefined} aria-hidden="true" />
        <span className="status-label" role="status" aria-live="polite">
          {statusLabel}
        </span>
        {statusDetail ? <span className="status-detail">{statusDetail}</span> : null}
        {progress !== null && busy ? (
          <span className="status-track" aria-hidden="true">
            <i style={{ width: `${Math.max(0, Math.min(100, progress))}%` }} />
          </span>
        ) : null}
      </div>

      <div className="status-center">
        {sourceName ? (
          <>
            <Icon name="film" size={12} />
            <span className="status-source">{sourceName}</span>
            <span className="status-divider" aria-hidden="true" />
            <span className="num status-time">{formatTime(playhead)}</span>
            <span className="status-muted">/</span>
            <span className="num status-time status-muted">{formatTime(duration)}</span>
            {clipLabel ? (
              <>
                <span className="status-divider" aria-hidden="true" />
                <span className="status-clip">{clipLabel}</span>
              </>
            ) : null}
          </>
        ) : (
          <span className="status-muted">No source loaded</span>
        )}
      </div>

      <div className="status-right">
        <span className="status-engine" data-off={!asrBackend ? 'true' : undefined} title="Speech model">
          <i aria-hidden="true" />
          <b>{asrBackend || 'speech off'}</b>
        </span>
        <span className="status-engine" data-off={!llmBackend ? 'true' : undefined} title="Ranking model">
          <i aria-hidden="true" />
          <b>{llmBackend || 'ranking off'}</b>
        </span>
        {chatMessages ? (
          <span className="status-engine" title={`${chatMessages.toLocaleString()} chat messages`}>
            <i aria-hidden="true" />
            <b>{chatMessages.toLocaleString()} chat</b>
          </span>
        ) : null}
        <span className="status-divider" aria-hidden="true" />
        <button
          type="button"
          className="status-theme"
          onClick={onOpenThemes}
          title={`Theme: ${themeName}. Open the theme atelier.`}
          aria-label={`Theme: ${themeName}. Open the theme atelier.`}
        >
          <span className="status-theme-dot" style={{ background: themeSwatch }} aria-hidden="true" />
          <span className="status-theme-name">{themeName}</span>
        </button>
        <span className="status-divider" aria-hidden="true" />
        {compact ? (
          <IconButton
            icon="panel-right"
            size="sm"
            label={rightOpen ? 'Hide inspector' : 'Show inspector'}
            active={rightOpen}
            onClick={onToggleRight}
          />
        ) : null}
        <IconButton icon="keyboard" size="sm" label="Keyboard shortcuts" onClick={onOpenShortcuts} />
      </div>
    </footer>
  )
})
