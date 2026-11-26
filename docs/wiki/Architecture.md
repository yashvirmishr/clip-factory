# Architecture

Clip Factory is one local service with a browser frontend and an Electron desktop shell. Neither client talks to a cloud API. The Python process owns the database, media, models, jobs and renders.

```text
Browser (localhost:5173)        Electron shell
        |                          |
        +-------- HTTP -----------+
                     |
              FastAPI on 127.0.0.1
                     |
     +---------------+----------------+
     |               |                |
  SQLite          JobManager        Static web/dist
     |               |
  analyses       one worker
  decisions          |
  edits          pipeline / render
                     |
              media, artifacts, models, renders
```

## Process model

`python -m clipper` starts Uvicorn. It binds `127.0.0.1:8756` by default. `web/dist` is mounted at `/`; in development the browser loads Vite on port 5173 and proxies `/api` to the same API.

The API creates a `JobManager` with a single worker thread. Every long task — analysis, URL download, chat fetch, model download or render — goes through that queue. Jobs expose `queued`, `running`, `done` or `error`, a stage label and a 0–1 progress value. Job state is in memory; a restart loses a queued or running job, not completed analyses.

One worker is a deliberate constraint. The pipeline and ffmpeg are already CPU- and memory-heavy on a laptop; two renders or a render beside a transcription would make timings and failures unpredictable. The UI enforces the same reality by reporting that the backend is busy.

## The analysis pipeline

| Stage | Module | Responsibility |
|---|---|---|
| Ingest | `pipeline/media.py`, `pipeline/fetch.py` | Probe with ffprobe, download URLs with yt-dlp, resolve metadata |
| Audio | `pipeline/media.py` | Extract the analysis track and build the peak pyramid |
| Transcribe | `pipeline/asr.py` | whisper.cpp, SRT/VTT import, or a deterministic stub |
| Align | `pipeline/align.py` | Clamp word timings, snap to silence, repair outliers |
| Scenes | `pipeline/scenes.py` | Detect cuts with ffmpeg and expose shot boundaries |
| Signals | `pipeline/signals.py` | Loudness, speech, hook-lexicon, chat and scene features |
| Windows | `pipeline/windows.py` | Sentence-bounded candidate windows |
| Gates | `pipeline/gates.py` | Structural pass/fail checks |
| Score | `llm/scorer.py`, `llm/grammar.py` | GBNF-constrained JSON scoring, with a labelled stub fallback |
| Select | `pipeline/select.py` | Overlap removal, dedupe, diversity and rank assignment |
| Scorecard | `pipeline/scorecard.py` | The eight visible checks and reel quality |
| Captions | `pipeline/caption/group.py` | Page grouping under word, line, CPS and duration limits |

Analysis is cached in the `analyses` table as a serialized `AnalysisResult`. A normal analyze request returns the cached result; `force` runs the pipeline again. The UI's re-analysis path uses force, so a deliberate model change can replace the old result.

One artifact sits below that cache: `artifacts/<source-id>/transcript.json`. `_transcribe` reuses it even on `force`, and it also wins over a newly supplied `subtitle_path`. After changing the ASR backend, delete that file before forcing analysis; changing only the LLM scorer does not require it.

### Why the cheap signals come first

Running a language model over every window is expensive and noisy. The deterministic signals decide where to look, gates remove structurally broken candidates, and only a shortlist reaches the model. The model's role is re-ranking, not discovery. This is also why the app can run without any model: the stub still produces a ranked reel, clearly labelled.

### The judge

The LLM adapter talks to a local `llama-server` over HTTP and requests a constrained JSON object containing a score, hook, title and reason. The grammar prevents malformed JSON from becoming a parse failure. If the server is absent, slow or returns invalid output, the stub provider keeps the pipeline usable and marks itself in the UI.

## Rendering

Rendering is a separate job and a separate module tree:

- `render/ass.py` owns the five caption styles and ASS generation, including karaoke timing.
- `render/ffmpeg.py` builds the filter graph and encoder arguments.
- `render/__init__.py` resolves framing, groups caption pages, computes a cache key and runs ffmpeg.
- `pipeline/framing.py` plans the auto crop from motion and skin density. The render uses that plan; `GET /api/sources/{sid}/clips/{cid}/framing` exposes the same plan for inspection before rendering.

The render cache is content-addressed by clip, preset, resolved framing and a digest of caption pages and caption style. A hook edit does not change the cache key because the hook is not part of the picture; a restyle does, because the pixels change.

## Editor handoff

`editors/spec.py` turns ranked candidates into `ClipSpec` objects. Each format is a renderer over the same specs:

| Module | Output |
|---|---|
| `otio.py` | OpenTimelineIO JSON |
| `xmeml.py` | FCP7 XML |
| `edl.py` | CMX 3600 EDL |
| `srt.py` | Per-clip SRT |
| `bundle.py` | Zip with all of the above and a manifest |
| `timecode.py` | Shared frame and timecode conversion |

Media is referenced by absolute path. The exporters do not copy source files.

## Learning loop

`learn/features.py`, `ranker.py`, `memory.py` and `profile.py` use the local decision log. Once there are enough labels, the app fits a personal re-ranker, evaluates it on a held-out split and only promotes it when it clears the configured improvement gate. The same history produces a compact few-shot memory and a style profile used in later prompts.

The learning loop is local and optional. It cannot repair a source that was transcribed badly, and it does not change the structural gates.

## Frontend

```text
web/src/
  App.tsx                  layout, commands, menus, shortcuts, selection
  api.ts                   typed HTTP client and formatting helpers
  types.ts                 shared response shapes
  styles.css               hand-authored shell and component styles
  components/              ProjectPanel, Reel, Monitor, Inspector, Timeline, ...
  workspace/               MenuBar, Tabs, Resizer, ContextMenu, CommandPalette, ...
  theme/                   compile, persistence, atelier, preview, built-in themes
```

There is no router. `App.tsx` is the composition root: it owns the selected source and clip, verdicts, job progress, workspace persistence and the command registry. Job progress is a server-sent event stream wrapped in `watchJob` (`web/src/api.ts`), which falls back to polling when `EventSource` is missing or the stream keeps failing — one place to reason about both. Every job in the app goes through it: analysis, chat, render, bake, model downloads and the VOD wait (`pollUntilDone`, which is now just a promise over the stream). The only remaining poll is the publish-queue list, because that is a collection and not one job.

Caption pages are cached per clip in `api.ts` (the last 24) and forgotten by `forgetCaptions` when a trim or a re-analysis changes the words. The clip id does not change on a trim, so without that explicit invalidation the captions tab would keep showing the pages from before the cut. A command is a single object with an id, label, group, icon, shortcut, disabled flag and run function; the menu bar, palette and context menus read from that registry. The global key handler mirrors the common shortcuts explicitly, because it also has to defer to focused inputs and dialogs.

Panel geometry and view state live under `clip-factory.workspace.v2`. Theme state lives under `clip-factory.theme.v1`. Nothing in the workspace layout is sent to the API.

The Timeline draws to a canvas and reads its colours from the compiled theme tokens, so it follows the active room rather than hardcoding a palette.

## Storage

| Table | Purpose |
|---|---|
| `sources` | Path, probe metadata, origin URL, creation time |
| `analyses` | Serialized pipeline result per source |
| `decisions` | Every approve/reject with reason, features, scores and model version |
| `hook_edits` | Before/after hook history |
| `state` | Small key/value application state |

SQLite is the index, not the media store. Source media stays where it is; downloaded URL sources land in `media/`; analysis sidecars and renders live in their own directories. The database path is `<data>/clipper.sqlite3`.

## Trust boundary

- The server binds to loopback by default. `--host` can change that, but there is no authentication, so exposing it to a network is not supported.
- CORS allows the local Vite origin. The built app is same-origin.
- Render filenames are validated before serving; the static mount only serves `web/dist`.
- The local API can read sources by path. Anyone who can run code as your user can already read those files; the app does not pretend otherwise.
- There is no telemetry. The backend makes no outbound call on startup. The page requests its default Google Fonts stylesheet, and falls back to system fonts when offline; URL import, chat fetch, model download and custom remote font stylesheets are explicit user actions.

## Desktop shell

`desktop/main.js` starts the Python sidecar on an ephemeral loopback port, waits for `/api/health`, and loads the URL in a sandboxed renderer. It owns the sidecar's lifetime and kills the process tree on exit. The sidecar's data directory is Electron's `userData`, not the repository's `data` folder.

---

Next: [API Reference](API-Reference.md).
