import { useEffect, useState } from 'react'
import { api } from '../api'
import type { RunnerSettings } from '../types'

const EXAMPLES = 'http://127.0.0.1:8080'

/**
 * Picking the scoring model is optional and always has been. This is the one
 * place the address lives, so the setup cards and the dialog agree.
 */
export function RunnerSetting() {
  const [settings, setSettings] = useState<RunnerSettings | null>(null)
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState<'test' | 'save' | null>(null)
  const [message, setMessage] = useState('')
  const [tone, setTone] = useState<'ok' | 'bad' | 'muted'>('muted')

  const load = () => {
    void api
      .runnerSettings()
      .then((next) => {
        setSettings(next)
        setUrl(next.url)
        if (next.url && next.reachable) {
          setTone('ok')
          setMessage(next.models.length ? `Reachable, ${next.models.length} model(s) loaded.` : 'Reachable.')
        }
      })
      .catch(() => setSettings(null))
  }

  useEffect(load, [])

  const locked = settings?.source === 'env'

  const test = () => {
    setBusy('test')
    setMessage('')
    void api
      .testRunner(url)
      .then((probe) => {
        setTone(probe.reachable ? 'ok' : 'bad')
        setMessage(
          probe.reachable
            ? probe.models.length
              ? `Reachable, ${probe.models.length} model(s) loaded.`
              : 'Reachable, but no model is loaded yet.'
            : probe.error,
        )
      })
      .catch((problem) => {
        setTone('bad')
        setMessage(String(problem))
      })
      .finally(() => setBusy(null))
  }

  const save = () => {
    setBusy('save')
    void api
      .saveRunner(url)
      .then((next) => {
        setSettings(next)
        setUrl(next.url)
        setTone(next.reachable ? 'ok' : 'muted')
        setMessage(next.url ? 'Saved. Scoring uses it on the next analysis.' : 'Cleared. Scoring uses the built-in rules.')
      })
      .catch((problem) => {
        setTone('bad')
        setMessage(String(problem))
      })
      .finally(() => setBusy(null))
  }

  return (
    <div className="runner-setting">
      <div className="runner-head">
        <div>
          <span className="label">Scoring model runner</span>
          <p className="field-hint">
            Optional. Point this at a llama-server you already run; scoring uses its model for the
            next analysis. Without it, the built-in rules rank clips.
          </p>
        </div>
        <span className="setup-pill" data-tone={settings?.reachable ? 'ok' : undefined}>
          {settings?.reachable ? 'reachable' : 'built-in'}
        </span>
      </div>

      <div className="runner-row">
        <label className="runner-field">
          <span>Address</span>
          <input
            type="url"
            value={url}
            readOnly={locked}
            spellCheck={false}
            placeholder={EXAMPLES}
            onChange={(event) => setUrl(event.target.value)}
            aria-describedby="runner-note"
          />
        </label>
        {!locked ? (
          <>
            <button type="button" className="btn sm ghost" disabled={busy !== null} onClick={test}>
              {busy === 'test' ? 'Testing…' : 'Test'}
            </button>
            <button type="button" className="btn sm primary" disabled={busy !== null} onClick={save}>
              {busy === 'save' ? 'Saving…' : 'Save'}
            </button>
          </>
        ) : null}
      </div>

      <p id="runner-note" className="runner-note" data-tone={tone}>
        {locked
          ? 'This address is set by your environment (CLIPPER_LLAMA_URL). Remove it there to change it here.'
          : message || 'Leave it empty to use the built-in rules.'}
      </p>
    </div>
  )
}
