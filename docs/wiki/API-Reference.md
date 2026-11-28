# API Reference

The API is a local FastAPI service. It is unversioned, unauthenticated, and intended for the bundled frontend, the desktop shell, and local scripting on the same machine.

Base URL: `http://127.0.0.1:8756/api` in development and with `scripts/run.cmd`.

## Conventions

- Request and response bodies are JSON unless noted.
- Errors use FastAPI's `{"detail": "..."}` envelope with a 4xx or 5xx status.
- Long operations return a job immediately. Follow it with `GET /api/jobs/{id}/events` (server-sent events, one frame per change, closed after the last) or poll `GET /api/jobs/{id}`. Both routes build their payload from one function, so they cannot disagree.
- A completed job exposes its result as `analysis`, regardless of whether it was an analysis, a download or a render.
- There are two lanes. A second compute-heavy request (analysis, render) queues behind the first; downloads, uploads and tool installs use the separate I/O lane and do not block it.

### Job shape

```json
{
  "id": "1710000000000-12",
  "kind": "analyze",
  "status": "running",
  "stage": "score",
  "pct": 0.62,
  "detail": "judging 10 of 14 candidates",
  "error": "",
  "created_at": 1710000000.0,
  "updated_at": 1710000002.4,
  "elapsed": 2.4
}
```

`status` is `queued`, `running`, `done` or `error`. `pct` is 0–1. On success, the result is attached to the job response as `analysis`.

## System

| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | `ok`, version, data dir, busy flag, llama URL, whisper path |
| GET | `/api/diagnostics` | Versions, data-directory sizes, disk free, for a bug report |
| GET | `/api/readiness` | Every setup card's check, from one probe of the machine |
| GET | `/api/tools` | ffmpeg and whisper.cpp: installed, resolved path, pinned version, and whether automatic install is supported |
| POST | `/api/tools/{tool_id}/install` | Download, verify and unpack one tool as a `tool` job; 404 for an unknown id |
| GET | `/api/hardware?refresh=false` | Hardware profile, tier advice, model recommendations |
| GET | `/api/ffmpeg` | libass availability and hardware encoder availability |
| GET | `/api/settings/llm` | Scoring runner address, its source and whether it answers |
| POST | `/api/settings/llm` | Save a runner address; 409 when `CLIPPER_LLAMA_URL` owns it |
| POST | `/api/settings/llm/test` | Probe an address without saving it |

`/api/ffmpeg` calls ffmpeg directly on every request. It reports `available: true` when the ffmpeg build has the `ass` filter, which is the libass requirement for burning captions.

`/api/readiness` is the same payload the setup cards and first-run tour read, so a check cannot disagree between the card and the API. Its `tools` field is the same payload as `GET /api/tools`. `/api/diagnostics` never leaves the machine; the about panel is the only consumer.

## Sources

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/sources` | List sources with `analyzed`, `clip_count` and `reel_quality` |
| POST | `/api/sources` | Register a local path synchronously |
| POST | `/api/sources/url` | Download an HTTP(S) VOD as a job |
| POST | `/api/demo` | Generate and register the demo stream |
| GET | `/api/sources/{id}` | One source |
| GET | `/api/media/{id}` | Stream the source file |
| GET | `/api/sources/{id}/chat` | Chat coverage and origin |
| POST | `/api/sources/{id}/chat/fetch` | Fetch Twitch chat replay as a job |
| POST | `/api/sources/{id}/analyze` | Run analysis as a job |
| GET | `/api/jobs` | The 20 most recent jobs |
| GET | `/api/jobs/{id}` | One job and its result |
| GET | `/api/jobs/{id}/events` | SSE stream: a frame per change, then the result |
| GET | `/api/sources/{id}/analysis?shape=reel` | The stored analysis, or 404 |
| GET | `/api/sources/{id}/peaks?buckets=1400` | Min/max peak envelope, 50–4000 buckets |
| GET | `/api/sources/{id}/thumb?t=0&w=320` | One JPEG still, cached on disk |
| POST | `/api/sources/{id}/proxy` | Build the preview proxy as a job |
| GET | `/api/media/{id}?proxy=1` | Stream the browsing proxy instead of the source |
| POST | `/api/sources/preview` | Inspect a URL without downloading it |
| GET | `/api/sources/{id}/tracks` | Caption tracks available for a fetched source |
| POST | `/api/sources/{id}/subtitles` | Download one caption track as a job |
| GET | `/api/languages` | Language catalogue: code, name, native name, script, RTL |
| GET | `/api/fonts` | Installed font families plus curated per-script picks |

### Analysis shapes

`shape=reel` (the default) returns ranked clips without `words` or `caption_pages` and drops unranked candidates — those are the megabytes and the reel does not draw them. `shape=full` returns every candidate with word timings.

### Register a local source

```bash
curl -X POST http://127.0.0.1:8756/api/sources \
  -H "Content-Type: application/json" \
  -d '{"path": "C:/media/stream.mp4", "name": "Stream"}'
```

Returns a `SourceInfo`. This route does not download; the path must exist. A URL input is rejected unless you use `/api/sources/url`.

### Import a URL

```bash
curl -X POST http://127.0.0.1:8756/api/sources/url \
  -H "Content-Type: application/json" \
  -d '{"path": "https://www.twitch.tv/videos/123456789"}'
```

Returns a job. Requires `yt-dlp`; otherwise 409 with an install hint. Playlists are refused by the fetcher.

### Analyze

```bash
curl -X POST http://127.0.0.1:8756/api/sources/<source-id>/analyze \
  -H "Content-Type: application/json" \
  -d '{"limit": 10, "force": false}'
```

| Field | Type | Meaning |
|---|---|---|
| `subtitle_path` | string? | Path to an SRT/VTT file. Used only when no whisper backend is available, and not when a transcript artifact already exists. |
| `chat_path` | string? | Use a local chat dump |
| `limit` | int | Number of clips requested from selection; default 10 |
| `force` | bool | Ignore the cached analysis result and run the pipeline again. Reuses `artifacts/<source-id>/transcript.json`; delete that file to change ASR output. |

Returns a job. The finished analysis is on `job.analysis` and is also persisted for `GET /analysis`.

### Analysis shape

```text
AnalysisResult
  source          SourceInfo
  candidates      ClipCandidate[]
  asr_backend     string
  llm_backend     string
  duration_s      number
  reel_quality    number (0-1)
  warnings        string[]
```

Each candidate carries `id`, `rank`, `start`, `end`, `text`, `words`, `signals`, `features`, `gates`, `scorecard`, `llm`, `fused`, `final`, `caption_pages` and `blocked`. `llm` can be null on an unscored candidate.

## Clips

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/sources/{sid}/clips/{cid}` | One candidate |
| GET | `.../captions` | Generated or edited caption pages and stats |
| PUT | `.../captions` | Save a manual caption pass |
| DELETE | `.../captions` | Discard manual pages and regroup from words |
| POST | `.../decision` | Approve, reject or undo |
| POST | `.../hook` | Set the hook text |
| POST | `.../trim` | Set in/out points |
| GET | `.../framing` | The auto-framing plan without rendering |
| GET | `.../captions/style?preset=hormozi` | The effective caption style (preset + this clip's overrides) |
| PUT | `.../captions/style` | Save per-clip caption style overrides |
| DELETE | `.../captions/style?preset=hormozi` | Back to the shipped preset |
| GET | `.../subtitles?format=srt` | This clip's captions as SRT, VTT or ASS |
| GET | `/api/sources/{sid}/subtitles?format=srt` | Zip of every clip's captions, in rank order |

### Caption style

```json
{ "preset": "hormozi", "overrides": { "font": "Impact", "size": 88, "primary": "&H0000FF00", "uppercase": false } }
```

Accepted override keys: `font`, `size`, `primary`, `secondary`, `outline`, `back`, `bold`, `outline_width`, `shadow`, `alignment`, `margin_v`, `margin_h`, `uppercase`, `karaoke`. Unknown keys are dropped and values are clamped (`size` 24–200, `outline_width` 0–20, `karaoke` one of `k`, `kf`, `none`) before anything is stored, so the render, the ASS download and the studio preview read the same numbers. The response is the effective style plus the `overrides` actually kept. `DELETE` removes them.

### Decision

```json
{ "action": "reject", "reason": "boring" }
```

`action` must be `approve`, `reject` or `undo`. Rejection reasons are free text; the UI offers `boring`, `confusing`, `cut off`, `spoiler`, `off topic`, `duplicate` and `unspecified`. The response includes the learner state and, when a decision was recorded, the learning outcome.

`undo` is accepted for client convenience. It does not delete the earlier decision row from the append-only log.

### Hook

```json
{ "hook": "The part nobody warns you about" }
```

Requires a scored candidate (`llm` present). The edit is recorded in `hook_edits`, applied to the analysis and reflected in the profile state.

### Trim

```json
{ "start": 142.5, "end": 187.0 }
```

Either edge can be omitted. The server clamps to the source, enforces a 5-second minimum, re-cuts words, rebuilds text, re-runs gates and rebuilds the scorecard. Caption pages are cleared and regenerated from the new word set.

### Captions

`PUT` takes a page array of caption words:

```json
{
  "pages": [
    [
      { "text": "The", "start": 0.0, "end": 0.18 },
      { "text": "first", "start": 0.18, "end": 0.46 }
    ]
  ]
}
```

The server re-groups the words under the configured line, word, CPS and duration limits. Invalid words or pages return 400. This route exists because the UI caption editor is read-only; it is the supported way to script a caption change.

### Framing

Returns the planned crop width, source dimensions, confidence and knots for the `auto` strategy. It does not render. A clip with no usable plan reports that the render will fall back to centre crop.

## Rendering and export

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/render/presets` | The full caption preset catalogue |
| POST | `/api/sources/{sid}/clips/{cid}/render` | Queue a render |
| GET | `/api/renders/{filename}` | Serve a rendered MP4 |
| GET | `/api/framing/status` | Whether face-aware framing can run, and what it falls back to |
| GET | `/api/sources/{sid}/export?format=bundle` | Download a handoff |
| POST | `/api/sources/{sid}/export/bake` | Render every selected clip into one folder, as a job |
| GET | `/api/sources/{sid}/export/bake` | The last bake's manifest, or `exists: false` |
| GET | `/api/sources/{sid}/export/bake/file/{name}` | Serve one baked MP4 |
| POST | `/api/reveal` | Open a bake folder in the file manager |

The reveal route only accepts paths inside the exports tree (403 otherwise) and only opens an existing folder (404 if not).

### Bake

```json
{ "preset": "hormozi", "framing": "auto", "approved_only": false }
```

Returns a job. The result carries `folder`, `clip_count`, `baked`, `failed` and a `clips` array where each entry has `file` on success and `error` on failure. The folder holds `<NN> <hook>.mp4`, `captions/<NN> <hook>.srt`, `manifest.json` and `README.txt`; a bake replaces the previous folder for that source. Renders are reused from the cache and hard-linked where the filesystem allows it.

### Render

```json
{ "preset": "hormozi", "framing": "auto", "force": false }
```

Returns a job. `framing` is `auto`, `blur` or `crop`. `force` skips the cached MP4. A fresh result includes `url`, `filename`, `duration`, `bytes`, `pages`, `style`, `framing`, `encoder`, `crop` and `cached: false`. A cache hit returns `url`, `filename`, `duration`, `style`, `framing`, `crop` and `cached: true`, without encoder or page count.

### Export

`format` is `bundle`, `otio`, `fcpxml`, `edl` or `srt`. The response is a file attachment. `bundle` includes `reel.otio`, `reel.xml`, `reel.edl`, `README.txt`, `manifest.json`, per-clip SRT files and any existing renders for exported clips.

Exports include every ranked clip, not only approved clips. A source without a ranked clip returns 409.

## Accounts and publishing

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/accounts` | Connected accounts, platform limits, credential-store status |
| POST | `/api/accounts/{platform}/connect` | Start OAuth; returns the provider `url` to open |
| GET | `/api/connections/callback` | Loopback OAuth callback; returns an HTML page |
| DELETE | `/api/accounts/{id}` | Revoke and forget an account |
| POST | `/api/accounts/{id}/sync` | Pull posts and metrics through the platform API |
| GET | `/api/accounts/{id}/overview` | Followers, medians and label readiness for one account |
| GET | `/api/accounts/{id}/posts?limit=100` | Recent posts with the latest metrics and engagement rate |
| GET | `/api/publish/limits` | Platform limits, supported platforms, verification date |
| POST | `/api/publish/validate` | Validate a draft without uploading |
| POST | `/api/publish` | Queue an upload |
| GET | `/api/publish/jobs` | Recent upload jobs |
| GET | `/api/publish/jobs/{id}` | One upload job |
| POST | `/api/publish/jobs/{id}/retry` | Requeue a failed upload |
| POST | `/api/publish/jobs/{id}/cancel` | Cancel a queued upload |
| GET | `/api/posts` | Published posts recorded locally |

`POST /api/publish` needs `platform` (`youtube` or `x`), `account_id`, `media_path` (the rendered MP4's local path, returned by a render as `path`), `title`, `caption`, `hashtags`, `visibility` and `made_for_kids`. An unsupported platform returns 400; a draft that breaks a platform limit returns 400 with the issue list in `detail`. Validation and upload use the same rules. Reusing an `idempotency_key` returns the existing job instead of uploading twice.

The queue claims a job before submitting it, retries retryable failures with backoff, resumes interrupted `running` jobs on launch, and runs a due-job scheduler every 20 seconds. `retry` refuses a job that is `running` or `cancelling`, and refuses one that already reached `done` (409 for both): re-publishing needs a new render, not a second copy of the same post.

Tokens live in the operating system credential store, never in `config.json`. Only `render_id` and `market_version` are read from a client-supplied `metadata` object; the title, caption, visibility and policy version were just validated and are not overwritten. The clip's `features`, `signals` and `llm` payloads are taken from the stored candidate, never from the request, so a published post cannot carry a feature vector the pipeline did not measure. A clip that no longer exists is recorded with `feature_coverage: "none"` and stays out of the performance model.

The API rejects publishing when the credential store is unavailable rather than writing tokens to disk.

## Models

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/models` | Manifest, install state, active model, fit |
| POST | `/api/models/{id}/download` | Download as a job |
| POST | `/api/models/{id}/activate` | Activate a downloaded model |

Activation persists in `config.json` and survives restart. A model that is not installed returns 409; an unknown id returns 404.

## Learning

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/learn/state` | Decision counts, threshold progress, gate and style profile |
| POST | `/api/learn/profile/refresh` | Rebuild the style profile |
| GET | `/api/learn/export` | JSONL dataset of decisions |
| GET | `/api/learn/personal` | Taste blend weight, account readiness and model history |
| POST | `/api/learn/personal/train` | Train one account (or all) through the holdout gates |
| POST | `/api/learn/personal/{version}/activate` | Activate a promoted model |
| POST | `/api/learn/personal/rollback` | Pause the personal model and return to approval-only ranking |
| GET | `/api/learning/weekly` | Last run, next run, due state and last results |
| POST | `/api/learning/weekly/run` | Sync accounts and train now |
| GET | `/api/sources/{source_id}/clips/{clip_id}/suggestions` | Regenerate coach suggestions for a clip |
| POST | `/api/sources/{source_id}/clips/{clip_id}/suggestions/{id}/preview` | Before/after preview |
| POST | `/api/sources/{source_id}/clips/{clip_id}/suggestions/{id}/apply` | Apply a fix and return the updated candidate |
| POST | `/api/sources/{source_id}/clips/{clip_id}/suggestions/{id}/undo` | Restore the stored pre-apply value |
| POST | `/api/sources/{source_id}/clips/{clip_id}/suggestions/{id}/dismiss` | Hide without changing the clip |

The export is `application/jsonl`. It is generated from the local decision log and is not automatically uploaded anywhere.

The personal model's gate is code, not an API option: 30 full-feature posts, 10 per class, a held-out AUC at least 0.03 above a reach-only baseline and a 200-permutation p < 0.05. `train` reports the gate result and leaves the active model alone on failure. `activate` refuses a version that did not clear the gate (409) — a failed attempt stays in the history for inspection but cannot be promoted by hand. The weekly daemon honors its seven-day interval; a manual run always runs.

## Errors

| Status | Typical cause |
|---|---|
| 400 | Unknown export format, invalid decision action, malformed caption pages, not an HTTP(S) URL, draft that breaks a platform limit |
| 401 | The account's token expired or was revoked; reconnect it |
| 404 | Source, clip, job, render, model or account not found; analysis or peaks not built |
| 409 | URL import without yt-dlp, no ranked clips to export, model not downloaded, retry of a running or finished upload, activation of a model that failed its gate, runner address set by `CLIPPER_LLAMA_URL` |
| 500 | ffmpeg missing, malformed peaks artifact, demo generation failure |
| 502 | The platform's analytics or upload API failed; `detail` carries the platform's message and `code` |
| 503 | The operating system credential store is unavailable, so connecting an account is refused |

ffmpeg failures inside a render job are reported on the job's `error` field, not as HTTP 500, because the request only queued the work.

## Not in the API

There is no authentication, user model, project lock, webhook or batch render endpoint. The app is designed to be the only client on a loopback interface.

Progress is available two ways — an SSE stream and a poll route — but there is no WebSocket, no server push of anything except job state, and no event history: a stream only reports what happens while it is open.

Only YouTube and X publishing are implemented; the account and limit records for TikTok and Instagram exist, but their upload and analytics adapters are not.

---

Next: [Development](Development.md).
