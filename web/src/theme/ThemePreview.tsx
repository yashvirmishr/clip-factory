import type { CSSProperties } from 'react'
import { themeStyle } from './compile'
import type { ThemeDefinition } from './types'

interface ThemePreviewProps {
  theme: ThemeDefinition
  size?: 'card' | 'large'
}

/**
 * A scale model of the workspace, not a screenshot. Every surface and mark is
 * painted from the selected theme's compiled variables so the marketplace can
 * show a truthful preview before a theme is applied.
 */
export function ThemePreview({ theme, size = 'card' }: ThemePreviewProps) {
  return (
    <div
      className={`theme-preview theme-preview--${size}`}
      style={themeStyle(theme) as CSSProperties}
      aria-hidden="true"
    >
      <div className="tp-menubar">
        <span className="tp-mark">
          <i />
          <i />
          <i />
        </span>
        <span className="tp-brand">Clip Factory</span>
        <span className="tp-menus">
          <i />
          <i />
          <i />
        </span>
        <span className="tp-command">
          <i />
        </span>
      </div>

      <div className="tp-toolbar">
        <span className="tp-workspace tp-workspace--active">
          <i />
        </span>
        <span className="tp-workspace">
          <i />
        </span>
        <span className="tp-workspace">
          <i />
        </span>
        <span className="tp-toolbar-gap" />
        <span className="tp-pill" />
        <span className="tp-pill tp-pill--short" />
      </div>

      <div className="tp-work">
        <div className="tp-rail">
          <span className="tp-eyebrow" />
          <span className="tp-line tp-line--wide" />
          <span className="tp-line" />
          <span className="tp-line tp-line--short" />
          <span className="tp-thumb tp-thumb--active" />
          <span className="tp-thumb" />
          <span className="tp-thumb tp-thumb--short" />
          <span className="tp-rail-foot" />
        </div>

        <div className="tp-centre">
          <div className="tp-stage">
            <div className="tp-screen">
              <span className="tp-hook">“You will not believe what happened next.”</span>
              <span className="tp-screen-meta">01 / 06</span>
              <span className="tp-play" />
            </div>
            <div className="tp-transport">
              <span className="tp-transport-time">00:18</span>
              <span className="tp-transport-line">
                <i />
              </span>
              <span className="tp-transport-time">00:18</span>
            </div>
          </div>

          <div className="tp-reel">
            <span className="tp-reel-card tp-reel-card--active" />
            <span className="tp-reel-card" />
            <span className="tp-reel-card" />
            <span className="tp-reel-card" />
          </div>
        </div>

        <div className="tp-inspector">
          <span className="tp-eyebrow" />
          <span className="tp-score">82</span>
          <span className="tp-line tp-line--wide" />
          <span className="tp-line" />
          <span className="tp-line tp-line--short" />
          <span className="tp-divider" />
          <span className="tp-field" />
          <span className="tp-field tp-field--short" />
          <span className="tp-primary" />
        </div>
      </div>

      <div className="tp-status">
        <span className="tp-status-dot" />
        <span className="tp-status-text tp-status-text--strong" />
        <span className="tp-status-gap" />
        <span className="tp-status-text" />
        <span className="tp-status-text tp-status-text--short" />
      </div>
    </div>
  )
}
