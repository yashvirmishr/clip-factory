export interface Word {
  text: string
  start: number
  end: number
  prob: number
  refined: boolean
}

export interface GateResult {
  id: string
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
  words: Word[]
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
  status: 'queued' | 'running' | 'done' | 'error'
  stage: string
  pct: number
  detail: string
  error: string
  elapsed: number
  analysis?: Analysis
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
}

export interface HardwareModel {
  id: string
  kind: 'asr' | 'llm' | 'vad'
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
