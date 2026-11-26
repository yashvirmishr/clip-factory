import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { formatTime, formatTimecode } from '../api'
import type { Clip, Peaks, Verdict } from '../types'
import { mix, withAlpha } from '../theme/color'
import { Icon } from '../workspace/Icon'
import { usePlayhead } from '../workspace/playhead'
import { IconButton } from '../workspace/ui'

interface TimelineProps {
  clips: Clip[]
  selectedId: string | null
  peaks: Peaks | null
  duration: number
  fps: number
  verdicts: Record<string, Verdict>
  hasSource: boolean
  onSeek: (seconds: number) => void
  onSelect: (clipId: string) => void
  onOpenMonitor: () => void
  themeId: string
}

const PAD = 18
const RULER_H = 28
const WAVE_H = 76
const TRACK_H = 40
const TRACK_GAP = 6

const TICK_STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600]

export function Timeline({
  clips,
  selectedId,
  peaks,
  duration,
  fps,
  verdicts,
  hasSource,
  onSeek,
  onSelect,
  onOpenMonitor,
  themeId,
}: TimelineProps) {
  const playhead = usePlayhead()
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const contentRef = useRef<HTMLDivElement | null>(null)
  const scrubbing = useRef(false)
  // A drag emits pointer moves faster than the browser can paint; one seek per
  // animation frame is the most the <video> element can honour anyway.
  const pendingSeek = useRef<number | null>(null)
  const seekFrame = useRef<number | null>(null)
  const [viewWidth, setViewWidth] = useState(720)
  const [zoom, setZoom] = useState(1)

  useEffect(() => {
    const node = scrollRef.current
    if (!node) return
    const observer = new ResizeObserver((entries) => {
      const next = entries[0]?.contentRect.width ?? 0
      if (next > 0) setViewWidth(next)
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  const inner = Math.max(120, viewWidth - PAD * 2)
  const span = Math.max(1, duration)
  const pps = (inner / span) * zoom
  const contentWidth = inner * zoom + PAD * 2
  const xFor = useCallback(
    (seconds: number) => PAD + Math.max(0, Math.min(span, seconds)) * pps,
    [pps, span],
  )

  const tracks = useMemo(() => {
    const ends: number[] = []
    const placed = clips.map((clip) => {
      let track = ends.findIndex((end) => end <= clip.start + 0.05)
      if (track === -1) {
        track = ends.length
        ends.push(clip.end)
      } else {
        ends[track] = clip.end
      }
      return { clip, track: Math.min(track, 1) }
    })
    return placed
  }, [clips])

  const trackCount = Math.max(1, Math.min(2, ...tracks.map((item) => item.track + 1)))
  const laneHeight = trackCount * TRACK_H + (trackCount - 1) * TRACK_GAP
  const canvasHeight = RULER_H + WAVE_H

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    // A long source at 8x zoom asks for a canvas wider than the browser will
    // allocate; clamp the backing store and scale the drawing to match.
    const maxBacking = 8192
    canvas.width = Math.max(1, Math.min(maxBacking, Math.floor(contentWidth * dpr)))
    canvas.height = Math.max(1, Math.min(maxBacking, Math.floor(canvasHeight * dpr)))
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.setTransform(
      canvas.width / Math.max(1, contentWidth),
      0,
      0,
      canvas.height / Math.max(1, canvasHeight),
      0,
      0,
    )
    ctx.clearRect(0, 0, contentWidth, canvasHeight)

    const styles = getComputedStyle(canvas)
    const readVar = (name: string, fallback: string) => {
      const value = styles.getPropertyValue(name).trim()
      return value || fallback
    }
    const ink = readVar('--ink', '#1c231f')
    const inkSoft = mix(ink, readVar('--bg', '#e8e3d7'), 0.18)
    const accent = readVar('--accent', '#2846d6')
    const mono = readVar('--font-mono', '"DM Mono", ui-monospace, monospace')

    // ruler ticks
    const target = 96
    const step = TICK_STEPS.find((candidate) => candidate * pps >= target) ?? TICK_STEPS[TICK_STEPS.length - 1]
    const minor = step / 5
    ctx.font = `10px ${mono}`
    ctx.textBaseline = 'middle'
    ctx.strokeStyle = withAlpha(ink, 0.18)
    ctx.fillStyle = withAlpha(inkSoft, 0.95)
    ctx.lineWidth = 1
    for (let t = 0; t <= span + 0.001; t += minor) {
      const x = Math.round(xFor(t)) + 0.5
      const major = Math.abs(t / step - Math.round(t / step)) < 0.0001
      ctx.beginPath()
      ctx.moveTo(x, major ? 14 : 21)
      ctx.lineTo(x, RULER_H)
      ctx.stroke()
      if (major) {
        const label = formatTime(t)
        const labelX = Math.max(2, Math.min(x + 5, contentWidth - ctx.measureText(label).width - 4))
        ctx.fillText(label, labelX, 9)
      }
    }
    ctx.strokeStyle = withAlpha(ink, 0.14)
    ctx.beginPath()
    ctx.moveTo(0, RULER_H + 0.5)
    ctx.lineTo(contentWidth, RULER_H + 0.5)
    ctx.stroke()

    // candidate windows: a quiet ribbon behind the waveform
    ctx.fillStyle = withAlpha(accent, 0.07)
    for (const clip of clips) {
      if (!clip.rank) continue
      const x0 = xFor(clip.start)
      const x1 = xFor(clip.end)
      ctx.fillRect(x0, RULER_H, Math.max(1, x1 - x0), WAVE_H)
    }

    if (!peaks || !peaks.buckets) return
    const n = peaks.buckets
    let magnitude = 1e-6
    for (let i = 0; i < n; i += 1) {
      magnitude = Math.max(magnitude, Math.abs(peaks.high[i] ?? 0), Math.abs(peaks.low[i] ?? 0))
    }
    const gain = 1 / magnitude
    const mid = RULER_H + WAVE_H / 2
    const amp = (WAVE_H / 2) * 0.78

    ctx.beginPath()
    for (let i = 0; i < n; i += 1) {
      const x = PAD + (i / Math.max(1, n - 1)) * (contentWidth - PAD * 2)
      const y = mid - Math.abs(peaks.high[i] ?? 0) * gain * amp
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    for (let i = n - 1; i >= 0; i -= 1) {
      const x = PAD + (i / Math.max(1, n - 1)) * (contentWidth - PAD * 2)
      const y = mid - Math.abs(peaks.low[i] ?? 0) * gain * amp
      ctx.lineTo(x, y)
    }
    ctx.closePath()
    ctx.fillStyle = withAlpha(ink, 0.16)
    ctx.fill()
    ctx.strokeStyle = withAlpha(ink, 0.28)
    ctx.lineWidth = 0.6
    ctx.stroke()
  }, [peaks, clips, contentWidth, canvasHeight, pps, span, xFor, themeId])

  const scheduleSeek = useCallback(
    (seconds: number) => {
      pendingSeek.current = Math.max(0, Math.min(span, seconds))
      if (seekFrame.current !== null) return
      seekFrame.current = window.requestAnimationFrame(() => {
        seekFrame.current = null
        const next = pendingSeek.current
        pendingSeek.current = null
        if (next !== null) onSeek(next)
      })
    },
    [onSeek, span],
  )

  useEffect(
    () => () => {
      if (seekFrame.current !== null) window.cancelAnimationFrame(seekFrame.current)
    },
    [],
  )

  const seekFromPointer = (clientX: number) => {
    const node = contentRef.current
    if (!node) return
    const rect = node.getBoundingClientRect()
    const seconds = (clientX - rect.left - PAD) / pps
    scheduleSeek(seconds)
  }

  const selected = clips.find((clip) => clip.id === selectedId) ?? null

  return (
    <div className="timeline">
      <div className="tab-toolbar timeline-toolbar">
        <span className="timeline-title">
          <Icon name="timeline" size={14} />
          Timeline
        </span>
        <span className="toolbar-divider" aria-hidden="true" />
        <span className="toolbar-hint">
          {selected
            ? `CLIP ${String(selected.rank ?? '—').padStart(2, '0')} · ${formatTimecode(selected.start, fps)} → ${formatTimecode(selected.end, fps)}`
            : `${clips.length} candidates over ${formatTime(duration)}`}
        </span>
        <span className="toolbar-spacer" />
        <div className="zoom-controls" role="group" aria-label="Timeline zoom">
          <IconButton
            icon="zoom-out"
            size="sm"
            label="Zoom out"
            disabled={zoom <= 1}
            onClick={() => setZoom((value) => Math.max(1, Math.round((value - 0.5) * 2) / 2))}
          />
          <span className="zoom-value num">{Math.round(zoom * 100)}%</span>
          <IconButton
            icon="zoom-in"
            size="sm"
            label="Zoom in"
            disabled={zoom >= 8}
            onClick={() => setZoom((value) => Math.min(8, Math.round((value + 0.5) * 2) / 2))}
          />
          <IconButton
            icon="fit-width"
            size="sm"
            label="Fit timeline to window"
            onClick={() => {
              setZoom(1)
              if (scrollRef.current) scrollRef.current.scrollLeft = 0
            }}
          />
        </div>
        <span className="toolbar-divider" aria-hidden="true" />
        <span className="timeline-clock num">{formatTimecode(playhead, fps)}</span>
      </div>

      {!hasSource || clips.length === 0 ? (
        <div className="work-empty timeline-empty">
          <span className="work-empty-mark" aria-hidden="true">
            <Icon name="timeline" size={22} />
          </span>
          <h2>{hasSource ? 'No clips to lay out.' : 'No tape loaded.'}</h2>
          <p>
            {hasSource
              ? 'Analyze the source to place ranked clips and their waveform on the timeline.'
              : 'Import a recording in the project panel to build a timeline.'}
          </p>
        </div>
      ) : (
        <>
          <div className="timeline-scroll" ref={scrollRef}>
            <div
              className="timeline-content"
              ref={contentRef}
              style={{ width: contentWidth }}
              onPointerDown={(event) => {
                if (event.button !== 0) return
                if ((event.target as HTMLElement).closest('button.tblock')) return
                scrubbing.current = true
                event.currentTarget.setPointerCapture(event.pointerId)
                seekFromPointer(event.clientX)
              }}
              onPointerMove={(event) => {
                if (scrubbing.current) seekFromPointer(event.clientX)
              }}
              onPointerUp={(event) => {
                scrubbing.current = false
                if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                  event.currentTarget.releasePointerCapture(event.pointerId)
                }
              }}
              onPointerCancel={() => {
                scrubbing.current = false
              }}
            >
              <div
                className="timeline-ruler"
                role="slider"
                tabIndex={0}
                aria-label="Timeline position"
                aria-valuemin={0}
                aria-valuemax={Math.round(span)}
                aria-valuenow={Math.round(playhead)}
                aria-valuetext={formatTimecode(playhead, fps)}
                onKeyDown={(event) => {
                  if (event.key === 'ArrowLeft') {
                    event.preventDefault()
                    onSeek(Math.max(0, playhead - (event.shiftKey ? 5 : 1)))
                  } else if (event.key === 'ArrowRight') {
                    event.preventDefault()
                    onSeek(Math.min(span, playhead + (event.shiftKey ? 5 : 1)))
                  } else if (event.key === 'Home') {
                    event.preventDefault()
                    onSeek(0)
                  } else if (event.key === 'End') {
                    event.preventDefault()
                    onSeek(span)
                  }
                }}
              />
              <canvas
                ref={canvasRef}
                className="timeline-canvas"
                style={{ width: contentWidth, height: canvasHeight }}
                aria-hidden="true"
              />
              <div className="timeline-lanes" style={{ height: laneHeight }}>
                {tracks.map(({ clip, track }) => {
                  const verdict = verdicts[clip.id]
                  const left = xFor(clip.start)
                  const width = Math.max(12, xFor(clip.end) - left)
                  // At whole-source zoom a 16-second clip is a few pixels wide.
                  // Show only the coloured marker until there is room for words.
                  const tight = width < 58
                  const roomy = width >= 120
                  const hook = clip.llm?.hook || clip.text
                  return (
                    <button
                      type="button"
                      key={clip.id}
                      className="tblock"
                      style={{ left, width, top: track * (TRACK_H + TRACK_GAP) }}
                      data-tight={tight ? 'true' : undefined}
                      data-selected={clip.id === selectedId ? 'true' : undefined}
                      data-verdict={verdict}
                      aria-current={clip.id === selectedId ? 'true' : undefined}
                      aria-label={`Clip ${clip.rank ?? ''}: ${hook}. ${formatTime(clip.start)} to ${formatTime(clip.end)}`}
                      title={`${formatTime(clip.start)} → ${formatTime(clip.end)} · ${hook}`}
                      onClick={() => {
                        onSelect(clip.id)
                        onSeek(clip.start)
                      }}
                      onDoubleClick={onOpenMonitor}
                    >
                      {tight ? null : (
                        <span className="tblock-rank num">{clip.rank ? String(clip.rank).padStart(2, '0') : '—'}</span>
                      )}
                      {roomy ? <span className="tblock-copy">{hook}</span> : null}
                      {roomy ? <span className="tblock-duration num">{(clip.end - clip.start).toFixed(1)}s</span> : null}
                    </button>
                  )
                })}
              </div>
              <div
                className="timeline-playhead"
                style={{ transform: `translateX(${xFor(playhead)}px)` }}
                aria-hidden="true"
              >
                <span />
              </div>
            </div>
          </div>

          <div className="timeline-foot">
            <span className="legend"><i data-tone="pending" /> Unreviewed</span>
            <span className="legend"><i data-tone="approve" /> Approved</span>
            <span className="legend"><i data-tone="reject" /> Rejected</span>
            <span className="toolbar-spacer" />
            <span className="timeline-hint">
              drag to scrub · <kbd className="kbd">←</kbd><kbd className="kbd">→</kbd> nudge · double-click a block for the monitor
            </span>
          </div>
        </>
      )}
    </div>
  )
}
