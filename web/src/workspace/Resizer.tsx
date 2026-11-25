import { useRef, type KeyboardEvent, type PointerEvent } from 'react'

interface ResizerProps {
  side: 'left' | 'right'
  value: number
  min: number
  max: number
  onChange: (value: number) => void
  onReset: () => void
  label: string
  controls: string
}

const STEP = 16

export function Resizer({ side, value, min, max, onChange, onReset, label, controls }: ResizerProps) {
  const drag = useRef<{ x: number; start: number } | null>(null)
  const clamp = (next: number) => Math.max(min, Math.min(max, Math.round(next)))

  const begin = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    event.currentTarget.dataset.active = 'true'
    drag.current = { x: event.clientX, start: value }
    document.body.dataset.resizing = 'true'
  }

  const move = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    const delta = event.clientX - drag.current.x
    onChange(clamp(drag.current.start + (side === 'left' ? delta : -delta)))
  }

  const end = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    drag.current = null
    delete event.currentTarget.dataset.active
    delete document.body.dataset.resizing
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  const key = (event: KeyboardEvent<HTMLDivElement>) => {
    let next: number | null = null
    if (event.key === 'ArrowLeft') next = value + (side === 'left' ? -STEP : STEP)
    if (event.key === 'ArrowRight') next = value + (side === 'left' ? STEP : -STEP)
    if (event.key === 'Home') next = min
    if (event.key === 'End') next = max
    if (event.key === 'Enter') {
      event.preventDefault()
      onReset()
      return
    }
    if (next === null) return
    event.preventDefault()
    onChange(clamp(next))
  }

  return (
    <div
      className={`resizer resizer-${side}`}
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-controls={controls}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={Math.round(value)}
      tabIndex={0}
      onPointerDown={begin}
      onPointerMove={move}
      onPointerUp={end}
      onPointerCancel={end}
      onDoubleClick={onReset}
      onKeyDown={key}
    >
      <span aria-hidden="true" />
    </div>
  )
}
