import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { formatTime, formatTimecode } from '../api'
import type { Captions, Clip, Verdict } from '../types'
import { Icon } from '../workspace/Icon'
import { IconButton } from '../workspace/ui'

export interface MonitorHandle {
  togglePlay: () => void
  play: () => void
  pause: () => void
  nudge: (seconds: number) => void
  step: (frames: number) => void
  seek: (seconds: number) => void
}

export type OverlayMode = 'hook' | 'captions' | 'off'

interface MonitorProps {
  clip: Clip | null
  mediaSrc: string | null
  sourceName: string
  sourceDuration: number
  fps: number
  captions: Captions | null
  captionsLoading: boolean
  seekRequest: { seconds: number; nonce: number } | null
  overlay: OverlayMode
  loop: boolean
  guides: boolean
  verdict: Verdict | undefined
  onOverlay: (mode: OverlayMode) => void
  onLoop: (loop: boolean) => void
  onGuides: (guides: boolean) => void
  onTime: (seconds: number) => void
  onVerdict: (verdict: Verdict) => void
  onOpenOutput: () => void
  onNotify: (kind: 'ok' | 'error' | 'info', message: string) => void
}

export const Monitor = forwardRef<MonitorHandle, MonitorProps>(function Monitor(
  {
    clip,
    mediaSrc,
    sourceName,
    sourceDuration,
    fps,
    captions,
    captionsLoading,
    seekRequest,
    overlay,
    loop,
    guides,
    verdict,
    onOverlay,
    onLoop,
    onGuides,
    onTime,
    onVerdict,
    onOpenOutput,
    onNotify,
  },
  ref,
) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const frameRef = useRef<HTMLDivElement | null>(null)
  const pendingSeek = useRef<number | null>(null)
  const rangeArmed = useRef(false)
  const scrubbing = useRef(false)
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [volume, setVolume] = useState(1)
  const [muted, setMuted] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [failed, setFailed] = useState(false)

  const duration = sourceDuration || videoRef.current?.duration || 0

  const applySeek = (seconds: number, report = true) => {
    const video = videoRef.current
    const target = Math.max(0, Math.min(duration || seconds, seconds))
    setTime(target)
    if (report) onTime(target)
    if (!video) return
    if (video.readyState >= 1) {
      video.currentTime = target
    } else {
      pendingSeek.current = target
    }
  }

  // A new clip always resets the monitor to its in point.
  useEffect(() => {
    if (!clip) {
      setTime(0)
      return
    }
    const video = videoRef.current
    setFailed(false)
    setTime(clip.start)
    if (video) {
      video.pause()
      if (video.readyState >= 1) video.currentTime = clip.start
      else pendingSeek.current = clip.start
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clip?.id])

  useEffect(() => {
    if (!seekRequest) return
    applySeek(seekRequest.seconds)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seekRequest?.nonce])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    video.volume = volume
    video.muted = muted
    video.playbackRate = speed
  }, [volume, muted, speed])

  useEffect(() => {
    return () => {
      videoRef.current?.pause()
    }
  }, [])

  const play = () => {
    const video = videoRef.current
    if (!video || !clip) return
    if (clip && time >= clip.end - 0.05) applySeek(clip.start)
    rangeArmed.current = true
    void video
      .play()
      .then(() => setPlaying(true))
      .catch(() => {
        setPlaying(false)
        onNotify('error', 'Playback was blocked by the browser. Press play once more.')
      })
  }

  const pause = () => {
    videoRef.current?.pause()
    setPlaying(false)
    rangeArmed.current = false
  }

  const togglePlay = () => {
    if (playing) pause()
    else play()
  }

  const nudge = (seconds: number) => {
    const video = videoRef.current
    if (!video) return
    const next = Math.max(0, Math.min(duration, video.currentTime + seconds))
    applySeek(next)
  }

  const step = (frames: number) => {
    pause()
    const video = videoRef.current
    if (!video) return
    applySeek(video.currentTime + frames / Math.max(1, fps))
  }

  useImperativeHandle(ref, () => ({
    togglePlay,
    play,
    pause,
    nudge,
    step,
    seek: (seconds: number) => applySeek(seconds),
  }))

  const onTimeUpdate = () => {
    const video = videoRef.current
    if (!video || !clip) return
    const next = video.currentTime
    setTime(next)
    onTime(next)
    if (rangeArmed.current && next >= clip.end - 0.02) {
      if (loop) {
        video.currentTime = clip.start
        setTime(clip.start)
        onTime(clip.start)
      } else {
        video.pause()
        video.currentTime = clip.end
        setTime(clip.end)
        onTime(clip.end)
        setPlaying(false)
        rangeArmed.current = false
      }
    }
  }

  const pointerSeek = (clientX: number, element: HTMLElement) => {
    const rect = element.getBoundingClientRect()
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
    applySeek(ratio * duration)
  }

  const activePage = captions?.pages.find((page) => time >= page.start && time < page.end) ?? null
  const hook = clip?.llm?.hook || clip?.text || ''

  if (!clip) {
    return (
      <div className="monitor">
        <div className="tab-toolbar monitor-toolbar">
          <span className="monitor-clip-label mono">MONITOR</span>
          <span className="toolbar-spacer" />
          <span className="toolbar-hint">No clip selected</span>
        </div>
        <div className="monitor-stage">
          <div className="work-empty monitor-empty">
            <span className="work-empty-mark" aria-hidden="true">
              <Icon name="monitor" size={22} />
            </span>
            <h2>No clip on the monitor.</h2>
            <p>Select a clip in the reel, or jump here from a timeline block to review the cut.</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="monitor">
      <div className="tab-toolbar monitor-toolbar">
        <span className="monitor-clip-label">
          <span className="mono">CLIP {clip.rank ? String(clip.rank).padStart(2, '0') : '—'}</span>
          <span className="num monitor-range">{formatTime(clip.start)} → {formatTime(clip.end)}</span>
        </span>

        <span className="toolbar-spacer" />

        <label className="select-wrap" title="Preview overlay">
          <Icon name={overlay === 'captions' ? 'captions' : overlay === 'hook' ? 'eye' : 'eye-off'} size={13} />
          <select
            value={overlay}
            onChange={(event) => onOverlay(event.target.value as OverlayMode)}
            aria-label="Preview overlay"
          >
            <option value="hook">Hook</option>
            <option value="captions">Captions</option>
            <option value="off">No overlay</option>
          </select>
          <Icon name="chevron-down" size={12} />
        </label>

        <IconButton
          icon="repeat"
          size="sm"
          label={loop ? 'Disable clip loop' : 'Loop selected clip'}
          active={loop}
          onClick={() => onLoop(!loop)}
        />
        <IconButton
          icon="crop"
          size="sm"
          label={guides ? 'Hide 9:16 guides' : 'Show 9:16 guides'}
          active={guides}
          onClick={() => onGuides(!guides)}
        />
        <button type="button" className="btn sm ghost" onClick={onOpenOutput}>
          <Icon name="arrow-up-right" size={13} />
          Output
        </button>
      </div>

      <div className="monitor-stage">
        <div className="monitor-frame" ref={frameRef}>
          <video
            ref={videoRef}
            src={mediaSrc ?? undefined}
            preload="metadata"
            playsInline
            onTimeUpdate={onTimeUpdate}
            onPlay={() => setPlaying(true)}
            onPause={() => {
              setPlaying(false)
              rangeArmed.current = false
            }}
            onSeeked={() => {
              const video = videoRef.current
              if (video) {
                setTime(video.currentTime)
                onTime(video.currentTime)
              }
            }}
            onLoadedMetadata={() => {
              const video = videoRef.current
              if (!video) return
              video.volume = volume
              video.muted = muted
              video.playbackRate = speed
              if (pendingSeek.current !== null) {
                video.currentTime = pendingSeek.current
                setTime(pendingSeek.current)
                onTime(pendingSeek.current)
                pendingSeek.current = null
              }
            }}
            onError={() => {
              setFailed(true)
              setPlaying(false)
            }}
            onClick={togglePlay}
            aria-label={`Source preview at ${formatTimecode(time, fps)}`}
          />

          <div className="monitor-badge">
            <span className="rec-dot" aria-hidden="true" />
            SOURCE PREVIEW
          </div>
          <div className="monitor-timecode num" aria-hidden="true">{formatTimecode(time, fps)}</div>

          {guides ? (
            <div className="monitor-guides" aria-hidden="true">
              <span className="guide-vertical">
                <i>9:16</i>
              </span>
            </div>
          ) : null}

          {overlay === 'hook' ? (
            <div className="overlay-hook" aria-hidden="true">
              <span className="overlay-kicker">Hook</span>
              <p>{hook}</p>
            </div>
          ) : null}

          {overlay === 'captions' ? (
            <div className="overlay-captions" aria-hidden="true">
              {captionsLoading ? (
                <span className="overlay-empty">Loading captions…</span>
              ) : activePage ? (
                <p>
                  {activePage.words.map((word, index) => (
                    <span key={`${index}-${word.start}`} data-active={time >= word.start && time < word.end ? 'true' : undefined}>
                      {word.text}{' '}
                    </span>
                  ))}
                </p>
              ) : (
                <span className="overlay-empty">No caption on screen</span>
              )}
            </div>
          ) : null}

          {!playing ? (
            <button type="button" className="monitor-play" onClick={togglePlay} aria-label="Play preview">
              <Icon name="play" size={22} />
            </button>
          ) : null}

          {failed ? (
            <div className="monitor-error" role="alert">
              <Icon name="alert" size={16} />
              <div>
                <b>Preview unavailable.</b>
                <span>The source file may have moved or the browser cannot decode it.</span>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      <div className="transport">
        <div
          className="scrubber"
          role="slider"
          tabIndex={0}
          aria-label="Preview position"
          aria-valuemin={0}
          aria-valuemax={Math.round(duration)}
          aria-valuenow={Math.round(time)}
          aria-valuetext={formatTimecode(time, fps)}
          onPointerDown={(event) => {
            if (event.button !== 0) return
            scrubbing.current = true
            event.currentTarget.setPointerCapture(event.pointerId)
            pointerSeek(event.clientX, event.currentTarget)
          }}
          onPointerMove={(event) => {
            if (scrubbing.current) pointerSeek(event.clientX, event.currentTarget)
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
          onKeyDown={(event) => {
            if (event.key === 'ArrowLeft') {
              event.preventDefault()
              nudge(-1)
            } else if (event.key === 'ArrowRight') {
              event.preventDefault()
              nudge(1)
            } else if (event.key === 'Home') {
              event.preventDefault()
              applySeek(0)
            } else if (event.key === 'End') {
              event.preventDefault()
              applySeek(duration)
            }
          }}
        >
          <span className="scrubber-clip" style={{ left: `${(clip.start / Math.max(1, duration)) * 100}%`, width: `${((clip.end - clip.start) / Math.max(1, duration)) * 100}%` }} />
          <span className="scrubber-track">
            <i style={{ width: `${(time / Math.max(1, duration)) * 100}%` }} />
          </span>
          <span className="scrubber-head" style={{ left: `${(time / Math.max(1, duration)) * 100}%` }} />
        </div>

        <div className="transport-row">
          <div className="transport-group">
            <IconButton icon="skip-back" label="Go to start" onClick={() => applySeek(clip.start)} />
            <IconButton icon="step-back" label="Step back one frame" onClick={() => step(-1)} />
            <button type="button" className="transport-play" onClick={togglePlay} aria-label={playing ? 'Pause' : 'Play'}>
              <Icon name={playing ? 'pause' : 'play'} size={17} />
            </button>
            <IconButton icon="step-forward" label="Step forward one frame" onClick={() => step(1)} />
            <IconButton icon="skip-forward" label="Go to clip out" onClick={() => applySeek(clip.end)} />
          </div>

          <div className="transport-clock">
            <span className="num">{formatTimecode(time, fps)}</span>
            <span className="transport-clock-total num">/ {formatTimecode(duration, fps)}</span>
          </div>

          <div className="transport-group transport-right">
            <IconButton
              icon={muted || volume === 0 ? 'volume-x' : 'volume'}
              label={muted ? 'Unmute preview' : 'Mute preview'}
              onClick={() => setMuted((current) => !current)}
            />
            <input
              type="range"
              className="volume-slider"
              min={0}
              max={1}
              step={0.01}
              value={muted ? 0 : volume}
              aria-label="Preview volume"
              onChange={(event) => {
                const next = Number(event.target.value)
                setVolume(next)
                setMuted(next === 0)
              }}
            />
            <label className="select-wrap speed-select" title="Playback speed">
              <select value={speed} onChange={(event) => setSpeed(Number(event.target.value))} aria-label="Playback speed">
                <option value={0.5}>0.5×</option>
                <option value={0.75}>0.75×</option>
                <option value={1}>1×</option>
                <option value={1.25}>1.25×</option>
                <option value={1.5}>1.5×</option>
                <option value={2}>2×</option>
              </select>
              <Icon name="chevron-down" size={11} />
            </label>
            <IconButton
              icon="maximize"
              label="Fullscreen preview"
              onClick={() => {
                if (document.fullscreenElement) {
                  void document.exitFullscreen()
                } else {
                  frameRef.current?.requestFullscreen().catch(() => {
                    onNotify('error', 'Fullscreen was blocked by the browser.')
                  })
                }
              }}
            />
          </div>
        </div>

        <div className="transport-meta">
          <span className="monitor-source-name" title={sourceName}>
            <Icon name="film" size={12} />
            {sourceName}
          </span>
          <span aria-hidden="true">·</span>
          <span className="num">{Math.round(clip.end - clip.start)}s clip</span>
          {verdict ? (
            <>
              <span aria-hidden="true">·</span>
              <span className="verdict-text" data-verdict={verdict}>
                {verdict === 'approve' ? 'Approved' : 'Rejected'}
              </span>
            </>
          ) : (
            <>
              <span aria-hidden="true">·</span>
              <button type="button" className="text-action" onClick={() => onVerdict('approve')}>Approve</button>
              <button type="button" className="text-action" onClick={() => onVerdict('reject')}>Reject</button>
            </>
          )}
          <span className="toolbar-spacer" />
          {captions ? (
            <span className="num">{captions.stats.pages} caption pages</span>
          ) : captionsLoading ? (
            <span>Loading captions…</span>
          ) : null}
        </div>
      </div>
    </div>
  )
})
