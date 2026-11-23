import { useRef, useState } from 'react'
import { formatTime } from '../api'
import type { Clip, Verdict } from '../types'
import { ScoreBars } from './bits'

interface Props {
  clip: Clip
  mediaSrc: string
  selected: boolean
  verdict: Verdict | null
  onSelect: () => void
  onVerdict: (verdict: Verdict) => void
}

function ClipThumb({ src, seekTo, hook, rank }: { src: string; seekTo: number; hook: string; rank: number | null }) {
  const ref = useRef<HTMLVideoElement | null>(null)
  const [failed, setFailed] = useState(false)
  return (
    <div className="thumb">
      {!failed ? (
        <video
          ref={ref}
          src={`${src}#t=${seekTo.toFixed(2)}`}
          muted
          playsInline
          preload="metadata"
          onLoadedMetadata={() => {
            const node = ref.current
            if (node) node.currentTime = seekTo
          }}
          onError={() => setFailed(true)}
        />
      ) : null}
      <span className="thumb-rank">{rank ? String(rank).padStart(2, '0') : '--'}</span>
      {hook ? <span className="thumb-hook">{hook}</span> : null}
    </div>
  )
}

export function ClipCard({ clip, mediaSrc, selected, verdict, onSelect, onVerdict }: Props) {
  const hook = clip.llm?.hook ?? ''
  const score = Math.round((clip.final || 0) * 100)
  const words = clip.features?.word_count ?? clip.text.split(' ').length

  return (
    <div
      className="clip"
      data-selected={selected}
      data-verdict={verdict ?? undefined}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onSelect()
        }
      }}
    >
      <ClipThumb src={mediaSrc} seekTo={clip.start + 2} hook={hook} rank={clip.rank} />

      <div className="clip-body">
        <p className={`clip-hook${hook ? '' : ' placeholder'}`}>
          {hook || 'no hook generated'}
        </p>
        <div className="clip-meta">
          <span>{formatTime(clip.start)}</span>
          <span className="sep" />
          <span>{Math.round(clip.end - clip.start)}s</span>
          <span className="sep" />
          <span>{words} words</span>
          {clip.llm?.provider && clip.llm.provider !== 'llama-server' ? (
            <>
              <span className="sep" />
              <span style={{ color: 'var(--warn)' }}>{clip.llm.provider}</span>
            </>
          ) : null}
        </div>
        <div className="clip-why">{clip.llm?.reason || 'no scoring reason recorded'}</div>
      </div>

      <div className="clip-right">
        <div className="score-block">
          <div className="score-value">{String(score).padStart(3, '0')}</div>
          <div className="score-rule" style={{ width: `${Math.max(8, score)}%` }} />
          <ScoreBars signals={clip.signals} />
        </div>
        <div className="verdict-row">
          <button
            type="button"
            className="icon-btn"
            data-on={verdict === 'approve'}
            title="Approve (A)"
            onClick={(event) => {
              event.stopPropagation()
              onVerdict(verdict === 'approve' ? 'undo' : 'approve')
            }}
          >
            ✓
          </button>
          <button
            type="button"
            className="icon-btn reject"
            data-on={verdict === 'reject'}
            title="Reject (X)"
            onClick={(event) => {
              event.stopPropagation()
              onVerdict(verdict === 'reject' ? 'undo' : 'reject')
            }}
          >
            ✕
          </button>
        </div>
      </div>
    </div>
  )
}
