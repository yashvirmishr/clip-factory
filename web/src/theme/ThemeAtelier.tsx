import { useEffect, useRef, useState } from 'react'
import { Modal } from '../workspace/Modal'
import { Icon } from '../workspace/Icon'
import { contrastRatio, formatRatio, normalizeHex, readableOn, slugify } from './color'
import { BUILTIN_THEMES, parseThemeFile, themePackage, uniqueCustomId } from './index'
import type { ThemeDefinition, ThemeSeeds } from './types'
import { COLOR_HINTS, COLOR_LABELS, THEME_SEED_KEYS } from './types'
import { ThemePreview } from './ThemePreview'

type Mode = 'browse' | 'studio'
type SchemeFilter = 'all' | 'light' | 'dark'
type ToastKind = 'ok' | 'error' | 'info'

interface ThemeAtelierProps {
  themes: ThemeDefinition[]
  activeId: string
  onClose: () => void
  onApply: (id: string) => void
  onSave: (theme: ThemeDefinition) => void
  onDelete: (id: string) => void
  onToast: (kind: ToastKind, message: string) => void
}

const isBuiltin = (theme: ThemeDefinition) => BUILTIN_THEMES.some((item) => item.id === theme.id)

function contrastChecks(theme: ThemeDefinition) {
  return [
    { label: 'Ink on canvas', ratio: contrastRatio(theme.seeds.ink, theme.seeds.canvas) },
    { label: 'Ink on surface', ratio: contrastRatio(theme.seeds.ink, theme.seeds.surface) },
    { label: 'Monitor labels', ratio: contrastRatio(theme.seeds.stageInk, theme.seeds.stage) },
    {
      label: 'Accent labels',
      ratio: contrastRatio(readableOn(theme.seeds.accent), theme.seeds.accent),
    },
  ]
}

function SeedField({
  name,
  value,
  onChange,
}: {
  name: keyof ThemeSeeds
  value: string
  onChange: (value: string) => void
}) {
  const [text, setText] = useState(value)
  useEffect(() => setText(value), [value])

  const commit = (next: string) => {
    setText(next)
    const normalized = normalizeHex(next)
    if (normalized) onChange(normalized)
  }

  return (
    <div className="seed-field" title={COLOR_HINTS[name]}>
      <div className="seed-field-head">
        <span>{COLOR_LABELS[name]}</span>
        <span className="seed-field-hint">{COLOR_HINTS[name]}</span>
      </div>
      <div className="seed-control">
        <label className="seed-swatch" style={{ background: value }} title={`Pick ${COLOR_LABELS[name].toLowerCase()}`}>
          <input
            type="color"
            value={value}
            aria-label={`${COLOR_LABELS[name]} colour picker`}
            onChange={(event) => commit(event.target.value)}
          />
        </label>
        <input
          className="seed-hex num"
          value={text}
          spellCheck={false}
          aria-label={`${COLOR_LABELS[name]} hex value`}
          onChange={(event) => commit(event.target.value)}
          onBlur={() => {
            if (!normalizeHex(text)) setText(value)
          }}
        />
      </div>
    </div>
  )
}

export function ThemeAtelier({
  themes,
  activeId,
  onClose,
  onApply,
  onSave,
  onDelete,
  onToast,
}: ThemeAtelierProps) {
  const [mode, setMode] = useState<Mode>('browse')
  const [selectedId, setSelectedId] = useState(activeId)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<SchemeFilter>('all')
  const [draft, setDraft] = useState<ThemeDefinition | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const importRef = useRef<HTMLInputElement>(null)

  const customThemes = themes.filter((theme) => !isBuiltin(theme))
  const selected = themes.find((theme) => theme.id === selectedId) ?? themes[0]
  const activeTheme = themes.find((theme) => theme.id === activeId) ?? themes[0]

  useEffect(() => {
    if (draft?.id === selectedId) return
    if (!themes.some((theme) => theme.id === selectedId)) setSelectedId(activeId)
  }, [activeId, draft?.id, selectedId, themes])

  useEffect(() => {
    if (mode === 'studio') {
      const timer = window.setTimeout(() => document.getElementById('theme-name')?.focus(), 40)
      return () => window.clearTimeout(timer)
    }
  }, [mode])

  const filtered = themes.filter((theme) => {
    if (filter !== 'all' && theme.scheme !== filter) return false
    const haystack = [theme.name, theme.author, theme.description, ...theme.tags].join(' ').toLowerCase()
    return haystack.includes(query.trim().toLowerCase())
  })

  const makeDraft = (base: ThemeDefinition, name: string): ThemeDefinition => {
    let id = `custom-${slugify(name) || 'theme'}-${Date.now().toString(36).slice(-4)}`
    let attempt = 1
    while (themes.some((theme) => theme.id === id)) {
      id = `custom-${slugify(name) || 'theme'}-${attempt}`
      attempt += 1
    }
    return {
      ...base,
      id,
      name,
      author: 'You',
      description: base.description,
      tags: base.tags.slice(0, 4),
      seeds: { ...base.seeds },
      fonts: { ...base.fonts },
    }
  }

  const startStudio = (base: ThemeDefinition, name: string) => {
    const created = makeDraft(base, name)
    setDraft(created)
    setSelectedId(created.id)
    setConfirmDelete(false)
    setMode('studio')
  }

  const openStudio = (theme: ThemeDefinition) => {
    if (!isBuiltin(theme)) {
      setDraft(theme)
      setSelectedId(theme.id)
      setConfirmDelete(false)
      setMode('studio')
      return
    }
    startStudio(theme, `${theme.name} remix`)
  }

  const newTheme = () => {
    const base = draft ?? selected ?? activeTheme
    startStudio(base, 'Untitled theme')
  }

  const updateDraft = (patch: Partial<ThemeDefinition>) => {
    if (!draft) return
    const next = { ...draft, ...patch }
    setDraft(next)
    onSave(next)
    if (next.id === activeId) onApply(next.id)
  }

  const updateSeed = (name: keyof ThemeSeeds, value: string) => {
    if (!draft) return
    updateDraft({ seeds: { ...draft.seeds, [name]: value } })
  }

  const downloadTheme = (theme: ThemeDefinition) => {
    const blob = new Blob([JSON.stringify(themePackage(theme), null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${slugify(theme.name) || 'clip-factory-theme'}.clip-theme.json`
    document.body.append(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    onToast('ok', `“${theme.name}” exported.`)
  }

  const shareTheme = async (theme: ThemeDefinition) => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(themePackage(theme), null, 2))
      onToast('ok', 'Theme JSON copied — paste it anywhere.')
    } catch {
      downloadTheme(theme)
      onToast('ok', 'Clipboard was blocked. The theme file was downloaded instead.')
    }
  }

  const importTheme = async (file: File) => {
    const result = parseThemeFile(await file.text())
    if (!result.theme) {
      onToast('error', result.error ?? 'That theme could not be read.')
      return
    }
    const imported = uniqueCustomId(result.theme, customThemes)
    onSave(imported)
    onApply(imported.id)
    setSelectedId(imported.id)
    setDraft(null)
    setMode('browse')
    onToast('ok', `“${imported.name}” added to your library.`)
  }

  const draftSaved = Boolean(draft && themes.some((theme) => theme.id === draft.id))

  const useDraft = () => {
    if (!draft) return
    if (!draftSaved) onSave(draft)
    onApply(draft.id)
  }

  const deleteDraft = () => {
    if (!draft) return
    if (draftSaved) onDelete(draft.id)
    setDraft(null)
    setSelectedId(BUILTIN_THEMES[0].id)
    setConfirmDelete(false)
    setMode('browse')
    onToast(
      'ok',
      draftSaved
        ? draft.id === activeTheme.id
          ? 'Theme deleted. The default room is back.'
          : 'Theme deleted. Your room is unchanged.'
        : 'Draft discarded.',
    )
  }

  return (
    <Modal
      title="Theme atelier"
      eyebrow="Appearance / Marketplace"
      onClose={onClose}
      width={1180}
      className="theme-modal"
    >
      <div className="atelier-shell">
        <div className="atelier-toolbar">
          <div className="atelier-tabs" role="tablist" aria-label="Theme views">
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'browse'}
              className="atelier-tab"
              data-active={mode === 'browse' ? 'true' : undefined}
              onClick={() => setMode('browse')}
            >
              Marketplace
              <span className="atelier-tab-count">{themes.length}</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'studio'}
              className="atelier-tab"
              data-active={mode === 'studio' ? 'true' : undefined}
              onClick={() => (draft ? setMode('studio') : openStudio(selected ?? activeTheme))}
            >
              Studio
              {customThemes.length ? <span className="atelier-tab-count">{customThemes.length}</span> : null}
            </button>
          </div>

          <div className="atelier-toolbar-spacer" />

          {mode === 'browse' ? (
            <>
              <label className="atelier-search">
                <Icon name="search" size={13} />
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search themes, authors, tags"
                  aria-label="Search themes"
                />
              </label>
              <div className="atelier-filter" role="group" aria-label="Filter by scheme">
                {(['all', 'light', 'dark'] as SchemeFilter[]).map((value) => (
                  <button
                    type="button"
                    key={value}
                    className="atelier-filter-button"
                    data-active={filter === value ? 'true' : undefined}
                    aria-pressed={filter === value}
                    onClick={() => setFilter(value)}
                  >
                    {value === 'all' ? 'All' : value === 'light' ? 'Light' : 'Dark'}
                  </button>
                ))}
              </div>
              <button type="button" className="btn ghost atelier-import" onClick={() => importRef.current?.click()}>
                <Icon name="upload" size={13} />
                Import
              </button>
              <input
                ref={importRef}
                type="file"
                accept=".json,application/json"
                hidden
                onChange={(event) => {
                  const file = event.target.files?.[0]
                  if (file) void importTheme(file)
                  event.target.value = ''
                }}
              />
            </>
          ) : (
            <span className="atelier-saved" data-state={draftSaved ? 'saved' : 'draft'}>
              <Icon name={draftSaved ? 'check' : 'save'} size={12} />
              {draftSaved ? 'Saved locally' : 'Local draft'}
            </span>
          )}
        </div>

        {mode === 'browse' ? (
          <>
            <div className="atelier-body">
              <div className="atelier-grid">
                {filtered.map((theme) => {
                  const applied = theme.id === activeId
                  const custom = !isBuiltin(theme)
                  return (
                    <button
                      type="button"
                      key={theme.id}
                      className="theme-card"
                      data-active={theme.id === selectedId ? 'true' : undefined}
                      aria-pressed={theme.id === selectedId}
                      onClick={() => {
                        setSelectedId(theme.id)
                        setDraft(null)
                      }}
                      onDoubleClick={() => onApply(theme.id)}
                    >
                      <ThemePreview theme={theme} />
                      <span className="theme-card-meta">
                        <span className="theme-card-identity">
                          <strong>{theme.name}</strong>
                          <span>
                            {theme.author}
                            {custom && theme.author === 'You' ? ' · Yours' : ''}
                          </span>
                        </span>
                        <span className="theme-card-scheme">{theme.scheme}</span>
                      </span>
                      {applied ? (
                        <span className="theme-card-applied">
                          <Icon name="check" size={10} />
                          In use
                        </span>
                      ) : null}
                    </button>
                  )
                })}

                <button type="button" className="theme-card theme-card-new" onClick={newTheme}>
                  <span className="theme-new-mark">
                    <Icon name="plus" size={20} />
                  </span>
                  <span className="theme-new-title">Make a theme</span>
                  <span className="theme-new-copy">Nine colours, one room. Start from the current theme and make it yours.</span>
                  <span className="theme-new-foot">
                    <Icon name="palette" size={12} />
                    Opens the studio
                  </span>
                </button>

                {!filtered.length ? (
                  <div className="atelier-empty">
                    <span className="label">No matches</span>
                    <h3>Try a different room.</h3>
                    <p>Search by colour mood, author or tag — or clear the filters.</p>
                    <button type="button" className="btn ghost" onClick={() => { setQuery(''); setFilter('all') }}>
                      Clear search
                    </button>
                  </div>
                ) : null}
              </div>
            </div>

            {selected ? (
              <footer className="atelier-actions">
                <div className="atelier-selection">
                  <span className="atelier-selection-name">
                    {selected.name}
                    <span>{selected.scheme}</span>
                  </span>
                  <span className="atelier-selection-copy">
                    {selected.description || 'A room with its own light.'}
                  </span>
                  <span className="atelier-tags">
                    {selected.tags.slice(0, 4).map((tag) => (
                      <span key={tag}>{tag}</span>
                    ))}
                  </span>
                </div>
                <div className="atelier-action-buttons">
                  <button type="button" className="btn ghost" onClick={() => downloadTheme(selected)}>
                    <Icon name="download" size={13} />
                    Export
                  </button>
                  <button type="button" className="btn ghost" onClick={() => void shareTheme(selected)}>
                    <Icon name="copy" size={13} />
                    Share
                  </button>
                  <button type="button" className="btn ghost" onClick={() => openStudio(selected)}>
                    <Icon name={isBuiltin(selected) ? 'copy' : 'sliders'} size={13} />
                    {isBuiltin(selected) ? 'Remix' : 'Edit'}
                  </button>
                  <button
                    type="button"
                    className="btn primary"
                    disabled={selected.id === activeId}
                    onClick={() => onApply(selected.id)}
                  >
                    <Icon name="check" size={13} />
                    {selected.id === activeId ? 'In use' : 'Use theme'}
                  </button>
                </div>
              </footer>
            ) : null}
          </>
        ) : draft ? (
          <>
            <div className="atelier-body atelier-body--studio">
              <div className="theme-studio">
                <aside className="studio-panel">
                  <div className="studio-scroll">
                    <div className="studio-kicker">
                      <span className="label">Theme studio</span>
                      <span className="studio-autosave" data-state={draftSaved ? 'saved' : 'draft'}>
                        <Icon name={draftSaved ? 'check' : 'save'} size={11} />
                        {draftSaved ? 'Autosaved' : 'Local draft'}
                      </span>
                    </div>

                    <div className="studio-switcher" aria-label="Your themes">
                      {customThemes.map((theme) => (
                        <button
                          type="button"
                          key={theme.id}
                          className="studio-chip"
                          data-active={theme.id === draft.id ? 'true' : undefined}
                          onClick={() => {
                            setDraft(theme)
                            setSelectedId(theme.id)
                            setConfirmDelete(false)
                          }}
                        >
                          <i style={{ background: theme.seeds.accent }} />
                          {theme.name}
                        </button>
                      ))}
                      <button type="button" className="studio-chip studio-chip--new" onClick={newTheme}>
                        <Icon name="plus" size={11} />
                        New
                      </button>
                    </div>

                    <div className="studio-fields">
                      <label className="studio-field">
                        <span>Name</span>
                        <input
                          id="theme-name"
                          value={draft.name}
                          maxLength={48}
                          onChange={(event) => updateDraft({ name: event.target.value })}
                        />
                      </label>
                      <label className="studio-field">
                        <span>Author</span>
                        <input
                          value={draft.author}
                          maxLength={40}
                          onChange={(event) => updateDraft({ author: event.target.value })}
                        />
                      </label>
                      <label className="studio-field">
                        <span>Description</span>
                        <textarea
                          value={draft.description}
                          rows={2}
                          maxLength={180}
                          onChange={(event) => updateDraft({ description: event.target.value })}
                          placeholder="One line about the light in this room."
                        />
                      </label>
                    </div>

                    <div className="studio-section-head">
                      <span>Palette</span>
                      <span>9 seeds</span>
                    </div>

                    <div className="seed-grid">
                      {THEME_SEED_KEYS.map((name) => (
                        <SeedField
                          key={name}
                          name={name}
                          value={draft.seeds[name]}
                          onChange={(value) => updateSeed(name, value)}
                        />
                      ))}
                    </div>

                    <details className="studio-advanced">
                      <summary>
                        Typography &amp; corners
                        <Icon name="chevron-down" size={12} />
                      </summary>
                      <div className="studio-fields studio-fields--advanced">
                        <label className="studio-field">
                          <span>UI font</span>
                          <input
                            value={draft.fonts.ui}
                            onChange={(event) => updateDraft({ fonts: { ...draft.fonts, ui: event.target.value } })}
                          />
                        </label>
                        <label className="studio-field">
                          <span>Display font</span>
                          <input
                            value={draft.fonts.display}
                            onChange={(event) => updateDraft({ fonts: { ...draft.fonts, display: event.target.value } })}
                          />
                        </label>
                        <label className="studio-field">
                          <span>Mono font</span>
                          <input
                            value={draft.fonts.mono}
                            onChange={(event) => updateDraft({ fonts: { ...draft.fonts, mono: event.target.value } })}
                          />
                        </label>
                        <label className="studio-field">
                          <span>Font stylesheet</span>
                          <input
                            value={draft.fonts.stylesheet ?? ''}
                            placeholder="https://fonts.googleapis.com/..."
                            onChange={(event) =>
                              updateDraft({
                                fonts: {
                                  ...draft.fonts,
                                  stylesheet: event.target.value.trim() || undefined,
                                },
                              })
                            }
                          />
                          <small>Optional HTTPS stylesheet for a custom typeface.</small>
                        </label>
                        <label className="studio-field studio-range">
                          <span>
                            Corner radius <b className="num">{draft.radius}px</b>
                          </span>
                          <input
                            type="range"
                            min={0}
                            max={12}
                            step={0.5}
                            value={draft.radius}
                            onChange={(event) => updateDraft({ radius: Number(event.target.value) })}
                          />
                        </label>
                      </div>
                    </details>

                    <div className="studio-contrast">
                      <div className="studio-section-head">
                        <span>Readability</span>
                        <span>WCAG AA at 4.5</span>
                      </div>
                      {contrastChecks(draft).map((check) => (
                        <div className="contrast-row" key={check.label}>
                          <span>{check.label}</span>
                          <b className="num">{formatRatio(check.ratio)}</b>
                          <span className="contrast-badge" data-pass={check.ratio >= 4.5 ? 'true' : 'false'}>
                            {check.ratio >= 4.5 ? 'Pass' : 'Low'}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                </aside>

                <div className="studio-preview">
                  <div className="studio-preview-head">
                    <span className="label">Live preview</span>
                    <span className="mono">
                      {draft.seeds.canvas} · {draft.scheme}
                    </span>
                  </div>
                  <ThemePreview theme={draft} size="large" />
                  <div className="studio-swatches">
                    {THEME_SEED_KEYS.map((name) => (
                      <span className="studio-swatch" key={name}>
                        <i style={{ background: draft.seeds[name] }} />
                        <span>{COLOR_LABELS[name]}</span>
                        <b className="num">{draft.seeds[name]}</b>
                      </span>
                    ))}
                  </div>
                  <p className="studio-note">
                    Every surface, hairline and monitor tone is derived from these nine colours. Export the JSON
                    to share the room, or{' '}
                    <a href="/themes/starter.json" download="clip-factory-theme-starter.json">
                      download a starter file
                    </a>
                    .
                  </p>
                </div>
              </div>
            </div>

            <footer className="atelier-actions">
              <div className="atelier-selection">
                <span className="atelier-selection-name">
                  {draft.name}
                  <span>{draftSaved ? 'Your theme' : 'Draft'} · {draft.scheme}</span>
                </span>
                <span className="atelier-selection-copy">
                  {draftSaved
                    ? 'Changes save in this browser as you type.'
                    : 'Edit a field or choose Use this theme to save this room.'}
                </span>
              </div>
              <div className="atelier-action-buttons">
                {confirmDelete ? (
                  <span className="studio-confirm">
                    <span>Delete this theme?</span>
                    <button type="button" className="btn ghost" onClick={() => setConfirmDelete(false)}>
                      Keep
                    </button>
                    <button type="button" className="btn danger" onClick={deleteDraft}>
                      Delete
                    </button>
                  </span>
                ) : (
                  <button type="button" className="btn ghost studio-delete" onClick={() => setConfirmDelete(true)}>
                    <Icon name="trash" size={13} />
                    Delete
                  </button>
                )}
                <button type="button" className="btn ghost" onClick={() => downloadTheme(draft)}>
                  <Icon name="download" size={13} />
                  Export
                </button>
                <button type="button" className="btn ghost" onClick={() => void shareTheme(draft)}>
                  <Icon name="copy" size={13} />
                  Share
                </button>
                <button
                  type="button"
                  className="btn primary"
                  disabled={draft.id === activeId}
                  onClick={useDraft}
                >
                  <Icon name="check" size={13} />
                  {draft.id === activeId ? 'In use' : 'Use this theme'}
                </button>
              </div>
            </footer>
          </>
        ) : null}
      </div>
    </Modal>
  )
}
