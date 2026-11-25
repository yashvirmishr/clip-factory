import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { Icon } from './Icon'
import { MenuItemButton } from './MenuList'
import type { AppCommand, MenuDefinition } from './types'

interface MenuBarProps {
  menus: MenuDefinition[]
  commands: Record<string, AppCommand>
  onRun: (command: AppCommand) => void
  onOpenPalette: () => void
  onOpenShortcuts: () => void
}

export function MenuBar({ menus, commands, onRun, onOpenPalette, onOpenShortcuts }: MenuBarProps) {
  const [openId, setOpenId] = useState<string | null>(null)
  const barRef = useRef<HTMLDivElement>(null)
  const popupRef = useRef<HTMLDivElement>(null)
  const triggerRefs = useRef<Record<string, HTMLButtonElement | null>>({})

  const close = (restoreFocus = false) => {
    const id = openId
    setOpenId(null)
    if (restoreFocus && id) triggerRefs.current[id]?.focus()
  }

  useEffect(() => {
    if (!openId) return
    const timer = window.setTimeout(() => {
      const first = popupRef.current?.querySelector<HTMLElement>('.menu-item:not(:disabled)')
      first?.focus()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [openId])

  useEffect(() => {
    if (!openId) return
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node
      if (barRef.current?.contains(target)) return
      setOpenId(null)
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [openId])

  const run = (command: AppCommand) => {
    close(true)
    onRun(command)
  }

  const focusSibling = (index: number, direction: 1 | -1) => {
    const next = (index + direction + menus.length) % menus.length
    setOpenId(menus[next].id)
    triggerRefs.current[menus[next].id]?.focus()
  }

  const menuKey = (event: KeyboardEvent<HTMLDivElement>, id: string) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      close(true)
      return
    }
    if (event.key === 'Tab') {
      setOpenId(null)
      return
    }
    const items = Array.from(
      popupRef.current?.querySelectorAll<HTMLElement>('.menu-item:not(:disabled)') ?? [],
    )
    if (!items.length) return
    const current = items.indexOf(document.activeElement as HTMLElement)
    let next: number | null = null
    if (event.key === 'ArrowDown') next = current < 0 ? 0 : (current + 1) % items.length
    if (event.key === 'ArrowUp') next = current < 0 ? items.length - 1 : (current - 1 + items.length) % items.length
    if (event.key === 'Home') next = 0
    if (event.key === 'End') next = items.length - 1
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault()
      const triggerIndex = menus.findIndex((menu) => menu.id === id)
      focusSibling(triggerIndex, event.key === 'ArrowRight' ? 1 : -1)
      return
    }
    if (next === null) return
    event.preventDefault()
    items[next]?.focus()
  }

  return (
    <header className="menubar" ref={barRef}>
      <div className="menubar-brand" aria-label="Clip Factory">
        <img className="brand-mark" src="/brand/clip-factory-mark.png" alt="" width={20} height={20} />
        <span className="brand-title">Clip Factory</span>
        <span className="brand-version num">0.1</span>
      </div>

      <nav className="menubar-menus" aria-label="Application menu">
        {menus.map((menu, index) => {
          const open = openId === menu.id
          return (
            <div className="menu-anchor" key={menu.id}>
              <button
                type="button"
                ref={(node) => {
                  triggerRefs.current[menu.id] = node
                }}
                className="menu-trigger"
                aria-haspopup="menu"
                aria-expanded={open}
                aria-controls={`menu-${menu.id}`}
                data-open={open ? 'true' : undefined}
                onClick={() => setOpenId(open ? null : menu.id)}
                onPointerEnter={() => {
                  if (openId && !open) setOpenId(menu.id)
                }}
                onKeyDown={(event) => {
                  if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    setOpenId(menu.id)
                  } else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
                    event.preventDefault()
                    focusSibling(index, event.key === 'ArrowRight' ? 1 : -1)
                  }
                }}
              >
                {menu.label}
              </button>
              {open ? (
                <div
                  className="menu-popup"
                  id={`menu-${menu.id}`}
                  ref={popupRef}
                  role="menu"
                  aria-label={menu.label}
                  onKeyDown={(event) => menuKey(event, menu.id)}
                >
                  {menu.items.map((itemId, itemIndex) => {
                    if (itemId === '-') {
                      return <div className="menu-separator" role="separator" key={`sep-${itemIndex}`} />
                    }
                    const command = commands[itemId]
                    if (!command) return null
                    return <MenuItemButton key={command.id} command={command} onRun={run} />
                  })}
                </div>
              ) : null}
            </div>
          )
        })}
      </nav>

      <div className="menubar-right">
        <button type="button" className="command-trigger" onClick={onOpenPalette} title="Command palette (Ctrl K)">
          <Icon name="search" size={13} />
          <span>Command</span>
          <kbd className="kbd">Ctrl K</kbd>
        </button>
        <button type="button" className="icon-btn icon-btn-sm" onClick={onOpenShortcuts} aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)">
          <Icon name="keyboard" size={15} />
        </button>
      </div>
    </header>
  )
}
