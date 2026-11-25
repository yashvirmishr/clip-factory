import { useEffect, useId, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { IconButton } from './ui'

interface ModalProps {
  title: string
  eyebrow?: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  width?: number
  className?: string
}

export function Modal({ title, eyebrow, onClose, children, footer, width = 720, className }: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef(onClose)
  const titleId = useId()
  closeRef.current = onClose

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const node = dialogRef.current
    const focusFirst = () => {
      const preferred = node?.querySelector<HTMLElement>('[data-autofocus]')
      const fallback = node?.querySelector<HTMLElement>(
        'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
      )
      ;(preferred ?? fallback ?? node)?.focus()
    }
    const timer = window.setTimeout(focusFirst, 30)

    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        closeRef.current()
        return
      }
      if (event.key !== 'Tab' || !node) return
      const focusable = Array.from(
        node.querySelectorAll<HTMLElement>(
          'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => element.offsetParent !== null)
      if (!focusable.length) {
        event.preventDefault()
        node.focus()
        return
      }
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
    return () => {
      window.clearTimeout(timer)
      document.removeEventListener('keydown', onKeyDown, true)
      if (previous?.isConnected) previous.focus()
    }
  }, [])

  return createPortal(
    <div
      className="modal-scrim"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        ref={dialogRef}
        className={`modal ${className ?? ''}`.trim()}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        style={{ width: `min(${width}px, calc(100vw - 48px))` }}
      >
        <header className="modal-head">
          <div>
            {eyebrow ? <p className="label">{eyebrow}</p> : null}
            <h2 id={titleId}>{title}</h2>
          </div>
          <IconButton icon="x" label="Close dialog" onClick={onClose} />
        </header>
        <div className="modal-body">{children}</div>
        {footer ? <footer className="modal-foot">{footer}</footer> : null}
      </div>
    </div>,
    document.body,
  )
}
