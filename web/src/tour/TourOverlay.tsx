import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { Readiness } from '../types'
import { SetupCards } from './SetupCards'
import type { TourActionId, TourStep } from './types'

interface Props {
  step: TourStep
  index: number
  total: number
  compact: boolean
  readiness: Readiness | null
  readinessError: string | null
  onRefresh: () => void
  onOpenSetup: () => void
  onNext: () => void
  onBack: () => void
  onClose: () => void
  onAction: (id: TourActionId) => void
}

const CARD_W = 380
const CARD_H = 300
const GAP = 18
const MARGIN = 14

function visibleAnchor(name?: string): DOMRect | null {
  if (!name) return null
  const nodes = Array.from(document.querySelectorAll<HTMLElement>(`[data-tour="${name}"]`))
  const live = nodes.find((node) => {
    if (node.offsetParent === null) return false
    const rect = node.getBoundingClientRect()
    return rect.width > 4 && rect.height > 4 && rect.bottom > 0 && rect.top < window.innerHeight
  })
  return live ? live.getBoundingClientRect() : null
}

/**
 * The tour sits above the workspace and below dialogs. Steps that point at a
 * real control keep the page interactive; only the explain cards (setup and the
 * final wrap) behave like a modal and trap focus.
 */
export function TourOverlay({
  step,
  index,
  total,
  compact,
  readiness,
  readinessError,
  onRefresh,
  onOpenSetup,
  onNext,
  onBack,
  onClose,
  onAction,
}: Props) {
  const titleId = useId()
  const cardRef = useRef<HTMLElement>(null)
  const [rect, setRect] = useState<DOMRect | null>(null)
  const [size, setSize] = useState({ width: window.innerWidth, height: window.innerHeight })

  const anchored = Boolean(step.anchor) && !compact
  const modal = !anchored || Boolean(step.panel)

  // Anchors move: panels resize, the inspector lifts out, the window changes.
  useLayoutEffect(() => {
    if (!anchored) {
      setRect(null)
      return
    }
    let frame = 0
    const measure = () => {
      frame = 0
      setRect(visibleAnchor(step.anchor))
      setSize({ width: window.innerWidth, height: window.innerHeight })
    }
    const schedule = () => {
      if (!frame) frame = window.requestAnimationFrame(measure)
    }
    measure()
    window.addEventListener('resize', schedule)
    window.addEventListener('scroll', schedule, true)
    const timer = window.setInterval(schedule, 500)
    return () => {
      window.removeEventListener('resize', schedule)
      window.removeEventListener('scroll', schedule, true)
      window.clearInterval(timer)
      if (frame) window.cancelAnimationFrame(frame)
    }
  }, [anchored, step.anchor, index])

  const cardStyle = (() => {
    if (!rect) {
      // Centred cards are taller than CARD_H, so CSS centres them; only the
      // horizontal position is measured here.
      const width = Math.min(468, size.width - MARGIN * 2)
      return { left: Math.max(MARGIN, (size.width - width) / 2) }
    }
    const rightRoom = size.width - rect.right
    const leftRoom = rect.left
    let left: number
    if (rightRoom > CARD_W + GAP) left = rect.right + GAP
    else if (leftRoom > CARD_W + GAP) left = rect.left - CARD_W - GAP
    else left = Math.max(MARGIN, Math.min(size.width - CARD_W - MARGIN, rect.left))
    const top = Math.max(
      MARGIN,
      Math.min(size.height - CARD_H - MARGIN, rect.top + rect.height / 2 - CARD_H / 2),
    )
    return { left, top }
  })()

  // Focus the primary action when a card opens, and hand focus back afterwards.
  useEffect(() => {
    if (!modal) return
    const previous = document.activeElement as HTMLElement | null
    const timer = window.setTimeout(() => {
      const target =
        cardRef.current?.querySelector<HTMLElement>('[data-tour-primary]') ?? cardRef.current
      target?.focus()
    }, 40)
    return () => {
      window.clearTimeout(timer)
      if (previous?.isConnected) previous.focus()
    }
  }, [modal, index])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        onClose()
        return
      }
      if (event.key === 'ArrowRight' && !event.shiftKey) {
        event.preventDefault()
        onNext()
        return
      }
      if (event.key === 'ArrowLeft' && !event.shiftKey) {
        event.preventDefault()
        onBack()
        return
      }
      if (!modal || event.key !== 'Tab' || !cardRef.current) return
      const focusable = Array.from(
        cardRef.current.querySelectorAll<HTMLElement>(
          'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => element.offsetParent !== null)
      if (!focusable.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown, true)
    return () => document.removeEventListener('keydown', onKeyDown, true)
  }, [modal, onClose, onNext, onBack])

  const primary = step.action
  const skipLabel = index === 0 ? 'Skip to the app' : 'Skip the tour'
  // An anchored step whose control is not on screen (nothing selected yet, for
  // example) would otherwise offer a button that cannot do anything. Fall back
  // to the secondary action, or to simply moving on.
  const actionMissing = Boolean(step.anchor) && !rect
  const fallbackAction = step.secondary
  const primaryLabel = actionMissing
    ? (fallbackAction?.label ?? 'Continue')
    : (primary?.label ?? 'Continue')
  const runPrimary = () => {
    if (actionMissing) {
      if (fallbackAction) onAction(fallbackAction.id)
      else onNext()
      return
    }
    if (primary) onAction(primary.id)
    else onNext()
  }

  return (
    <div className="tour-layer">
      {rect ? (
        <div
          className="tour-spot"
          aria-hidden="true"
          style={{
            left: rect.left - 6,
            top: rect.top - 6,
            width: rect.width + 12,
            height: rect.height + 12,
          }}
        />
      ) : (
        <div className="tour-scrim" aria-hidden="true" />
      )}

      <section
        className={`tour-card${rect ? ' anchored' : ' centred'}`}
        style={cardStyle}
        role="dialog"
        aria-modal={modal || undefined}
        aria-labelledby={titleId}
        ref={cardRef}
        tabIndex={-1}
      >
        <header className="tour-head">
          <span className="tour-eyebrow">
            {index < 2 ? 'Setup' : 'Tour'} &nbsp;·&nbsp; {index + 1} of {total}
          </span>
          <button type="button" className="tour-close" aria-label="Pause the tour" onClick={onClose}>
            ×
          </button>
        </header>

        <h3 id={titleId} className="tour-title">
          {step.title}
        </h3>

        {step.body ? <p className="tour-body">{step.body}</p> : null}
        {step.panel ? (
          <SetupCards
            variant={step.panel}
            readiness={readiness}
            error={readinessError}
            onRefresh={onRefresh}
            onOpenSetup={onOpenSetup}
          />
        ) : null}

        <footer className="tour-foot">
          <div className="tour-foot-left">
            {index > 0 ? (
              <button type="button" className="btn sm ghost" onClick={onBack}>
                Back
              </button>
            ) : null}
            <button type="button" className="tour-skip" onClick={onClose}>
              {skipLabel}
            </button>
          </div>
          <div className="tour-foot-right">
            {step.secondary && !actionMissing ? (
              <button
                type="button"
                className="btn sm ghost"
                onClick={() => onAction(step.secondary!.id)}
              >
                {step.secondary.label}
              </button>
            ) : null}
            <button type="button" className="btn sm primary" data-tour-primary onClick={runPrimary}>
              {primaryLabel}
            </button>
          </div>
        </footer>

        <div className="tour-dots" aria-hidden="true">
          {Array.from({ length: total }, (_, dot) => (
            <span key={dot} data-on={dot <= index ? 'true' : undefined} />
          ))}
        </div>
      </section>
    </div>
  )
}
