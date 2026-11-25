import { useCallback, useEffect, useRef, useState } from 'react'
import { api, formatBytes } from '../api'
import type { ModelsPayload, ModelStatus } from '../types'
import { Icon } from '../workspace/Icon'
import { Spinner } from '../workspace/ui'

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
    return (
      <div className="panel-loading">
        <Spinner label={error ?? 'Reading model manifest'} />
      </div>
    )
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
    <div className="model-list">
      <div className="model-summary">
        <span className="num">{payload.available_gb.toFixed(1)} GB</span> free right now
        <span aria-hidden="true">·</span>
        <span className="num">{formatBytes(payload.reserve_gb * 1e9)}</span> reserved
      </div>

      {payload.whisper_cli ? (
        <p className="model-path">
          whisper.cpp <code>{payload.whisper_cli}</code>
        </p>
      ) : (
        <p className="warn-line">
          <Icon name="alert" size={13} />
          whisper.cpp binary not found. Put <code>whisper-cli.exe</code> in <code>{payload.models_dir}\..\bin</code> or
          on PATH — until then transcription uses the deterministic stub.
        </p>
      )}

      {models.map((model) => {
        const row = rows[model.id]
        return (
          <article className="model-row" key={model.id}>
            <div className="model-main">
              <div className="model-title">
                <b>{model.label}</b>
                {recommended.has(model.id) ? <span className="pill ok">recommended</span> : null}
                {model.active ? <span className="pill accent">in use</span> : null}
                {!model.fits ? <span className="pill warn">needs more memory</span> : null}
              </div>
              <div className="model-meta">
                {KIND_LABEL[model.kind] ?? model.kind}
                <span aria-hidden="true">·</span>
                <span>{model.speed}</span>
                <span aria-hidden="true">·</span>
                <span className="num">{model.size_gb} GB</span>
              </div>
              {row && !row.error ? (
                <div className="model-progress">
                  <div className="meter" aria-hidden="true">
                    <i style={{ width: `${Math.round(row.pct * 100)}%` }} />
                  </div>
                  <span className="num">
                    {row.detail || 'downloading'} · {Math.round(row.pct * 100)}%
                  </span>
                </div>
              ) : null}
              {row?.error ? <span className="warn-line">{row.error}</span> : null}
            </div>
            <div className="model-action">
              {model.installed ? (
                <button
                  type="button"
                  className="btn sm ghost"
                  disabled={model.active}
                  onClick={() => void activate(model)}
                >
                  {model.active ? 'In use' : 'Use model'}
                </button>
              ) : (
                <button
                  type="button"
                  className="btn sm ghost"
                  disabled={Boolean(row && !row.error)}
                  onClick={() => void download(model)}
                >
                  <Icon name="download" size={13} />
                  {row && !row.error ? 'Downloading' : 'Download'}
                </button>
              )}
            </div>
          </article>
        )
      })}
      {error ? (
        <p className="warn-line">
          <Icon name="alert" size={13} />
          {error}
        </p>
      ) : null}
    </div>
  )
}
