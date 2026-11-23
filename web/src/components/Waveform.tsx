import { useEffect, useRef } from 'react'
import type { Clip, Peaks } from '../types'

interface Props {
  peaks: Peaks | null
  duration: number
  clips: Clip[]
  playhead: number
  onSeek: (seconds: number) => void
}

/**
 * Pre-rendered peak data drawn to a canvas. Never decodes audio in the
 * renderer - a full-length AudioBuffer is ~1 GB on a long VOD.
 */
export function Waveform({ peaks, duration, clips, playhead, onSeek }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !peaks || !peaks.buckets) return
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const width = canvas.clientWidth
    const height = canvas.clientHeight
    canvas.width = Math.floor(width * dpr)
    canvas.height = Math.floor(height * dpr)
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, width, height)

    const mid = height / 2
    const amp = mid * 0.88

    // candidate windows: a thin ribbon plus a whisper of fill, so the
    // waveform stays readable underneath
    for (const clip of clips) {
      if (!clip.rank) continue
      const x0 = Math.max(0, (clip.start / duration) * width)
      const x1 = Math.min(width, (clip.end / duration) * width)
      const w = Math.max(1, x1 - x0)
      ctx.fillStyle = 'rgba(255, 92, 26, 0.07)'
      ctx.fillRect(x0, 0, w, height)
      ctx.fillStyle = 'rgba(255, 92, 26, 0.5)'
      ctx.fillRect(x0, 0, w, 2)
    }

    const n = peaks.buckets
    let magnitude = 1e-6
    for (let i = 0; i < n; i += 1) {
      magnitude = Math.max(magnitude, Math.abs(peaks.high[i] ?? 0), Math.abs(peaks.low[i] ?? 0))
    }
    const gain = 1 / magnitude

    // mirrored filled envelope; strokes per bucket read as dots at any zoom
    ctx.beginPath()
    for (let i = 0; i < n; i += 1) {
      const x = (i / Math.max(1, n - 1)) * width
      const y = mid - Math.abs(peaks.high[i] ?? 0) * gain * amp
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    for (let i = n - 1; i >= 0; i -= 1) {
      const x = (i / Math.max(1, n - 1)) * width
      const y = mid - Math.abs(peaks.low[i] ?? 0) * gain * amp
      ctx.lineTo(x, y)
    }
    ctx.closePath()
    ctx.fillStyle = '#454550'
    ctx.fill()
    ctx.strokeStyle = '#5a5a67'
    ctx.lineWidth = 0.6
    ctx.stroke()

    // playhead
    const px = (playhead / duration) * width
    ctx.strokeStyle = '#ede8e1'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(px + 0.5, 0)
    ctx.lineTo(px + 0.5, height)
    ctx.stroke()
  }, [peaks, duration, clips, playhead])

  return (
    <canvas
      ref={canvasRef}
      className="wave-canvas"
      onClick={(event) => {
        const rect = event.currentTarget.getBoundingClientRect()
        const ratio = (event.clientX - rect.left) / rect.width
        onSeek(Math.max(0, Math.min(duration, ratio * duration)))
      }}
    />
  )
}
