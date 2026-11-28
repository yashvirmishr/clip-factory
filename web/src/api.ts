import type {
  AccountPost,
  Analysis,
  Captions,
  CaptionStyle,
  ChatStatus,
  Clip,
  Diagnostics,
  FontCatalog,
  FramingStatus,
  Hardware,
  JobState,
  LearnState,
  ModelsPayload,
  Peaks,
  PersonalState,
  Readiness,
  RunnerProbe,
  RunnerSettings,
  SourceInfo,
  SourcePreview,
  SourceRow,
  Suggestion,
  ToolsPayload,
  SuggestionPreview,
  WeeklyState,
  LanguageEntry,
  TracksPayload,
  Verdict,
} from './types'

const BASE = '/api'

/** The loopback callback on whichever origin serves this page. */
export function callbackUrl(): string {
  return `${window.location.origin}/api/connections/callback`
}

const TERMINAL = new Set(['done', 'error', 'cancelled'])

// Caption pages are the biggest per-clip payload and the reel is browsed clip by
// clip, so the last handful are kept. A trim or a re-analysis forgets them; a
// stale page set is how captions and video silently drift apart.
const CAPTION_CACHE_LIMIT = 24
const captionCache = new Map<string, Captions>()
// Bumped by every invalidation. A read that was already in flight when the
// words changed must not write its old pages back into the cache afterwards.
let captionGeneration = 0

function captionKey(sourceId: string, clipId: string): string {
  return `${sourceId}:${clipId}`
}

/** Drop cached caption pages for one clip, or for every clip of a source. */
export function forgetCaptions(sourceId: string, clipId?: string): void {
  captionGeneration += 1
  if (clipId) {
    captionCache.delete(captionKey(sourceId, clipId))
    return
  }
  for (const key of Array.from(captionCache.keys())) {
    if (key.startsWith(`${sourceId}:`)) captionCache.delete(key)
  }
}

/**
 * Wait for a job to finish.
 *
 * Used for the one flow with no panel to show progress in: a VOD download that
 * can run for minutes before the source exists to look at. It rides the same
 * stream as everything else rather than re-implementing the wait loop.
 */
export function pollUntilDone(
  jobId: string,
  intervalMs = 700,
  maxWaitMs = 6 * 3600 * 1000,
): Promise<JobState> {
  return new Promise((resolve, reject) => {
    let stop: (() => void) | null = null
    const timeout = setTimeout(() => {
      stop?.()
      reject(new Error('download is taking too long - check the job log'))
    }, maxWaitMs)
    stop = watchJob(
      jobId,
      (job) => {
        // Every frame arrives here, including "queued". Resolving on the first
        // one hands the caller a job that has not failed yet - which is how a
        // dead download used to report "Added the video".
        if (!TERMINAL.has(job.status)) return
        clearTimeout(timeout)
        stop?.()
        resolve(job)
      },
      intervalMs,
    )
  })
}

/**
 * Follow a job until it finishes, without polling.
 *
 * The backend streams one frame per change over SSE and closes after the last
 * one. Polling stays as the fallback for an environment without EventSource and
 * for a stream that keeps failing, so a browser quirk cannot strand a render.
 * Returns a stop function; calling it is idempotent.
 */
export function watchJob(
  jobId: string,
  onJob: (job: JobState) => void,
  pollMs = 900,
): () => void {
  let stopped = false
  let source: EventSource | null = null
  let timer: number | null = null
  let failures = 0

  const stop = () => {
    if (stopped) return
    stopped = true
    source?.close()
    source = null
    if (timer !== null) window.clearInterval(timer)
    timer = null
  }

  const deliver = (job: JobState) => {
    if (stopped) return
    onJob(job)
    if (TERMINAL.has(job.status)) stop()
  }

  const poll = async () => {
    let job: JobState
    try {
      job = await api.job(jobId)
    } catch {
      // A transient read failure is not a failed job; the next tick retries.
      return
    }
    deliver(job)
  }

  const startPolling = () => {
    if (stopped || timer !== null) return
    void poll()
    timer = window.setInterval(() => void poll(), pollMs)
  }

  function connect() {
    if (stopped) return
    if (typeof EventSource === 'undefined') {
      startPolling()
      return
    }
    try {
      source = new EventSource(`${BASE}/jobs/${jobId}/events`)
    } catch {
      startPolling()
      return
    }
    source.onmessage = (event) => {
      failures = 0
      let job: JobState
      try {
        job = JSON.parse(event.data) as JobState
      } catch {
        return
      }
      deliver(job)
    }
    // The browser reconnects a dropped stream on its own, so a failed
    // connection is only counted here. Three in a row means it is not coming
    // back: closing the source stops the reconnects and polling takes over.
    source.onerror = () => {
      if (stopped || !source) return
      failures += 1
      if (failures < 3) return
      source.close()
      source = null
      startPolling()
    }
  }

  connect()
  return stop
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
      const payload = body?.detail
      if (typeof payload === 'string') detail = payload
      else if (payload && typeof payload === 'object') {
        const issues = Array.isArray(payload.issues)
          ? payload.issues.map((issue: { remedy?: string; message?: string }) => issue.remedy || issue.message || '').filter(Boolean)
          : []
        detail = [payload.message || 'The request was rejected.', ...issues].join(' ')
      }
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
  ingestUrl: (
    url: string,
    options?: {
      language?: string
      subtitle_track?: { lang: string; auto: boolean } | null
      prefer_captions?: boolean
    },
  ) =>
    request<JobState>('/sources/url', {
      method: 'POST',
      body: JSON.stringify({ path: url, ...(options ?? {}) }),
    }),

  previewSource: (url: string) =>
    request<SourcePreview>('/sources/preview', {
      method: 'POST',
      body: JSON.stringify({ url }),
    }),

  tracks: (sourceId: string) => request<TracksPayload>(`/sources/${sourceId}/tracks`),

  importSubtitles: (sourceId: string, lang: string, auto: boolean) =>
    request<JobState>(`/sources/${sourceId}/subtitles`, {
      method: 'POST',
      body: JSON.stringify({ lang, auto }),
    }),

  languages: () => request<LanguageEntry[]>('/languages'),

  analysis: (sourceId: string) => request<Analysis>(`/sources/${sourceId}/analysis`),

  analyze: (sourceId: string, options?: { limit?: number; force?: boolean; subtitle_path?: string }) => {
    // A new analysis replaces words, so every page set for this source is stale.
    forgetCaptions(sourceId)
    return request<JobState>(`/sources/${sourceId}/analyze`, {
      method: 'POST',
      body: JSON.stringify({ limit: 10, force: false, ...options }),
    })
  },

  chatStatus: (sourceId: string) => request<ChatStatus>(`/sources/${sourceId}/chat`),

  fetchChat: (sourceId: string) =>
    request<JobState>(`/sources/${sourceId}/chat/fetch`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),

  job: (jobId: string) => request<JobState>(`/jobs/${jobId}`),

  cancelJob: (jobId: string) =>
    request<JobState>(`/jobs/${jobId}/cancel`, { method: 'POST' }),

  peaks: (sourceId: string, buckets = 1400) =>
    request<Peaks>(`/sources/${sourceId}/peaks?buckets=${buckets}`),

  captions: async (sourceId: string, clipId: string) => {
    const key = captionKey(sourceId, clipId)
    const cached = captionCache.get(key)
    if (cached) return cached
    const generation = captionGeneration
    const payload = await request<Captions>(`/sources/${sourceId}/clips/${clipId}/captions`)
    // Invalidated while the read was out: hand these pages to the caller but do
    // not keep them, or the next clip switch would show the pre-trim words.
    if (generation === captionGeneration) {
      if (captionCache.size >= CAPTION_CACHE_LIMIT) {
        const oldest = captionCache.keys().next().value
        if (oldest) captionCache.delete(oldest)
      }
      captionCache.set(key, payload)
    }
    return payload
  },

  models: () => request<ModelsPayload>('/models'),

  tools: () => request<ToolsPayload>('/tools'),

  installTool: (toolId: string) =>
    request<JobState>(`/tools/${toolId}/install`, { method: 'POST' }),

  readiness: () => request<Readiness>('/readiness'),

  runnerSettings: () => request<RunnerSettings>('/settings/llm'),

  saveRunner: (url: string) =>
    request<RunnerSettings>('/settings/llm', { method: 'POST', body: JSON.stringify({ url }) }),

  testRunner: (url: string) =>
    request<RunnerProbe>('/settings/llm/test', { method: 'POST', body: JSON.stringify({ url }) }),

  diagnostics: () => request<Diagnostics>('/diagnostics'),

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

  fonts: () => request<FontCatalog>('/fonts'),

  framingStatus: () => request<FramingStatus>('/framing/status'),

  captionStyle: (sourceId: string, clipId: string, preset?: string) =>
    request<CaptionStyle>(
      `/sources/${sourceId}/clips/${clipId}/captions/style${
        preset ? `?preset=${encodeURIComponent(preset)}` : ''
      }`,
    ),

  saveCaptionStyle: (
    sourceId: string,
    clipId: string,
    preset: string,
    overrides: Record<string, string | number | boolean>,
    applyToAll = false,
  ) =>
    request<CaptionStyle>(`/sources/${sourceId}/clips/${clipId}/captions/style`, {
      method: 'PUT',
      body: JSON.stringify({ preset, overrides, apply_to_all: applyToAll }),
    }),

  clearCaptionStyle: (sourceId: string, clipId: string, preset?: string) =>
    request<CaptionStyle>(
      `/sources/${sourceId}/clips/${clipId}/captions/style${
        preset ? `?preset=${encodeURIComponent(preset)}` : ''
      }`,
      { method: 'DELETE' },
    ),

  renderClip: (sourceId: string, clipId: string, preset: string, framing: string, force = false) =>
    request<JobState>(`/sources/${sourceId}/clips/${clipId}/render`, {
      method: 'POST',
      body: JSON.stringify({ preset, framing, force }),
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

  trimClip: async (sourceId: string, clipId: string, start: number, end: number) => {
    const clip = await request<Clip>(`/sources/${sourceId}/clips/${clipId}/trim`, {
      method: 'POST',
      body: JSON.stringify({ start, end }),
    })
    // Trimming re-cuts the words, so the pages that were cached are wrong now.
    forgetCaptions(sourceId, clipId)
    return clip
  },

  bakeReel: (sourceId: string, preset: string, framing: string, approvedOnly: boolean) =>
    request<JobState>(`/sources/${sourceId}/export/bake`, {
      method: 'POST',
      body: JSON.stringify({ preset, framing, approved_only: approvedOnly }),
    }),

  lastBake: (sourceId: string) =>
    request<{
      folder: string
      exists: boolean
      clip_count?: number
      baked?: number
      failed?: number
      clips?: Array<{ id: string; name: string; file?: string; error?: string }>
    }>(`/sources/${sourceId}/export/bake`),

  revealFolder: (path: string) =>
    request<{ ok: boolean; path: string }>('/reveal', {
      method: 'POST',
      body: JSON.stringify({ path }),
    }),

  bakeFileUrl: (sourceId: string, file: string) =>
    `${BASE}/sources/${sourceId}/export/bake/file/${encodeURIComponent(file)}`,

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

  accounts: () =>
    request<{
      accounts: Array<{
        id: string
        platform: string
        handle?: string
        display_name?: string
        external_id?: string
      }>
      platforms: Array<{
        platform: string
        label: string
        min_duration_s: number
        max_duration_s: number
        max_bytes: number
        caption_limit: number
        title_limit: number
        max_hashtags: number
        aspect: string
        connected: number
        adapter: boolean
      }>
      secret_store: { available?: boolean; backend?: string; detail?: string }
    }>('/accounts'),

  connectAccount: (platform: string, clientId: string, clientSecret: string, redirectUri = '') =>
    request<{ platform: string; url: string; state: string; redirect_uri: string; manual_callback: boolean }>(
      `/accounts/${platform}/connect`,
      {
        method: 'POST',
        body: JSON.stringify({ client_id: clientId, client_secret: clientSecret, redirect_uri: redirectUri }),
      },
    ),

  disconnectAccount: (accountId: string) =>
    request<{ ok: boolean }>(`/accounts/${accountId}`, { method: 'DELETE' }),

  syncAccount: (accountId: string) =>
    request<Record<string, unknown>>(`/accounts/${accountId}/sync`, { method: 'POST' }),

  accountOverview: (accountId: string) =>
    request<Record<string, unknown>>(`/accounts/${accountId}/overview`),

  accountPosts: (accountId: string, limit = 100) =>
    request<{ posts: AccountPost[]; baseline: Record<string, unknown> }>(
      `/accounts/${accountId}/posts?limit=${limit}`,
    ),

  personalState: (accountId = '') =>
    request<PersonalState>(`/learn/personal${accountId ? `?account_id=${encodeURIComponent(accountId)}` : ''}`),

  trainPersonal: (accountId = '') =>
    request<Record<string, unknown>>(
      `/learn/personal/train${accountId ? `?account_id=${encodeURIComponent(accountId)}` : ''}`,
      { method: 'POST' },
    ),

  activatePersonal: (version: string) =>
    request<Record<string, unknown>>(`/learn/personal/${encodeURIComponent(version)}/activate`, {
      method: 'POST',
    }),

  rollbackPersonal: () =>
    request<PersonalState>('/learn/personal/rollback', { method: 'POST' }),

  weeklyStatus: () => request<WeeklyState>('/learning/weekly'),

  runWeekly: () => request<WeeklyState>('/learning/weekly/run', { method: 'POST' }),

  suggestions: (sourceId: string, clipId: string) =>
    request<{ suggestions: Suggestion[] }>(`/sources/${sourceId}/clips/${clipId}/suggestions`),

  previewSuggestion: (sourceId: string, clipId: string, suggestionId: string) =>
    request<{ suggestion: Suggestion; preview: SuggestionPreview }>(
      `/sources/${sourceId}/clips/${clipId}/suggestions/${suggestionId}/preview`,
      { method: 'POST' },
    ),

  applySuggestion: (sourceId: string, clipId: string, suggestionId: string) =>
    request<{ suggestion: Suggestion; candidate: Clip | null; changed: boolean }>(
      `/sources/${sourceId}/clips/${clipId}/suggestions/${suggestionId}/apply`,
      { method: 'POST' },
    ),

  undoSuggestion: (sourceId: string, clipId: string, suggestionId: string) =>
    request<{ suggestion: Suggestion; candidate: Clip | null }>(
      `/sources/${sourceId}/clips/${clipId}/suggestions/${suggestionId}/undo`,
      { method: 'POST' },
    ),

  dismissSuggestion: (sourceId: string, clipId: string, suggestionId: string) =>
    request<Suggestion>(`/sources/${sourceId}/clips/${clipId}/suggestions/${suggestionId}/dismiss`, {
      method: 'POST',
    }),

  validatePublish: (body: {
    platform: string
    media_path: string
    title: string
    caption: string
    hashtags: string[]
    visibility: string
    made_for_kids: boolean
  }) =>
    request<{
      ok: boolean
      issues: Array<{ field: string; code: string; severity: string; message: string; remedy: string }>
      limits: Record<string, unknown> | null
    }>('/publish/validate', { method: 'POST', body: JSON.stringify(body) }),

  publishJobs: (limit = 8) =>
    request<{ jobs: Array<Record<string, unknown>> }>(`/publish/jobs?limit=${limit}`),

  publish: (body: {
    platform: string
    account_id: string
    media_path: string
    title: string
    caption: string
    hashtags: string[]
    visibility: string
    made_for_kids: boolean
    source_id: string
    clip_id: string
    scheduled_at?: number
  }) => request<Record<string, unknown>>('/publish', { method: 'POST', body: JSON.stringify(body) }),

  retryPublish: (jobId: string) =>
    request<Record<string, unknown>>(`/publish/jobs/${jobId}/retry`, { method: 'POST' }),

  learn: () => request<LearnState>('/learn/state'),

  refreshProfile: () =>
    request<{ ok: boolean; state: LearnState }>('/learn/profile/refresh', {
      method: 'POST',
      body: JSON.stringify({}),
    }),

  exportDataset: () => request<string>('/learn/export'),

  mediaUrl: (sourceId: string, proxy = false) =>
    `${BASE}/media/${sourceId}${proxy ? '?proxy=1' : ''}`,
  thumbUrl: (sourceId: string, t: number, w = 320) =>
    `${BASE}/sources/${sourceId}/thumb?t=${t.toFixed(2)}&w=${w}`,
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

export function formatTimecode(seconds: number, fps = 30): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '00:00:00:00'
  // Use a nominal integer rate. These clips are short, so non-drop timecode is
  // exact enough; 29.97 must not produce fractional frame numbers.
  const rate = Math.max(1, Math.round(fps))
  const totalFrames = Math.round(seconds * rate)
  const frames = totalFrames % rate
  const whole = Math.floor(totalFrames / rate)
  const h = Math.floor(whole / 3600)
  const m = Math.floor((whole % 3600) / 60)
  const s = whole % 60
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${pad(h)}:${pad(m)}:${pad(s)}:${pad(frames)}`
}

export function formatBytes(bytes: number): string {
  if (!bytes) return '—'
  const gb = bytes / 1e9
  return gb >= 1 ? `${gb.toFixed(2)} GB` : `${Math.round(bytes / 1e6)} MB`
}
