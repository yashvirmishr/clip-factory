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
  leftOpen: boolean
  rightOpen: boolean
  onToggleLeft: () => void
  onToggleRight: () => void
  onOpenShortcuts: () => void
  workspaceLabel: string
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
  leftOpen,
  rightOpen,
  onToggleLeft,
  onToggleRight,
  onOpenShortcuts,
  workspaceLabel,
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
        <span className="status-workspace" title="Active workspace">
          <Icon name="layers" size={12} />
          {workspaceLabel}
        </span>
        <span className="status-divider" aria-hidden="true" />
        <IconButton
          icon="panel-left"
          size="sm"
          className="status-panel-toggle"
          label={leftOpen ? 'Hide project panel' : 'Show project panel'}
          active={leftOpen}
          onClick={onToggleLeft}
        />
        <IconButton
          icon="panel-right"
          size="sm"
          className="status-panel-toggle"
          label={rightOpen ? 'Hide inspector' : 'Show inspector'}
          active={rightOpen}
          onClick={onToggleRight}
        />
        <IconButton icon="keyboard" size="sm" label="Keyboard shortcuts" onClick={onOpenShortcuts} />
      </div>
    </footer>
  )
})
