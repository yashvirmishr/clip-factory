import type { ReactNode } from 'react'

/**
 * One stroke weight, one 24px grid, one visual language. Every icon in the app
 * comes from this file so panels, menus and transport controls never drift
 * apart.
 */
const ICONS = {
  film: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4" />
    </>
  ),
  folder: (
    <path d="M3 7.5A2.5 2.5 0 0 1 5.5 5h3.2a2 2 0 0 1 1.5.7L11.5 7h7A2.5 2.5 0 0 1 21 9.5v7A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5z" />
  ),
  sparkles: (
    <>
      <path d="M11.5 3.5 13 8l4.5 1.5L13 11l-1.5 4.5L10 11 5.5 9.5 10 8z" />
      <path d="m18 14 .8 2.2L21 17l-2.2.8L18 20l-.8-2.2L15 17l2.2-.8z" />
    </>
  ),
  play: <path d="M8 5.2v13.6l10.5-6.8z" fill="currentColor" stroke="none" />,
  pause: <path d="M8.5 5v14M15.5 5v14" strokeWidth="2.6" />,
  'skip-back': (
    <>
      <path d="M18.5 5.5v13L8.5 12z" fill="currentColor" stroke="none" />
      <path d="M5 5v14" strokeWidth="2" />
    </>
  ),
  'skip-forward': (
    <>
      <path d="M5.5 5.5v13L15.5 12z" fill="currentColor" stroke="none" />
      <path d="M19 5v14" strokeWidth="2" />
    </>
  ),
  'step-back': (
    <>
      <path d="M17 6.5v11L9 12z" fill="currentColor" stroke="none" />
      <path d="M6 5v14" strokeWidth="2" />
    </>
  ),
  'step-forward': (
    <>
      <path d="M7 6.5v11L15 12z" fill="currentColor" stroke="none" />
      <path d="M18 5v14" strokeWidth="2" />
    </>
  ),
  volume: (
    <>
      <path d="M11 5 6.5 9H3v6h3.5L11 19z" />
      <path d="M15 8.8a4.5 4.5 0 0 1 0 6.4M18 6a8.5 8.5 0 0 1 0 12" />
    </>
  ),
  'volume-x': (
    <>
      <path d="M11 5 6.5 9H3v6h3.5L11 19z" />
      <path d="m15.5 9.5 5 5M20.5 9.5l-5 5" />
    </>
  ),
  maximize: <path d="M8 3H3v5M16 3h5v5M21 16v5h-5M3 16v5h5" />,
  repeat: (
    <>
      <path d="m17 2.5 4 4-4 4" />
      <path d="M3 11.5v-1a4 4 0 0 1 4-4h14" />
      <path d="m7 21.5-4-4 4-4" />
      <path d="M21 12.5v1a4 4 0 0 1-4 4H3" />
    </>
  ),
  captions: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M10.5 10.4a2.6 2.6 0 1 0 0 3.2M17.5 10.4a2.6 2.6 0 1 0 0 3.2" />
    </>
  ),
  eye: (
    <>
      <path d="M2.5 12S6 6.5 12 6.5 21.5 12 21.5 12 18 17.5 12 17.5 2.5 12 2.5 12z" />
      <circle cx="12" cy="12" r="2.6" />
    </>
  ),
  'eye-off': (
    <>
      <path d="m3 3 18 18" />
      <path d="M10.6 6.2c.5-.1.9-.2 1.4-.2 6 0 9.5 6 9.5 6a16 16 0 0 1-3.2 3.8M6.5 6.7A16.4 16.4 0 0 0 2.5 12s3.5 5.5 9.5 5.5c1.4 0 2.6-.3 3.8-.8" />
      <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4.5 4.5" />
    </>
  ),
  x: <path d="M6 6l12 12M18 6 6 18" />,
  'chevron-down': <path d="m6 9 6 6 6-6" />,
  'chevron-up': <path d="m6 15 6-6 6 6" />,
  'chevron-left': <path d="m15 6-6 6 6 6" />,
  'chevron-right': <path d="m9 6 6 6-6 6" />,
  'panel-left': (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M9 4v16" />
    </>
  ),
  'panel-right': (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M15 4v16" />
    </>
  ),
  external: (
    <>
      <path d="M14 4h6v6" />
      <path d="M20 4 11 13" />
      <path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4" />
    </>
  ),
  dock: (
    <>
      <path d="M14 4h6v16h-6" />
      <path d="M4 12h10M10 8l4 4-4 4" />
    </>
  ),
  sliders: (
    <>
      <path d="M4 6h9M18 6h2M4 12h3M12 12h8M4 18h10M19 18h1" />
      <circle cx="15.5" cy="6" r="2" />
      <circle cx="9.5" cy="12" r="2" />
      <circle cx="16.5" cy="18" r="2" />
    </>
  ),
  keyboard: (
    <>
      <rect x="2" y="6" width="20" height="12" rx="2" />
      <path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10" />
    </>
  ),
  command: (
    <path d="M9 6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3z" />
  ),
  check: <path d="m4 12.5 5 5L20 6.5" />,
  alert: (
    <>
      <path d="M12 3 2 21h20z" />
      <path d="M12 9.5v4.5M12 18h.01" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 8h.01" />
    </>
  ),
  copy: (
    <>
      <rect x="8.5" y="8.5" width="12.5" height="12.5" rx="2" />
      <path d="M16 8.5V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3.5" />
    </>
  ),
  scissors: (
    <>
      <circle cx="6" cy="6" r="2.8" />
      <circle cx="6" cy="18" r="2.8" />
      <path d="M8.2 8.1 20 20M8.2 15.9 20 4" />
    </>
  ),
  download: (
    <>
      <path d="M12 3v12M7 10.5l5 5 5-5" />
      <path d="M4 19.5h16" />
    </>
  ),
  upload: (
    <>
      <path d="M12 21V9M7 14l5-5 5 5" />
      <path d="M4 4.5h16" />
    </>
  ),
  more: (
    <>
      <circle cx="5" cy="12" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="19" cy="12" r="1.3" fill="currentColor" stroke="none" />
    </>
  ),
  list: (
    <>
      <path d="M9 6h11M9 12h11M9 18h11" />
      <circle cx="4.5" cy="6" r="1.2" fill="currentColor" stroke="none" />
      <circle cx="4.5" cy="12" r="1.2" fill="currentColor" stroke="none" />
      <circle cx="4.5" cy="18" r="1.2" fill="currentColor" stroke="none" />
    </>
  ),
  grid: (
    <>
      <rect x="3.5" y="3.5" width="7" height="7" rx="1" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="1" />
      <rect x="3.5" y="13.5" width="7" height="7" rx="1" />
      <rect x="13.5" y="13.5" width="7" height="7" rx="1" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5.5l3.5 2" />
    </>
  ),
  monitor: (
    <>
      <rect x="2.5" y="4" width="19" height="13" rx="2" />
      <path d="M8 21h8M12 17v4" />
    </>
  ),
  timeline: (
    <>
      <path d="M3 6.5h18M3 12h18M3 17.5h18" opacity=".55" />
      <rect x="5" y="4.5" width="5" height="4" rx="1" fill="currentColor" stroke="none" />
      <rect x="12" y="10" width="7" height="4" rx="1" fill="currentColor" stroke="none" />
      <rect x="7" y="15.5" width="6" height="4" rx="1" fill="currentColor" stroke="none" />
    </>
  ),
  refresh: (
    <>
      <path d="M20.5 8v5h-5" />
      <path d="M3.5 16v-5h5" />
      <path d="M6.2 8.5A8 8 0 0 1 20.5 13M17.8 15.5A8 8 0 0 1 3.5 11" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  minus: <path d="M5 12h14" />,
  crop: (
    <>
      <path d="M6 2v16h16" />
      <path d="M2 6h16v16" />
    </>
  ),
  activity: <path d="M3 12h3.5l2.2-6.5 4.1 13L15 12h6" />,
  layers: (
    <>
      <path d="m12 3 9 5-9 5-9-5z" />
      <path d="m3 13 9 5 9-5" />
      <path d="m3 17.5 9 5 9-5" />
    </>
  ),
  'arrow-up-right': <path d="M7 17 17 7M9 7h8v8" />,
  'play-circle': (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M10 8.5v7l5.5-3.5z" fill="currentColor" stroke="none" />
    </>
  ),
  flag: <path d="M5 21V4M5 4h11.5l-1.8 4 1.8 4H5" />,
  ban: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m5.7 5.7 12.6 12.6" />
    </>
  ),
  grip: (
    <>
      <circle cx="9" cy="6" r="1.1" fill="currentColor" stroke="none" />
      <circle cx="15" cy="6" r="1.1" fill="currentColor" stroke="none" />
      <circle cx="9" cy="12" r="1.1" fill="currentColor" stroke="none" />
      <circle cx="15" cy="12" r="1.1" fill="currentColor" stroke="none" />
      <circle cx="9" cy="18" r="1.1" fill="currentColor" stroke="none" />
      <circle cx="15" cy="18" r="1.1" fill="currentColor" stroke="none" />
    </>
  ),
  filter: <path d="M3 5h18l-7 8.5V20l-4 2v-8.5z" />,
  sort: (
    <>
      <path d="M7 4v16M3.5 16.5 7 20l3.5-3.5" />
      <path d="M17 20V4M13.5 7.5 17 4l3.5 3.5" />
    </>
  ),
  'zoom-in': (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M11 8.5v5M8.5 11h5M16 16l4.5 4.5" />
    </>
  ),
  'zoom-out': (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M8.5 11h5M16 16l4.5 4.5" />
    </>
  ),
  'fit-width': (
    <>
      <path d="M3 12h18M7 8l-4 4 4 4M17 8l4 4-4 4" />
    </>
  ),
  'save': (
    <>
      <path d="M5 3h11l3 3v15H5z" />
      <path d="M8 3v6h8V3M8 21v-7h8v7" />
    </>
  ),
  'folder-open': (
    <path d="M3 7.5A2.5 2.5 0 0 1 5.5 5h3.2a2 2 0 0 1 1.5.7L11.5 7h7A2.5 2.5 0 0 1 21 9.5v.5H6a2 2 0 0 0-2 1.7L3 19z" />
  ),
  palette: (
    <>
      <path d="M12 3a9 9 0 0 0 0 18h.6a1.8 1.8 0 0 0 1.2-3.1 1.8 1.8 0 0 1 1.2-3.1H17A4 4 0 0 0 21 11a8 8 0 0 0-9-8z" />
      <circle cx="7.8" cy="10" r="1" fill="currentColor" stroke="none" />
      <circle cx="10.3" cy="6.8" r="1" fill="currentColor" stroke="none" />
      <circle cx="14.2" cy="7.1" r="1" fill="currentColor" stroke="none" />
    </>
  ),
  sun: (
    <>
      <circle cx="12" cy="12" r="3.6" />
      <path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M18.7 5.3l-1.4 1.4M6.7 17.3l-1.4 1.4" />
    </>
  ),
  moon: <path d="M20.2 15.2A8.6 8.6 0 0 1 8.8 3.8 8.7 8.7 0 1 0 20.2 15.2z" />,
  trash: (
    <>
      <path d="M4 7h16M9 7V4h6v3M6.5 7l.9 13h9.2l.9-13M10 11v6M14 11v6" />
    </>
  ),
} satisfies Record<string, ReactNode>

export type IconName = keyof typeof ICONS

interface IconProps {
  name: IconName
  size?: number
  strokeWidth?: number
  className?: string
}

export function Icon({ name, size = 16, strokeWidth = 1.5, className }: IconProps) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      className={className ? `icon ${className}` : 'icon'}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {ICONS[name]}
    </svg>
  )
}