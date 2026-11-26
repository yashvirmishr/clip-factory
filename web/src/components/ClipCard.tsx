import { memo, useRef, useState } from 'react'
import { formatTime } from '../api'
import type { Clip, Verdict } from '../types'
import { Icon } from '../workspace/Icon'
import { IconButton } from '../workspace/ui'

interface ClipCardProps {
  clip: Clip
  thumbSrc: string
  fallbackSrc: string
  selected: boolean
  verdict: Verdict | undefined
  view: 'list' | 'grid'
  onSelect: (clipId: string) => void
  onOpen: (clip: Clip) => void
  onVerdict: (clipId: string, verdict: Verdict) => void
  onMenu: (clip: Clip, position: { x: number; y: number }) => void
}

function ClipThumb({
  src,
  fallbackSrc,
  seekTo,
  rank,
  duration,
  verdict,
}: {
  src: string
  fallbackSrc: string
  seekTo: number
  rank: number | null
  duration: number
  verdict: Verdict | undefined
}) {
  const ref = useRef<HTMLVideoElement | null>(null)
  // A still image for the common case; if ffmpeg could not build one the card
  // keeps the old <video> preview rather than showing a blank frame.
  const [mode, setMode] = useState<'image' | 'video' | 'none'>('image')

  return (
    <span className="clip-thumb" aria-hidden="true">
      {mode === 'image' ? (
        <img
          src={src}
          alt=""
          loading="lazy"
          decoding="async"
          tabIndex={-1}
          onError={() => setMode(fallbackSrc ? 'video' : 'none')}
        />
      ) : mode === 'video' ? (
        <video
          ref={ref}
          src={`${fallbackSrc}#t=${seekTo.toFixed(2)}`}
          muted
          playsInline
          preload="metadata"
          tabIndex={-1}
          onLoadedMetadata={() => {
            const node = ref.current
            if (node) node.currentTime = seekTo
          }}
          onError={() => setMode('none')}
        />
      ) : (
        <span className="clip-thumb-fallback">
          <Icon name="film" size={18} />
        </span>
      )}
      <span className="clip-rank num">{rank ? String(rank).padStart(2, '0') : '--'}</span>
      <span className="clip-duration num">{formatTime(duration)}</span>
      {verdict ? (
        <span className="clip-verdict" data-verdict={verdict}>
          <Icon name={verdict === 'approve' ? 'check' : 'x'} size={11} />
          {verdict === 'approve' ? 'Approved' : 'Rejected'}
        </span>
      ) : null}
    </span>
  )
}

export const ClipCard = memo(function ClipCard({
  clip,
  thumbSrc,
  fallbackSrc,
  selected,
  verdict,
  view,
  onSelect,
  onOpen,
  onVerdict,
  onMenu,
}: ClipCardProps) {
  const hook = clip.llm?.hook ?? ''
  const score = Math.round((clip.final || 0) * 100)
  const duration = Math.max(0, clip.end - clip.start)

  return (
    <article
      className="clip-card"
      data-selected={selected ? 'true' : undefined}
      data-verdict={verdict}
      data-view={view}
      role="listitem"
      onContextMenu={(event) => {
        event.preventDefault()
        onMenu(clip, { x: event.clientX, y: event.clientY })
      }}
    >
      <button
        type="button"
        className="clip-hit"
        onClick={() => onSelect(clip.id)}
        onDoubleClick={() => onOpen(clip)}
        aria-current={selected ? 'true' : undefined}
        title="Select clip · double-click to open in the monitor"
      >
        <ClipThumb
          src={thumbSrc}
          fallbackSrc={fallbackSrc}
          seekTo={clip.start + Math.min(2.5, duration / 3)}
          rank={clip.rank}
          duration={duration}
          verdict={verdict}
        />

        <span className="clip-main">
          <span className="clip-heading">
            <span className="clip-badge mono">
              CLIP {clip.rank ? String(clip.rank).padStart(2, '0') : '—'}
            </span>
            <span className="clip-timecode num">
              {formatTime(clip.start)} → {formatTime(clip.end)}
            </span>
            {clip.blocked ? <span className="clip-blocked">blocked</span> : null}
          </span>

          <span className={`clip-hook ${hook ? '' : 'is-placeholder'}`}>
            {hook || clip.text}
          </span>
        </span>

        <span className="clip-figure" aria-label={`Score ${score} out of 100`}>
          <span className="clip-score num">{score}</span>
          <span className="clip-score-label">score</span>
        </span>
      </button>

      <div className="clip-actions">
        <IconButton
          icon="check"
          size="sm"
          label={verdict === 'approve' ? 'Undo approval' : 'Approve clip'}
          active={verdict === 'approve'}
          onClick={() => onVerdict(clip.id, verdict === 'approve' ? 'undo' : 'approve')}
        />
        <IconButton
          icon="x"
          size="sm"
          label={verdict === 'reject' ? 'Undo rejection' : 'Reject clip'}
          active={verdict === 'reject'}
          onClick={() => onVerdict(clip.id, verdict === 'reject' ? 'undo' : 'reject')}
        />
        <IconButton
          icon="more"
          size="sm"
          label="Clip actions"
          onClick={(event) => {
            const rect = event.currentTarget.getBoundingClientRect()
            onMenu(clip, { x: rect.right - 2, y: rect.bottom + 2 })
          }}
        />
      </div>
    </article>
  )
})
