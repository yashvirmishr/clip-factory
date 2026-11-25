import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { MenuItemButton } from './MenuList'
import type { AppCommand } from './types'

interface ContextMenuProps {
  x: number
  y: number
  label: string
  items: Array<AppCommand | null>
  onRun: (command: AppCommand) => void
  onClose: () => void
}

export function ContextMenu({ x, y, label, items, onRun, onClose }: ContextMenuProps) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ x, y })

  useLayoutEffect(() => {
    const node = ref.current
    if (!node) return
    const rect = node.getBoundingClientRect()
    const margin = 8
    setPos({
      x: Math.max(margin, Math.min(x, window.innerWidth - rect.width - margin)),
      y: Math.max(margin, Math.min(y, window.innerHeight - rect.height - margin)),
    })
  }, [x, y, items.length])

  useEffect(() => {
    const node = ref.current
    const first = node?.querySelector<HTMLElement>('.menu-item:not(:disabled)')
    first?.focus()

    const onPointerDown = (event: PointerEvent) => {
      if (!node?.contains(event.target as Node)) onClose()
    }
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        onClose()
        return
      }
      if (event.key === 'Tab') {
        event.preventDefault()
        onClose()
        return
      }
      if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
      const focusable = Array.from(node?.querySelectorAll<HTMLElement>('.menu-item:not(:disabled)') ?? [])
      if (!focusable.length) return
      event.preventDefault()
      const current = focusable.indexOf(document.activeElement as HTMLElement)
      let next = current
      if (event.key === 'ArrowDown') next = current < 0 ? 0 : (current + 1) % focusable.length
      if (event.key === 'ArrowUp') next = current < 0 ? focusable.length - 1 : (current - 1 + focusable.length) % focusable.length
      if (event.key === 'Home') next = 0
      if (event.key === 'End') next = focusable.length - 1
      focusable[next]?.focus()
    }

    document.addEventListener('pointerdown', onPointerDown, true)
    document.addEventListener('keydown', onKeyDown, true)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true)
      document.removeEventListener('keydown', onKeyDown, true)
    }
  }, [onClose])

  return createPortal(
    <div
      ref={ref}
      className="context-menu"
      role="menu"
      aria-label={label}
      style={{ left: pos.x, top: pos.y }}
      onContextMenu={(event) => event.preventDefault()}
    >
      {items.map((item, index) =>
        item ? (
          <MenuItemButton
            key={item.id}
            command={item}
            onRun={(command) => {
              onRun(command)
              onClose()
            }}
          />
        ) : (
          <div className="menu-separator" role="separator" key={`sep-${index}`} />
        ),
      )}
    </div>,
    document.body,
  )
}
