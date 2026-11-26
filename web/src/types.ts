export interface Word {
  text: string
  start: number
  end: number
  prob: number
  refined: boolean
}

export interface GateResult {
  id: string
  /** Plain-language name from the backend; falls back to the id if absent. */
  label?: string
  passed: boolean
  severity: 'block' | 'warn'
  detail: string
}

export interface ScoreItem {
  id: string
  label: string
  passed: boolean
  detail: string
}

export interface LLMJudgement {
  score: number
  hook: string
  title: string
  reason: string
  understands_standalone: boolean
  has_payoff: boolean
  provider: string
}

export interface WindowFeatures {
  duration: number
  word_count: number
  words_per_sec: number
  question_count: number
  exclaim_count: number
  second_person: number
  number_count: number
  hook_lexicon_hits: number
  profanity: number
  caps_ratio: number
  mean_word_prob: number
  low_conf_ratio: number
  speech_coverage: number
  start_in_stream: number
  end_in_stream: number
}

export interface Clip {
  id: string
  source_id: string
  start: number
  end: number
  text: string
  /** Absent on `shape=reel` payloads; fetch the clip for word timings. */
  words?: Word[]
  signals: Record<string, number>
  features: WindowFeatures | null
  fused: number
  llm: LLMJudgement | null
  final: number
  gates: GateResult[]
  scorecard: ScoreItem[]
  rank: number | null
  blocked: boolean
}

export interface SourceInfo {
  id: string
  name: string
  path: string
  duration: number
  width: number
  height: number
  fps: number
  has_audio: boolean
  size_bytes: number
  origin_url: string
}

export interface ChatStatus {
  messages: number
  first: number
  last: number
  coverage: number
  available: boolean
  origin_url: string
  twitch_vod: string
}

export interface SourceRow extends SourceInfo {
  analyzed: boolean
  clip_count: number
  reel_quality: number
}

export interface Analysis {
  source: SourceInfo
  candidates: Clip[]
  asr_backend: string
  llm_backend: string
  duration_s: number
  reel_quality: number
  warnings: string[]
}

export interface JobState {
  id: string
  kind: string
  status: 'queued' | 'running' | 'done' | 'error' | 'cancelled'
  stage: string
  pct: number
  detail: string
  error: string
  elapsed: number
  cancelling?: boolean
  /** Timings and counts of a finished analysis; the reel is fetched separately. */
  analysis_ready?: boolean
  source_id?: string
  clip_count?: number
  reel_quality?: number
  timings?: Record<string, number>
  analysis?: Analysis
}

export interface LanguageEntry {
  code: string
  name: string
  native: string
  script: string
  rtl: boolean
}

export interface CaptionTrack {
  lang: string
  label: string
  native?: string
  auto: boolean
  ext: string
}

export interface SourcePreview {
  url: string
  kind: string
  title: string
  channel: string
  duration: number
  thumbnail: string
  live: boolean
  tracks: CaptionTrack[]
  error?: string
}

export interface TracksPayload {
  preview: SourcePreview | null
  stored: Array<{ language: string; path: string; cues: number; bytes: number }>
  asr: { model: string; english_only: boolean; language: string; available: boolean }
}

export interface Peaks {
  duration: number
  low: number[]
  high: number[]
  buckets: number
}

export interface LearnState {
  decisions: number
  labels: { approve: number; reject: number }
  learning_threshold: number
  progress_to_ranker: number
  ranker_active: boolean
  ranker_holdout_auc: number | null
  ranker_samples: number
  ranker_history: { at: number; auc: number; baseline_auc: number; n: number }[]
  ranker_meta: Record<string, unknown>
  hook_edits: number
  hook_edits_needed: number
  style_profile: string
  style_ready: boolean
  quality: {
    decisions: number
    approvals: number
    rejections: number
    approval_rate: number
    reject_reasons: Record<string, number>
  }
  features: string[]
}

export interface CaptionWord {
  text: string
  start: number
  end: number
}

export interface CaptionPage {
  index: number
  start: number
  end: number
  words: CaptionWord[]
  lines: string[]
  text: string
  cps: number
  warnings: string[]
}

export interface Captions {
  clip_id: string
  pages: CaptionPage[]
  stats: { pages: number; mean_cps: number; warnings: number }
  /** The family the renderer picks for this script; previews use it. */
  font?: string
  edited?: boolean
}

export interface CaptionStyle {
  key: string
  /** The preset this clip saves, when it has one. */
  preset?: string
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
  overrides: Record<string, string | number | boolean>
  /** Present on an apply-to-all response. */
  applied?: number
}

export interface FontCatalog {
  families: string[]
  curated: Record<string, string[]>
}

export interface FramingStatus {
  available: boolean
  engine: string
  model: string
  hint: string
  cv2?: boolean
  model_installed?: boolean
  configured?: boolean
  model_id?: string
}

export interface HardwareModel {
  id: string
  kind: 'asr' | 'llm' | 'vad' | 'face'
  label: string
  size_gb: number
  min_tier: string
  speed: string
  url: string
  filename: string
}

export interface Hardware {
  profile: {
    cpu: { name: string; logical_cores: number; physical_estimate: number }
    memory: { total_gb: number; available_gb: number }
    gpus: { name: string; vram_gb: number; vendor: string; integrated?: boolean; dedicated?: boolean }[]
    primary_gpu: { name: string; vram_gb: number; vendor: string } | null
    cuda: boolean
    vulkan: boolean
    disk_free_gb: number
    os: string
    ffmpeg: boolean
  }
  advice: {
    tier: string
    tier_label: string
    blurb: string
    asr: HardwareModel | null
    vad: HardwareModel | null
    llm_scoring: HardwareModel | null
    llm_polish: HardwareModel | null
    model_budget_gb: number
    notes: string[]
  }
  models: HardwareModel[]
}

export type Verdict = 'approve' | 'reject' | 'undo'

export interface ModelStatus {
  id: string
  kind: 'asr' | 'vad' | 'llm' | string
  label: string
  size_gb: number
  min_tier: string
  speed: string
  filename: string
  installed: boolean
  active: boolean
  fits: boolean
  path: string
  tier_ok: boolean
}

export interface Diagnostics {
  version: string
  pid: number
  uptime_s: number
  python: string
  data_dir: string
  data_writable: boolean
  log: string
  db: { path: string; bytes: number }
  media: { path: string; bytes: number }
  disk: { free_gb?: number; total_gb?: number }
  busy: boolean
  jobs: JobState[]
  ffmpeg: string
  llama_url: string
  whisper_cli: string
}

export interface ModelsPayload {
  tier: string
  models_dir: string
  available_gb: number
  reserve_gb: number
  models: ModelStatus[]
  active: { asr: string; vad: string; llm: string; whisper_cli: string; llama_url: string }
  recommended: { asr: string | null; llm: string | null }
  whisper_cli: string
  asr_ready: boolean
}
export interface RunnerProbe {
  url: string
  reachable: boolean
  models: string[]
  error: string
}

export interface RunnerSettings extends RunnerProbe {
  source: 'env' | 'config' | 'none'
  editable: boolean
}

export interface Readiness {
  machine: {
    os: string
    memory_gb: number
    gpu: string
    vram_gb: number
    tier: string
    note: string
  }
  video: { ffmpeg: boolean; disk_free_gb: number }
  speech: {
    ready: boolean
    model: string
    whisper_cli: string
    bin_dir: string
    recommended: { id: string; label: string; size_gb: number; speed: string } | null
  }
  scoring: { built_in: boolean; runner: RunnerSettings }
  models: { dir: string; available_gb: number }
}

export interface SuggestionEvidence {
  quote: string
  start: number | null
  end: number | null
  metric: string
  value: unknown
  label: string
}

export interface Suggestion {
  id: string
  source_id: string
  clip_id: string
  kind: string
  severity: 'warn' | 'info'
  title: string
  why: string
  evidence: SuggestionEvidence[]
  fix: string
  auto_fixable: boolean
  action: Record<string, unknown>
  status: 'open' | 'applied' | 'dismissed' | 'resolved'
}

export interface SuggestionPreview {
  type: 'trim' | 'hook' | 'none'
  before: Record<string, unknown>
  after: Record<string, unknown>
  before_text: string
  after_text: string
  duration_s?: number
}

export interface PersonalModelState {
  version: string
  active: boolean
  created_at: number
  data_window: string
  metrics: Record<string, number | string | boolean>
  feature_importance: Record<string, number>
}

export interface PersonalState {
  ready: boolean
  posts: number
  positives: number
  negatives: number
  min_posts: number
  min_per_class: number
  min_auc_gain: number
  blend_cap: number
  active: PersonalModelState | null
  history: PersonalModelState[]
}

export interface WeeklyState {
  last_run: number
  next_run: number
  due: boolean
  interval_days: number
  results: Array<{
    account_id: string
    platform: string
    display_name: string
    ok: boolean
    new_posts?: number
    labels?: { labeled: number; positives: number; negatives: number; median: number }
    error?: string
  }>
  training: Record<string, unknown>
  running: boolean
}

export interface AccountPost {
  id: string
  account_id: string
  platform_post_id: string
  url: string
  title: string
  caption: string
  published_at: number
  duration_s: number
  hashtags: string[]
  features: Record<string, number>
  metrics: Record<string, number | null>
  composite: number | null
  engagement_rate: number
  label: number | null
  origin: string
  captured_at: number
}

