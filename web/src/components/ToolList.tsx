import { useCallback, useEffect, useRef, useState } from 'react'
import { api, watchJob } from '../api'
import type { ToolStatus, ToolsPayload } from '../types'
import { Icon } from '../workspace/Icon'
import { Spinner } from '../workspace/ui'

interface RowState {
  pct: number
  detail: string
  error?: string
}

/**
 * The two programs the pipeline shells out to.
 *
 * A model is useless without something to run it, and an app that cannot cut
 * a clip without a manual unzip is not installed. Each row installs into the
 * folder the pipeline already puts first on PATH, verifies the publisher's
 * pinned hash on the way, and turns green without a restart.
 */
export function ToolList() {
  const [payload, setPayload] = useState<ToolsPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [rows, setRows] = useState<Record<string, RowState>>({})
  const timers = useRef<Array<() => void>>([])

  const load = useCallback(async () => {
    try {
      setPayload(await api.tools())
      setError(null)
    } catch (failure) {
      setError((failure as Error).message)
    }
  }, [])

  useEffect(() => {
    void load()
    return () => {
      timers.current.forEach((stop) => stop())
      timers.current = []
    }
  }, [load])

  const patch = (id: string, next: Partial<RowState>) =>
    setRows((current) => ({ ...current, [id]: { ...(current[id] ?? { pct: 0, detail: '' }), ...next } }))

  const install = async (tool: ToolStatus) => {
    patch(tool.id, { pct: 0, detail: 'starting', error: undefined })
    try {
      const started = await api.installTool(tool.id)
      const stop = watchJob(
        started.id,
        (job) => {
          patch(tool.id, { pct: job.pct, detail: job.detail || job.stage })
          if (job.status === 'done') {
            setRows((current) => {
              const next = { ...current }
              delete next[tool.id]
              return next
            })
            void load()
          } else if (job.status === 'error' || job.status === 'cancelled') {
            patch(tool.id, { error: job.error || 'install failed', pct: 0 })
          }
        },
        700,
      )
      timers.current.push(stop)
    } catch (failure) {
      patch(tool.id, { error: (failure as Error).message })
    }
  }

  if (!payload) {
    return (
      <div className="panel-loading">
        <Spinner label={error ?? 'Checking for ffmpeg and whisper.cpp'} />
      </div>
    )
  }

  return (
    <div className="tool-list">
      {!payload.automatic ? (
        <div className="model-warning">
          <Icon name="alert" size={14} />
          <div className="model-warning-copy">
            <p>
              Automatic install is Windows-only. On {payload.platform || 'this system'}, get the
              programs from their publishers, put the executables in
              <code>{payload.bin_dir}</code>, then press Re-probe.
            </p>
          </div>
        </div>
      ) : null}

      {payload.tools.map((tool) => {
        const row = rows[tool.id]
        return (
          <article className="model-row" key={tool.id}>
            <div className="model-main">
              <div className="model-title">
                <b>{tool.label}</b>
                <span className="pill">v{tool.version}</span>
                {tool.installed ? (
                  <span className="pill ok">installed</span>
                ) : (
                  <span className="pill warn">missing</span>
                )}
              </div>
              <div className="model-meta">
                <span className="num">{tool.size_mb} MB</span>
                <span aria-hidden="true">·</span>
                <span>{tool.license}</span>
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
              {tool.installed && tool.path ? (
                <p className="model-path">
                  <code>{tool.path}</code>
                </p>
              ) : null}
            </div>
            <div className="model-action">
              {tool.installed ? (
                <span className="pill ok">ready</span>
              ) : (
                <button
                  type="button"
                  className="btn sm ghost"
                  disabled={Boolean(row && !row.error)}
                  onClick={() => void install(tool)}
                >
                  <Icon name="download" size={13} />
                  {row && !row.error ? 'Installing' : 'Install'}
                </button>
              )}
            </div>
          </article>
        )
      })}

      <p className="field-hint">
        Downloaded from the publisher over HTTPS and checked against a pinned SHA-256 before
        anything is unpacked. No restart is needed.
      </p>
      {error ? (
        <p className="warn-line">
          <Icon name="alert" size={13} />
          {error}
        </p>
      ) : null}
    </div>
  )
}
