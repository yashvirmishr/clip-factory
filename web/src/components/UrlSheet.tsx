import { useMemo, useState } from 'react'
import { formatTime } from '../api'
import type { LanguageEntry, SourcePreview } from '../types'
import { Icon } from '../workspace/Icon'
import { Modal } from '../workspace/Modal'

export interface UrlChoice {
  language: string
  subtitle_track: { lang: string; auto: boolean } | null
  prefer_captions: boolean
}

interface UrlSheetProps {
  preview: SourcePreview
  languages: LanguageEntry[]
  busy: boolean
  onCancel: () => void
  onConfirm: (choice: UrlChoice) => void
}

/**
 * What you get after pasting a URL: the video, and every way it can be
 * transcribed. Choosing a caption track is free and exact; Whisper is the
 * fallback for videos that have none.
 */
export function UrlSheet({ preview, languages, busy, onCancel, onConfirm }: UrlSheetProps) {
  const [language, setLanguage] = useState('auto')
  const [source, setSource] = useState<string>('whisper')
  const [translate, setTranslate] = useState(false)

  const chosen = useMemo(
    () => preview.tracks.find((track) => (track.auto ? 'auto:' : 'track:') + track.lang === source),
    [preview.tracks, source],
  )

  const confirm = () => {
    onConfirm({
      language,
      subtitle_track: chosen ? { lang: chosen.lang, auto: chosen.auto } : null,
      prefer_captions: Boolean(chosen),
    })
  }

  return (
    <Modal
      title={preview.title || 'That video'}
      eyebrow={preview.kind}
      onClose={onCancel}
      width={640}
      footer={
        <>
          <button type="button" className="btn ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="btn primary" onClick={confirm} disabled={busy} data-autofocus>
            <Icon name="download" size={14} />
            {busy ? 'Adding…' : 'Add this video'}
          </button>
        </>
      }
    >
      <div className="url-sheet">
        {preview.thumbnail ? (
          <img className="url-sheet-thumb" src={preview.thumbnail} alt="" loading="lazy" />
        ) : null}

        <div className="url-sheet-meta">
          <h3>{preview.title || 'Untitled'}</h3>
          <p>
            {preview.channel || 'Unknown channel'}
            {preview.duration ? ` · ${formatTime(preview.duration)}` : ''}
            {preview.live ? ' · live' : ''}
          </p>
        </div>

        <label className="field url-sheet-language">
          <span>Language spoken in the video</span>
          <select value={language} onChange={(event) => setLanguage(event.target.value)}>
            {languages.map((entry) => (
              <option key={entry.code} value={entry.code}>
                {entry.code === 'auto' ? 'Detect automatically' : `${entry.name} — ${entry.native}`}
              </option>
            ))}
          </select>
        </label>

        <fieldset className="url-sheet-sources">
          <legend>How to read the speech</legend>

          <label className="url-sheet-option" data-active={source === 'whisper' ? 'true' : undefined}>
            <input
              type="radio"
              name="transcript-source"
              value="whisper"
              checked={source === 'whisper'}
              onChange={() => setSource('whisper')}
            />
            <span>
              <b>Speech recognition</b>
              <em>Works on any video. Slower, and it has to guess at names.</em>
            </span>
          </label>

          {preview.tracks.map((track) => {
            const key = (track.auto ? 'auto:' : 'track:') + track.lang
            return (
              <label
                key={key}
                className="url-sheet-option"
                data-active={source === key ? 'true' : undefined}
              >
                <input
                  type="radio"
                  name="transcript-source"
                  value={key}
                  checked={source === key}
                  onChange={() => setSource(key)}
                />
                <span>
                  <b>
                    {track.label || track.lang}
                    {track.native && track.native !== track.label ? ` — ${track.native}` : ''}
                    {track.auto ? <i className="url-sheet-auto">AUTO</i> : null}
                  </b>
                  <em>
                    {track.auto
                      ? 'YouTube’s automatic captions. Instant, but punctuation is guesswork.'
                      : 'Uploaded captions. Exact text and timing.'}
                  </em>
                </span>
              </label>
            )
          })}

          {preview.tracks.length === 0 ? (
            <p className="url-sheet-empty">
              No caption tracks on this video, so speech recognition is the only option.
            </p>
          ) : null}
        </fieldset>

        <label className="url-sheet-check">
          <input
            type="checkbox"
            checked={translate}
            onChange={(event) => setTranslate(event.target.checked)}
          />
          <span>
            Translate to English while transcribing
            <em>Speech recognition only, and only into English.</em>
          </span>
        </label>
      </div>
    </Modal>
  )
}
