import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import type { CaptionPage, CaptionStyle } from '../types'
import { Icon } from '../workspace/Icon'
import { getCaptionPreset } from '../workspace/captionPreset'
import { Field, RangeField, Spinner } from '../workspace/ui'

interface Preset {
  key: string
  label: string
  font: string
  size: number
  primary: string
  secondary: string
  outline: string
  back: string
  bold: number
  outline_width: number
  shadow: number
  alignment: number
  margin_h: number
  margin_v: number
  uppercase: boolean
  karaoke: string
}

interface Draft {
  font: string
  size: number
  primary: string
  secondary: string
  outline: string
  outline_width: number
  shadow: number
  margin_v: number
  uppercase: boolean
  karaoke: string
}

interface Props {
  sourceId: string
  clipId: string
  pages: CaptionPage[]
  onNotify: (kind: 'ok' | 'error' | 'info', message: string) => void
}

/** ASS colours are ``&HAABBGGRR``; the colour input wants ``#RRGGBB``. */
function assToHex(value: string): string {
  const raw = value.replace(/^&H/i, '').padStart(8, '0').slice(-8)
  const [blue, green, red] = [raw.slice(2, 4), raw.slice(4, 6), raw.slice(6, 8)]
  return `#${red}${green}${blue}`.toLowerCase()
}

function hexToAss(value: string): string {
  const hex = value.replace('#', '').padEnd(6, '0').slice(0, 6)
  const [red, green, blue] = [hex.slice(0, 2), hex.slice(2, 4), hex.slice(4, 6)]
  return `&H00${blue}${green}${red}`.toUpperCase()
}

function draftFromPreset(preset: Preset | undefined, style: CaptionStyle | null): Draft {
  const source = style ?? preset
  return {
    font: source?.font ?? 'Arial Black',
    size: source?.size ?? 104,
    primary: assToHex(source?.primary ?? '&H001A5CFF'),
    secondary: assToHex(source?.secondary ?? '&H00FFFFFF'),
    outline: assToHex(source?.outline ?? '&H00000000'),
    outline_width: source?.outline_width ?? 8,
    shadow: source?.shadow ?? 2,
    margin_v: source?.margin_v ?? 300,
    uppercase: source?.uppercase ?? true,
    karaoke: source?.karaoke ?? 'k',
  }
}

function overridesFrom(draft: Draft, preset: Preset | undefined): Record<string, string | number | boolean> {
  if (!preset) return {}
  const base: Draft = {
    font: preset.font,
    size: preset.size,
    primary: assToHex(preset.primary),
    secondary: assToHex(preset.secondary),
    outline: assToHex(preset.outline),
    outline_width: preset.outline_width,
    shadow: preset.shadow,
    margin_v: preset.margin_v,
    uppercase: preset.uppercase,
    karaoke: preset.karaoke,
  }
  const changed: Record<string, string | number | boolean> = {}
  if (draft.font !== base.font) changed.font = draft.font
  if (draft.size !== base.size) changed.size = draft.size
  if (draft.primary !== base.primary) changed.primary = hexToAss(draft.primary)
  if (draft.secondary !== base.secondary) changed.secondary = hexToAss(draft.secondary)
  if (draft.outline !== base.outline) changed.outline = hexToAss(draft.outline)
  if (Number(draft.outline_width) !== Number(base.outline_width)) changed.outline_width = Number(draft.outline_width)
  if (Number(draft.shadow) !== Number(base.shadow)) changed.shadow = Number(draft.shadow)
  if (Number(draft.margin_v) !== Number(base.margin_v)) changed.margin_v = Number(draft.margin_v)
  if (draft.uppercase !== base.uppercase) changed.uppercase = draft.uppercase
  if (draft.karaoke !== base.karaoke) changed.karaoke = draft.karaoke
  return changed
}

const KARAOKE = [
  { value: 'k', label: 'Word pops' },
  { value: 'kf', label: 'Word sweeps' },
  { value: 'none', label: 'Static' },
]

const PREVIEW_H = 300

/**
 * Per-clip caption styling that survives into the render and the handoff.
 *
 * The preview is drawn from the same numbers the backend burns with, so a font
 * or size that looks wrong here is wrong in the MP4 - there is no second
 * styling implementation to drift from the first.
 */
export function SubtitleStudio({ sourceId, clipId, pages, onNotify }: Props) {
  const [presets, setPresets] = useState<Preset[]>([])
  const [fonts, setFonts] = useState<string[]>([])
  const [preset, setPreset] = useState(getCaptionPreset)
  const [style, setStyle] = useState<CaptionStyle | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [loading, setLoading] = useState(true)
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)
  const stamp = useRef(0)
  const notifyRef = useRef(onNotify)
  notifyRef.current = onNotify

  useEffect(() => {
    let live = true
    Promise.all([
      api.renderPresets().catch(() => []),
      api.fonts().catch(() => ({ families: [], curated: {} })),
    ]).then(([list, catalog]) => {
      if (!live) return
      setPresets(list as Preset[])
      setFonts(catalog.families)
    })
    return () => {
      live = false
    }
  }, [])

  useEffect(() => {
    const mine = ++stamp.current
    setLoading(true)
    setError(null)
    api
      .captionStyle(sourceId, clipId)
      .then((payload) => {
        if (mine !== stamp.current) return
        setStyle(payload)
        if (payload.preset) setPreset(payload.preset)
        setDraft(draftFromPreset(undefined, payload))
        setSaveState('idle')
      })
      .catch((failure) => {
        if (mine !== stamp.current) return
        setError((failure as Error).message)
        setStyle(null)
        setDraft(null)
      })
      .finally(() => {
        if (mine === stamp.current) setLoading(false)
      })
  }, [sourceId, clipId])

  const base = useMemo(() => presets.find((item) => item.key === preset), [presets, preset])
  const presetChanged = Boolean(style?.preset && style.preset !== preset)
  const dirty = useMemo(() => {
    if (!draft) return false
    return presetChanged || Object.keys(overridesFrom(draft, base)).length > 0
  }, [draft, base, presetChanged])
  const overridden = Object.keys(style?.overrides ?? {}).length > 0

  const samplePages = pages.slice(0, 2)
  const scale = PREVIEW_H / 1920

  const save = async (applyToAll = false) => {
    if (!draft) return
    const overrides = overridesFrom(draft, base)
    setSaveState('saving')
    setError(null)
    try {
      const payload = await api.saveCaptionStyle(sourceId, clipId, preset, overrides, applyToAll)
      setStyle(payload)
      setDraft(draftFromPreset(undefined, payload))
      setSaveState('saved')
      notifyRef.current(
        'ok',
        applyToAll && payload.applied
          ? `Caption style applied to ${payload.applied} clips.`
          : 'Caption style saved for this clip.',
      )
    } catch (failure) {
      setSaveState('error')
      setError((failure as Error).message)
      notifyRef.current('error', (failure as Error).message)
    }
  }

  const reset = async () => {
    setSaveState('saving')
    try {
      const payload = await api.clearCaptionStyle(sourceId, clipId)
      setStyle(payload)
      if (payload.preset) setPreset(payload.preset)
      setDraft(draftFromPreset(undefined, payload))
      setSaveState('idle')
      notifyRef.current('info', 'Back to the shipped preset.')
    } catch (failure) {
      setSaveState('error')
      notifyRef.current('error', (failure as Error).message)
    }
  }

  const pickPreset = (key: string) => {
    // Choosing a preset is a local preview until Save. The preset is saved with
    // the clip, so switching it here must not silently restyle every other clip.
    const next = presets.find((item) => item.key === key)
    setPreset(key)
    setSaveState('idle')
    if (next) setDraft(draftFromPreset(next, null))
  }

  if (loading && !draft) {
    return (
      <section className="inspector-section">
        <div className="panel-loading">
          <Spinner label="Loading caption style" />
        </div>
      </section>
    )
  }

  return (
    <section className="inspector-section" data-tour="captions">
      <header className="section-head">
        <div>
          <span className="label">Subtitle studio</span>
          <h3>Style this clip&apos;s captions</h3>
        </div>
        <span className="pill numeric">{draft?.font ?? style?.font ?? '-'}</span>
      </header>

      <div className="section-body stack-12">
        <div className="field-block">
          <span className="field-label">Preset</span>
          <div className="chip-row" role="group" aria-label="Caption preset">
            {presets.map((item) => (
              <button
                type="button"
                key={item.key}
                className="chip"
                data-on={preset === item.key}
                onClick={() => pickPreset(item.key)}
                title={`${item.font} · ${item.size}px`}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        {draft ? (
          <>
            <div className="subtitle-preview" style={{ height: PREVIEW_H }}>
              <div className="subtitle-preview-frame" aria-hidden="true" />
              <div
                className="subtitle-preview-caption"
                style={{
                  bottom: Math.max(6, draft.margin_v * scale),
                  paddingLeft: Math.max(4, 90 * scale),
                  paddingRight: Math.max(4, 90 * scale),
                  color: draft.primary,
                  fontFamily: `${draft.font}, sans-serif`,
                  fontSize: Math.max(9, draft.size * scale),
                  fontWeight: style?.bold ? 800 : 600,
                  WebkitTextStroke: `${Math.max(0, draft.outline_width * scale)}px ${draft.outline}`,
                  textShadow: `0 ${Math.max(1, draft.shadow * scale)}px 2px rgba(0,0,0,0.6)`,
                }}
              >
                {samplePages.length
                  ? samplePages.map((page) => (
                      <span key={page.index} style={{ display: 'block' }}>
                        {draft.uppercase ? page.text.toUpperCase() : page.text}
                      </span>
                    ))
                  : <span>{draft.uppercase ? 'YOUR CAPTIONS APPEAR HERE' : 'Your captions appear here'}</span>}
              </div>
              <span className="subtitle-preview-tag">9:16 preview</span>
            </div>

            <div className="subtitle-controls">
              <Field label="Font">
                <select
                  aria-label="Font"
                  value={draft.font}
                  onChange={(event) => setDraft({ ...draft, font: event.target.value })}
                >
                  {[draft.font, ...fonts.filter((family) => family !== draft.font)].map((family) => (
                    <option key={family} value={family}>
                      {family}
                    </option>
                  ))}
                </select>
              </Field>

              <Field label="Words animate">
                <select
                  aria-label="Words animate"
                  value={draft.karaoke}
                  onChange={(event) => setDraft({ ...draft, karaoke: event.target.value })}
                >
                  {KARAOKE.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </Field>

              <RangeField
                label="Size"
                value={draft.size}
                min={40}
                max={180}
                step={2}
                suffix="px"
                onChange={(size) => setDraft({ ...draft, size })}
              />

              <RangeField
                label="Height"
                value={draft.margin_v}
                min={0}
                max={900}
                step={10}
                suffix="px"
                onChange={(margin_v) => setDraft({ ...draft, margin_v })}
              />

              <RangeField
                label="Outline"
                value={draft.outline_width}
                min={0}
                max={16}
                step={0.5}
                suffix="px"
                onChange={(outline_width) => setDraft({ ...draft, outline_width })}
              />

              <Field label="Colours">
                <div className="subtitle-swatches">
                  <input
                    type="color"
                    aria-label="Spoken word colour"
                    title="Spoken word"
                    value={draft.primary}
                    onChange={(event) => setDraft({ ...draft, primary: event.target.value })}
                  />
                  <input
                    type="color"
                    aria-label="Upcoming word colour"
                    title="Upcoming word"
                    value={draft.secondary}
                    onChange={(event) => setDraft({ ...draft, secondary: event.target.value })}
                  />
                  <button
                    type="button"
                    className="chip"
                    data-on={draft.uppercase}
                    onClick={() => setDraft({ ...draft, uppercase: !draft.uppercase })}
                  >
                    UPPER
                  </button>
                </div>
              </Field>
            </div>

            <div className="subtitle-actions">
              <span className="field-hint">
                {saveState === 'saving'
                  ? 'Saving…'
                  : saveState === 'saved'
                    ? 'Saved for this clip'
                    : dirty
                      ? 'Unsaved changes'
                      : 'Matches the preset'}
              </span>
              <div className="chip-row">
                <button
                  type="button"
                  className="btn sm ghost"
                  onClick={() => void reset()}
                  disabled={saveState === 'saving' || (!dirty && !overridden)}
                >
                  Reset
                </button>
                <button
                  type="button"
                  className="btn sm ghost"
                  onClick={() => void save(true)}
                  disabled={!dirty || saveState === 'saving'}
                  title="Give every ranked clip this preset and these changes"
                >
                  Apply to all
                </button>
                <button
                  type="button"
                  className="btn sm primary"
                  onClick={() => void save()}
                  disabled={!dirty || saveState === 'saving'}
                >
                  <Icon name="save" size={13} />
                  Save style
                </button>
              </div>
            </div>
          </>
        ) : (
          <p className="panel-note">{error ?? 'Caption styling is unavailable for this clip.'}</p>
        )}

        {error && draft ? (
          <p className="warn-line">
            <Icon name="alert" size={13} />
            {error}
          </p>
        ) : null}
      </div>
    </section>
  )
}
