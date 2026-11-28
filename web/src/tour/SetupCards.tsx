import { useEffect, useState } from 'react'
import { api, watchJob } from '../api'
import type { JobState, Readiness } from '../types'

interface Props {
  variant: 'welcome' | 'readiness'
  readiness: Readiness | null
  error: string | null
  onRefresh: () => void
  onOpenSetup: () => void
}

function megabytes(gb: number): string {
  if (!gb) return ''
  const mb = Math.round(gb * 1000)
  return mb >= 1000 ? `${(mb / 1000).toFixed(1)} GB` : `${mb} MB`
}

function copyPath(path: string): Promise<boolean> {
  if (window.clipFactory?.copyText) return window.clipFactory.copyText(path)
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard
      .writeText(path)
      .then(() => true)
      .catch(() => false)
  }
  return Promise.resolve(false)
}

/**
 * The two setup screens. They read one readiness snapshot rather than probing
 * the machine themselves, and nothing here blocks: every row is a statement
 * about right now, and Continue works whether or not the row is green.
 */
export function SetupCards({ variant, readiness, error, onRefresh, onOpenSetup }: Props) {
  const [fixing, setFixing] = useState(false)
  const [job, setJob] = useState<JobState | null>(null)
  const [copied, setCopied] = useState(false)
  const [downloadingId, setDownloadingId] = useState<string | null>(null)
  const [toolJob, setToolJob] = useState<JobState | null>(null)
  const [toolId, setToolId] = useState<string | null>(null)
  const [toolKind, setToolKind] = useState<string | null>(null)
  const [toolError, setToolError] = useState<{ id: string; message: string } | null>(null)

  // A download is the only long action on this screen. Follow the job until it
  // settles, then re-read readiness so the row turns green on its own.
  useEffect(() => {
    if (!downloadingId) return
    return watchJob(
      downloadingId,
      (next) => {
        setJob(next)
        if (next.status === 'done') {
          setDownloadingId(null)
          setJob(null)
          onRefresh()
        } else if (next.status === 'error' || next.status === 'cancelled') {
          setDownloadingId(null)
        }
      },
      700,
    )
  }, [downloadingId, onRefresh])

  // Installing a program follows the same shape, but it is a separate job: a
  // model download and an ffmpeg download can be retried independently.
  useEffect(() => {
    if (!toolId) return
    return watchJob(
      toolId,
      (next) => {
        setToolJob(next)
        if (next.status === 'done') {
          setToolId(null)
          setToolJob(null)
          setToolKind(null)
          onRefresh()
        } else if (next.status === 'error' || next.status === 'cancelled') {
          setToolId(null)
          setToolKind(null)
          setToolError({
            id: toolId,
            message: next.error || 'The install stopped before it finished.',
          })
        }
      },
      700,
    )
  }, [toolId, onRefresh])

  const installTool = async (id: string) => {
    setToolError(null)
    setToolKind(id)
    try {
      const started = await api.installTool(id)
      setToolJob(started)
      setToolId(started.id)
    } catch (problem) {
      setToolKind(null)
      setToolError({ id, message: (problem as Error).message })
    }
  }

  if (variant === 'welcome') {
    return (
      <div className="tour-welcome">
        <p className="tour-lede">
          It finds the moments worth posting, cuts them into vertical clips with captions, and you
          decide what keeps. Everything runs on this computer: nothing is uploaded and there is no
          account.
        </p>
        <p className="tour-meta">About four minutes &nbsp;·&nbsp; stop and resume any time</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="tour-readiness">
        <p className="tour-error">The app's background service is not answering: {error}</p>
        <button type="button" className="btn sm ghost" onClick={onRefresh}>
          Check again
        </button>
      </div>
    )
  }

  if (!readiness) {
    return (
      <div className="tour-readiness" aria-live="polite">
        <p className="tour-meta">Checking this computer…</p>
      </div>
    )
  }

  const { machine, video, speech, scoring, tools } = readiness
  const runner = scoring.runner
  const recommended = speech.recommended
  const speechReady = speech.ready
  const ffmpeg = video.ffmpeg
  const running = job && (job.status === 'running' || job.status === 'queued')
  const toolBusy = Boolean(
    toolId && toolJob && (toolJob.status === 'running' || toolJob.status === 'queued'),
  )
  const whisperTool = tools?.tools.find((tool) => tool.id === 'whisper')

  return (
    <div className="tour-readiness">
      <div className="setup-rows" role="list">
        <div className="setup-row" data-tone={ffmpeg ? 'ok' : 'bad'} role="listitem">
          <span className="setup-dot" aria-hidden="true">
            {ffmpeg ? '✓' : '!'}
          </span>
          <div className="setup-row-copy">
            <div className="setup-row-title">
              Video tools
              <span className="setup-pill">{ffmpeg ? 'ready' : 'missing'}</span>
            </div>
            <p>
              {ffmpeg
                ? 'ffmpeg found. Cutting, captions and rendering will work.'
                : 'ffmpeg is not installed. Nothing can be cut or rendered until it is.'}
            </p>
            {!ffmpeg && toolError?.id === 'ffmpeg' ? (
              <p className="setup-progress" data-tone="bad">
                {toolError.message}
              </p>
            ) : null}
          </div>
          {!ffmpeg ? (
            tools?.automatic ? (
              <button
                type="button"
                className="setup-fix"
                disabled={toolBusy && toolKind === 'ffmpeg'}
                onClick={() => void installTool('ffmpeg')}
              >
                {toolBusy && toolKind === 'ffmpeg' ? 'Installing…' : 'Install'}
              </button>
            ) : (
              <button type="button" className="setup-fix" onClick={onRefresh}>
                Check again
              </button>
            )
          ) : null}
        </div>

        <div className="setup-row" data-tone={speechReady ? 'ok' : 'warn'} role="listitem">
          <span className="setup-dot" aria-hidden="true">
            {speechReady ? '✓' : '!'}
          </span>
          <div className="setup-row-copy">
            <div className="setup-row-title">
              Reading speech
              <span className="setup-pill">
                {speechReady
                  ? 'ready'
                  : speech.whisper_cli
                    ? 'needs a model'
                    : speech.model
                      ? 'needs the speech program'
                      : 'needs setting up'}
              </span>
            </div>
            <p>
              {speechReady
                ? speech.model
                  ? `${speech.model} is installed and in use.`
                  : 'A speech model is installed and in use.'
                : 'Clips still work, but from a stand-in transcript rather than the real words.'}
            </p>
          </div>
          {!speechReady && !fixing ? (
            <button type="button" className="setup-fix" onClick={() => setFixing(true)}>
              Fix this ›
            </button>
          ) : null}
        </div>

        <div className="setup-row" data-tone="ok" role="listitem">
          <span className="setup-dot" aria-hidden="true">
            ✓
          </span>
          <div className="setup-row-copy">
            <div className="setup-row-title">
              Judging clips
              <span className="setup-pill">{runner.reachable ? 'your runner' : 'built-in'}</span>
            </div>
            <p>
              {runner.reachable
                ? `Talking to your model runner at ${runner.url}. `
                : 'Ranks moments with the built-in rules. A local model is optional, not required.'}
            </p>
          </div>
          <button type="button" className="setup-fix" onClick={onOpenSetup}>
            Change
          </button>
        </div>
      </div>

      <p className="setup-machine">
        <span>{machine.memory_gb} GB memory</span>
        <span aria-hidden="true">·</span>
        <span>{machine.gpu ? machine.gpu : 'no graphics card'}</span>
        <span aria-hidden="true">·</span>
        <span>{machine.os}</span>
      </p>
      <p className="setup-note">{machine.note}</p>

      {fixing && !speechReady ? (
        <div className="setup-speech">
          <div className="setup-speech-head">
            <div>
              <h4>Give it a way to read speech.</h4>
              <p>
                Two things are needed: a speech model, and the small program that runs it. The
                model downloads here. The program is one file you place once.
              </p>
            </div>
            <button type="button" className="btn sm ghost" onClick={() => setFixing(false)}>
              Not now
            </button>
          </div>

          {recommended ? (
            <div className="setup-model" data-busy={running ? 'true' : undefined}>
              <div className="setup-model-copy">
                <div className="setup-model-name">
                  {recommended.label}
                  <span className="setup-pill">recommended</span>
                </div>
                <p>
                  {megabytes(recommended.size_gb)}
                  {recommended.speed ? ` · ${recommended.speed}` : ''}
                </p>
                {running ? (
                  <>
                    <div className="meter" aria-hidden="true">
                      <i style={{ width: `${Math.round((job?.pct ?? 0) * 100)}%` }} />
                    </div>
                    <p className="setup-progress" aria-live="polite">
                      {Math.round((job?.pct ?? 0) * 100)}% downloaded
                    </p>
                  </>
                ) : job?.status === 'error' ? (
                  <p className="setup-progress" data-tone="bad">
                    The download stopped. Press Download to resume where it left off.
                  </p>
                ) : null}
              </div>
              {running ? (
                <button
                  type="button"
                  className="btn sm ghost"
                  onClick={() => {
                    if (downloadingId) void api.cancelJob(downloadingId)
                  }}
                >
                  Cancel
                </button>
              ) : (
                <button
                  type="button"
                  className="btn sm primary"
                  onClick={() => {
                    void (async () => {
                      try {
                        const started = await api.downloadModel(recommended.id)
                        setJob(started)
                        setDownloadingId(started.id)
                      } catch (problem) {
                        setJob({
                          id: 'local',
                          status: 'error',
                          stage: 'download',
                          pct: 0,
                          detail: '',
                          error: String(problem),
                        } as JobState)
                      }
                    })()
                  }}
                >
                  Download
                </button>
              )}
            </div>
          ) : null}

          {speech.whisper_cli ? null : (
            <div className="setup-runner">
              <div className="setup-runner-head">
                <span className="tour-eyebrow">Still missing: the speech program</span>
              </div>
              {tools?.automatic ? (
                <>
                  <p className="setup-small">
                    The Windows build of whisper.cpp
                    {whisperTool ? ` (${whisperTool.size_mb} MB)` : ''} goes into the folder the
                    app already checks, after its pinned hash is verified.
                  </p>
                  <div className="setup-path-actions">
                    <button
                      type="button"
                      className="btn sm primary"
                      disabled={toolBusy && toolKind === 'whisper'}
                      onClick={() => void installTool('whisper')}
                    >
                      {toolBusy && toolKind === 'whisper'
                        ? 'Installing…'
                        : 'Install whisper.cpp'}
                    </button>
                    <button type="button" className="btn sm ghost" onClick={onRefresh}>
                      Check again
                    </button>
                  </div>
                  {toolBusy && toolKind === 'whisper' && toolJob ? (
                    <>
                      <div className="meter" aria-hidden="true">
                        <i style={{ width: `${Math.round((toolJob.pct ?? 0) * 100)}%` }} />
                      </div>
                      <p className="setup-progress" aria-live="polite">
                        {toolJob.detail || 'downloading'} ·
                        {Math.round((toolJob.pct ?? 0) * 100)}%
                      </p>
                    </>
                  ) : null}
                  {toolError?.id === 'whisper' ? (
                    <p className="setup-progress" data-tone="bad">
                      {toolError.message}
                    </p>
                  ) : null}
                  <p className="setup-small">
                    Already have your own build? Put <b>whisper-cli.exe</b> in{' '}
                    <code>{speech.bin_dir}</code> and press Check again.
                  </p>
                </>
              ) : (
                <>
                  <p className="setup-small">
                    Download whisper.cpp once and put <b>whisper-cli.exe</b> in this folder:
                  </p>
                  <code className="setup-path">{speech.bin_dir}</code>
                  <div className="setup-path-actions">
                    <button
                      type="button"
                      className="btn sm ghost"
                      onClick={() => {
                        void copyPath(speech.bin_dir).then((ok) => {
                          setCopied(ok)
                          window.setTimeout(() => setCopied(false), 1600)
                        })
                      }}
                    >
                      {copied ? 'Copied' : 'Copy path'}
                    </button>
                    {window.clipFactory?.openPath ? (
                      <button
                        type="button"
                        className="btn sm ghost"
                        onClick={() => void window.clipFactory?.openPath(speech.bin_dir ?? '')}
                      >
                        Open folder
                      </button>
                    ) : null}
                    <button type="button" className="btn sm ghost" onClick={onRefresh}>
                      Check again
                    </button>
                  </div>
                </>
                )}
            </div>
          )}

          <p className="setup-small">
            Rather not download anything? Open a video that already has .srt or .vtt subtitles and
            it will read those words instead.
          </p>
        </div>
      ) : null}
    </div>
  )
}
