import type {
  Analysis,
  Captions,
  Clip,
  Hardware,
  JobState,
  LearnState,
  ModelsPayload,
  Peaks,
  SourceInfo,
  SourceRow,
  Verdict,
} from './types'

const BASE = '/api'

const TERMINAL = new Set(['done', 'error'])

/**
 * Poll a job to completion.
 *
 * Used for the one flow with no other place to show progress: a VOD download
 * that can run for minutes before the source exists to look at.
 */
export async function pollUntilDone(
  jobId: string,
  intervalMs = 700,
  maxWaitMs = 6 * 3600 * 1000,
): Promise<JobState> {
  const started = Date.now()
  for (;;) {
    const job = await api.job(jobId)
    if (TERMINAL.has(job.status)) return job
    if (Date.now() - started > maxWaitMs) {
      throw new Error('download is taking too long - check the job log')
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
    ...init,
  })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (body?.detail) detail = String(body.detail)
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail)
  }
  const type = response.headers.get('content-type') ?? ''
  if (type.includes('application/json')) return (await response.json()) as T
  return (await response.text()) as unknown as T
}

export const api = {
  health: () => request<{ ok: boolean; version: string; data_dir: string; busy: boolean }>('/health'),

  hardware: () => request<Hardware>('/hardware'),

  sources: () => request<SourceRow[]>('/sources'),

  ingest: (path: string, name?: string) =>
    request<SourceInfo>('/sources', {
      method: 'POST',
      body: JSON.stringify({ path, name }),
    }),

  createDemo: () => request<SourceInfo>('/demo', { method: 'POST', body: JSON.stringify({}) }),
  ingestUrl: (url: string) =>
    request<JobState>('/sources/url', {
      method: 'POST',
      body: JSON.stringify({ path: url }),
    }),

  analysis: (sourceId: string) => request<Analysis>(`/sources/${sourceId}/analysis`),

  analyze: (sourceId: string, options?: { limit?: number; force?: boolean; subtitle_path?: string }) =>
    request<JobState>(`/sources/${sourceId}/analyze`, {
      method: 'POST',
      body: JSON.stringify({ limit: 10, force: false, ...options }),
    }),

  job: (jobId: string) => request<JobState>(`/jobs/${jobId}`),

  peaks: (sourceId: string, buckets = 1400) =>
    request<Peaks>(`/sources/${sourceId}/peaks?buckets=${buckets}`),

  captions: (sourceId: string, clipId: string) =>
    request<Captions>(`/sources/${sourceId}/clips/${clipId}/captions`),

  models: () => request<ModelsPayload>('/models'),

  downloadModel: (modelId: string) =>
    request<JobState>(`/models/${modelId}/download`, { method: 'POST' }),

  activateModel: (modelId: string) =>
    request<{ ok: boolean; active: ModelsPayload['active']; warning: string | null }>(
      `/models/${modelId}/activate`,
      { method: 'POST' },
    ),

  renderPresets: () =>
    request<{ key: string; label: string; font: string; size: number; karaoke: string }[]>(
      '/render/presets',
    ),

  renderClip: (sourceId: string, clipId: string, preset: string, framing: string) =>
    request<JobState>(`/sources/${sourceId}/clips/${clipId}/render`, {
      method: 'POST',
      body: JSON.stringify({ preset, framing }),
    }),

  decide: (sourceId: string, clipId: string, action: Verdict, reason = '') =>
    request<{ ok: boolean; state: LearnState }>(`/sources/${sourceId}/clips/${clipId}/decision`, {
      method: 'POST',
      body: JSON.stringify({ action, reason }),
    }),

  setHook: (sourceId: string, clipId: string, hook: string) =>
    request<{ ok: boolean; hook: string; state: LearnState }>(
      `/sources/${sourceId}/clips/${clipId}/hook`,
      { method: 'POST', body: JSON.stringify({ hook }) },
    ),

  trimClip: (sourceId: string, clipId: string, start: number, end: number) =>
    request<Clip>(`/sources/${sourceId}/clips/${clipId}/trim`, {
      method: 'POST',
      body: JSON.stringify({ start, end }),
    }),

  framingPlan: (sourceId: string, clipId: string) =>
    request<{
      cuts: number[]
      shots: [number, number][]
      plan: {
        method: string
        crop_w: number
        knots: [number, number][]
        confidence: number
      } | null
      expression: string
    }>(`/sources/${sourceId}/clips/${clipId}/framing`),

  learn: () => request<LearnState>('/learn/state'),

  refreshProfile: () =>
    request<{ ok: boolean; state: LearnState }>('/learn/profile/refresh', {
      method: 'POST',
      body: JSON.stringify({}),
    }),

  exportDataset: () => request<string>('/learn/export'),

  mediaUrl: (sourceId: string) => `${BASE}/media/${sourceId}`,
}

export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00'
  const total = Math.floor(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${m}:${String(s).padStart(2, '0')}`
}

export function formatBytes(bytes: number): string {
  if (!bytes) return '—'
  const gb = bytes / 1e9
  return gb >= 1 ? `${gb.toFixed(2)} GB` : `${Math.round(bytes / 1e6)} MB`
}
