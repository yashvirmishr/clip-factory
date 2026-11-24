import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { ModelsPayload, ModelStatus } from '../types'

const KIND_LABEL: Record<string, string> = {
  asr: 'Transcription',
  vad: 'Voice activity',
  llm: 'Scoring',
}

interface RowState {
  jobId?: string
  pct: number
  detail: string
  error?: string
}

/**
 * Download and activate models from inside the app.
 *
 * The manifest recommends by tier, but the decision stays visible: each row says
 * what it costs, whether it fits in the memory free *right now*, and whether it
 * is already in use. A download you cannot see the progress of is a download
 * people assume has hung.
 */
export function ModelList() {
  const [payload, setPayload] = useState<ModelsPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [rows, setRows] = useState<Record<string, RowState>>({})
  const timers = useRef<number[]>([])

  const load = useCallback(async () => {
    try {
      setPayload(await api.models())
      setError(null)
    } catch (failure) {
      setError((failure as Error).message)
    }
  }, [])

  useEffect(() => {
    void load()
    return () => {
      timers.current.forEach((id) => window.clearInterval(id))
      timers.current = []
    }
  }, [load])

  const patch = (id: string, next: Partial<RowState>) =>
    setRows((current) => ({ ...current, [id]: { ...(current[id] ?? { pct: 0, detail: '' }), ...next } }))

  const watch = (modelId: string, jobId: string) => {
    const timer = window.setInterval(async () => {
      try {
        const job = await api.job(jobId)
        patch(modelId, { pct: job.pct, detail: job.detail || job.stage })
        if (job.status === 'done') {
          window.clearInterval(timer)
          setRows((current) => {
            const next = { ...current }
            delete next[modelId]
            return next
          })
          void load()
        } else if (job.status === 'error') {
          window.clearInterval(timer)
          patch(modelId, { error: job.error || 'download failed', pct: 0 })
        }
      } catch (failure) {
        window.clearInterval(timer)
        patch(modelId, { error: (failure as Error).message, pct: 0 })
      }
    }, 600)
    timers.current.push(timer)
  }

  const download = async (model: ModelStatus) => {
    patch(model.id, { pct: 0, detail: 'starting', error: undefined })
    try {
      const job = await api.downloadModel(model.id)
      patch(model.id, { jobId: job.id })
      watch(model.id, job.id)
    } catch (failure) {
      patch(model.id, { error: (failure as Error).message })
    }
  }

  const activate = async (model: ModelStatus) => {
    try {
      const result = await api.activateModel(model.id)
      if (result.warning) setError(result.warning)
      await load()
    } catch (failure) {
      setError((failure as Error).message)
    }
  }

  if (!payload) {
    return <p className="panel-note">{error ?? 'Reading model manifest…'}</p>
  }

  const recommended = new Set(
    [payload.recommended.asr, payload.recommended.llm].filter(Boolean) as string[],
  )
  const order: Record<string, number> = { asr: 0, vad: 1, llm: 2 }
  const models = [...payload.models].sort(
    (a, b) =>
      (order[a.kind] ?? 9) - (order[b.kind] ?? 9) ||
      Number(recommended.has(b.id)) - Number(recommended.has(a.id)) ||
      a.size_gb - b.size_gb,
  )

  return (
    <>
      <div className="panel-note" style={{ marginBottom: 6 }}>
        {payload.available_gb.toFixed(1)} GB free right now ({payload.reserve_gb} GB reserved for the
        OS). Models larger than 75% of that are flagged, not hidden.
      </div>
      {payload.whisper_cli ? (
        <div className="panel-note" style={{ marginBottom: 8 }}>
          whisper.cpp: <span className="mono">{payload.whisper_cli}</span>
        </div>
      ) : (
        <div className="panel-note" style={{ marginBottom: 8, color: 'var(--warn)' }}>
          whisper.cpp binary not found. Put <span className="mono">whisper-cli.exe</span> in{' '}
          <span className="mono">{payload.models_dir}\..\bin</span> or on PATH — until then
          transcription uses the deterministic stub.
        </div>
      )}
      {models.map((model) => {
        const row = rows[model.id]
        return (
          <div className="model-row" key={model.id}>
            <div style={{ minWidth: 0 }}>
              <div>
                {model.label}
                {recommended.has(model.id) ? (
                  <span className="pill" style={{ marginLeft: 6, fontSize: 9 }}>
                    recommended
                  </span>
                ) : null}
                {model.active ? (
                  <span className="pill" style={{ marginLeft: 6, fontSize: 9, color: 'var(--signal)' }}>
                    active
                  </span>
                ) : null}
              </div>
              <div className="speed">
                {KIND_LABEL[model.kind] ?? model.kind} · {model.speed}
                {!model.fits ? ' · larger than the memory free right now' : ''}
              </div>
              {row && !row.error ? (
                <div style={{ marginTop: 4 }}>
                  <div className="meter">
                    <i style={{ width: `${Math.round(row.pct * 100)}%` }} />
                  </div>
                  <span className="mono" style={{ fontSize: 9.5, color: 'var(--ink-3)' }}>
                    {row.detail || 'downloading'} · {Math.round(row.pct * 100)}%
                  </span>
                </div>
              ) : null}
              {row?.error ? <span className="warn-line">{row.error}</span> : null}
            </div>
            <div className="size">{model.size_gb} GB</div>
            <div style={{ display: 'flex', gap: 6 }}>
              {model.installed ? (
                <button
                  type="button"
                  className="btn sm"
                  disabled={model.active}
                  onClick={() => void activate(model)}
                >
                  {model.active ? 'In use' : 'Use'}
                </button>
              ) : (
                <button
                  type="button"
                  className="btn sm"
                  disabled={Boolean(row && !row.error)}
                  onClick={() => void download(model)}
                >
                  {row && !row.error ? 'Downloading' : 'Download'}
                </button>
              )}
            </div>
          </div>
        )
      })}
      {error ? <p className="warn-line">{error}</p> : null}
    </>
  )
}
