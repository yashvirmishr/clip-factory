import { useRef, type PointerEvent, type ReactNode } from 'react'
import { Icon } from './Icon'
import { IconButton } from './ui'

export interface FloatRect {
  x: number
  y: number
  width: number
  height: number
}

interface InspectorFrameProps {
  floating: boolean
  rect: FloatRect
  onRect: (rect: FloatRect) => void
  onDock: () => void
  children: ReactNode
}

const MIN_WIDTH = 336
const MIN_HEIGHT = 380
const MARGIN = 8
const TOP_MIN = 36

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value))

export function InspectorFrame({ floating, rect, onRect, onDock, children }: InspectorFrameProps) {
  const rectRef = useRef(rect)
  rectRef.current = rect
  const drag = useRef<{ x: number; y: number; start: FloatRect; mode: 'move' | 'resize' } | null>(null)

  const begin = (event: PointerEvent<HTMLDivElement>, mode: 'move' | 'resize') => {
    if (!floating || event.button !== 0) return
    if (mode === 'move' && (event.target as HTMLElement).closest('button')) return
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    drag.current = { x: event.clientX, y: event.clientY, start: rectRef.current, mode }
    document.body.dataset.resizing = 'true'
  }

  const move = (event: PointerEvent<HTMLDivElement>) => {
    const state = drag.current
    if (!state) return
    const dx = event.clientX - state.x
    const dy = event.clientY - state.y
    if (state.mode === 'move') {
      const maxX = Math.max(MARGIN, window.innerWidth - state.start.width - MARGIN)
      const maxY = Math.max(TOP_MIN, window.innerHeight - state.start.height - MARGIN)
      onRect({
        ...state.start,
        x: clamp(state.start.x + dx, MARGIN, maxX),
        y: clamp(state.start.y + dy, TOP_MIN, maxY),
      })
    } else {
      const maxWidth = Math.max(MIN_WIDTH, window.innerWidth - state.start.x - MARGIN)
      const maxHeight = Math.max(MIN_HEIGHT, window.innerHeight - state.start.y - MARGIN)
      onRect({
        ...state.start,
        width: clamp(state.start.width + dx, MIN_WIDTH, maxWidth),
        height: clamp(state.start.height + dy, MIN_HEIGHT, maxHeight),
      })
    }
  }

  const end = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    drag.current = null
    delete document.body.dataset.resizing
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  return (
    <div
      className={`inspector-frame ${floating ? 'is-floating' : 'is-docked'}`}
      style={
        floating
          ? { left: rect.x, top: rect.y, width: rect.width, height: rect.height }
          : undefined
      }
    >
      <div
        className="float-bar"
        hidden={!floating}
        onPointerDown={(event) => begin(event, 'move')}
        onPointerMove={move}
        onPointerUp={end}
        onPointerCancel={end}
        onDoubleClick={onDock}
      >
        <span className="float-grip" aria-hidden="true">
          <Icon name="grip" size={14} />
        </span>
        <span className="float-title">Inspector</span>
        <span className="float-sub">Floating</span>
        <span className="float-actions">
          <IconButton icon="dock" size="sm" label="Dock inspector" onClick={onDock} />
        </span>
      </div>

      {children}

      <div
        className="float-resize"
        aria-hidden="true"
        onPointerDown={(event) => begin(event, 'resize')}
        onPointerMove={move}
        onPointerUp={end}
        onPointerCancel={end}
      >
        <span />
      </div>
    </div>
  )
}
