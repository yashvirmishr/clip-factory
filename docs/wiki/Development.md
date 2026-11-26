# Development

This page is for changing Clip Factory. It assumes the install from [Getting Started](Getting-Started.md) works and that you have read [Architecture](Architecture.md).

## Run the two halves

Backend, with reload:

```powershell
$env:PYTHONPATH = "backend"
./.venv/Scripts/python.exe -m clipper --reload
```

Frontend:

```powershell
cd web
npm run dev
```

Open the Vite URL, normally `http://localhost:5173`. Vite proxies `/api` to `127.0.0.1:8756`; do not hardcode a second API origin. If port 8756 is taken, start the backend elsewhere and update `web/vite.config.ts`.

Use separate data directories when two experiments would share a database:

```powershell
$env:PYTHONPATH = "backend"
$env:CLIPPER_DATA_DIR = "$PWD/tmp/experiment-a"
./.venv/Scripts/python.exe -m clipper
```

## Environment variables

The backend reads these from the process environment. Nothing else is configurable there; preferences live in the data directory.

| Variable | Effect |
|---|---|
| `CLIPPER_DATA_DIR` | Library location: database, media, artifacts, renders |
| `CLIPPER_LLAMA_URL` | Scoring runner address; when set, the Settings field is read-only and says why |
| `CLIPPER_WHISPER_CLI` | Path to `whisper-cli` when it is not in `<data>/bin` or on `PATH` |
| `CLIPPER_YTDLP_COOKIES` | `cookies.txt` for archives that refuse anonymous playback |
| `CLIPPER_LOG_LEVEL` | Backend log level, `INFO` by default |
| `CLIPPER_SECRET_BACKEND` | `keyring` (default) or `memory`; the latter keeps tokens in RAM for development |
| `CLIPPER_DISABLE_WEEKLY=1` | Stops the weekly learning daemon; the manual endpoint still works |
| `CLIPPER_DISABLE_PUBLISH_SCHEDULER=1` | Stops the thread that retries due uploads |
| `CLIPPER_DISABLE_REVOKE=1` | Skips the remote revoke call when an account is disconnected |

## Checks

Backend suite:

```powershell
./.venv/Scripts/python.exe -m pytest
```

Faster pass without the real-encode test:

```powershell
./.venv/Scripts/python.exe -m pytest -m "not slow"
```

Frontend typecheck, unit tests and production build:

```powershell
cd web
npx tsc -b --pretty false
npm test
npm run build
```

`npm test` runs Vitest over `api.test.ts` and the theme colour maths, the two places where a regression is invisible in a screenshot. Everything else is still a manual pass over the states you touched. The backend suite uses FastAPI's test client and temporary media fixtures; it does not need the dev server.

User-facing copy has its own check, and CI runs it:

```powershell
./.venv/Scripts/python.exe scripts/copy-lint.py
```

Useful focused runs:

```powershell
./.venv/Scripts/python.exe -m pytest backend/tests/test_api.py -q
./.venv/Scripts/python.exe -m pytest backend/tests/test_captions.py backend/tests/test_editors.py -q
./.venv/Scripts/python.exe -m pytest backend/tests/test_render.py -q -m slow
./.venv/Scripts/python.exe -m pytest backend/tests/test_learn.py backend/tests/test_personal.py -q
./.venv/Scripts/python.exe -m pytest backend/tests/test_analytics.py backend/tests/test_coach.py backend/tests/test_weekly.py -q
./.venv/Scripts/python.exe -m pytest backend/tests/test_publish_queue.py backend/tests/test_x.py backend/tests/test_youtube.py -q
```

Performance and pick quality have their own harnesses:

```powershell
./.venv/Scripts/python.exe scripts/perf.py
./.venv/Scripts/python.exe scripts/perf.py path/to/video.mp4
./.venv/Scripts/python.exe scripts/goldset.py benchmarks/gold/demo-stream.json
./.venv/Scripts/python.exe scripts/goldset.py benchmarks/gold --limit 5 --json
```

`perf.py` reports measured time and peak RSS per stage; it does not estimate. `goldset.py` re-runs analysis with `force` so a cached analysis cannot flatter a change. The transcript artifact is still reused; delete it when the change affects ASR.

## Where to change what

| You want to change | Start here |
|---|---|
| Page layout, panels, selection | `web/src/App.tsx` |
| A clip card, filter or sort | `web/src/components/Reel.tsx`, `ClipCard.tsx` |
| Inspector sections and score display | `web/src/components/Inspector.tsx` |
| Monitor playback, captions, transport | `web/src/components/Monitor.tsx` |
| Timeline drawing and hit testing | `web/src/components/Timeline.tsx` |
| Toolbar primitives, tabs, resizers, dialogs | `web/src/workspace/` |
| Colours, type, spacing | `web/src/styles.css` and `web/src/theme/` |
| Analysis, gates, scoring | `backend/clipper/pipeline/`, `backend/clipper/llm/` |
| Render graph and caption burn-in | `backend/clipper/render/` |
| NLE handoff formats | `backend/clipper/editors/` |
| Accounts, OAuth, token storage | `backend/clipper/accounts.py`, `backend/clipper/publish/oauth.py`, `web/src/components/AccountsPanel.tsx` |
| Upload adapters and the queue | `backend/clipper/publish/` |
| Engagement labels and the performance model | `backend/clipper/analytics.py`, `backend/clipper/personal.py` |
| Coach suggestions | `backend/clipper/coach.py`, `web/src/components/CoachPanel.tsx` |
| Weekly schedule | `backend/clipper/weekly.py` |
| HTTP surface | `backend/clipper/api.py` |

## Adding a command

Commands are the single source for menus, the command palette and context menus. Add one to the `commands` map in `App.tsx`:

```ts
{
  id: 'clip.copyTitle',
  label: 'Copy title',
  group: 'Clip',
  icon: 'copy',
  shortcut: 'Ctrl Alt T',
  keywords: 'copy title metadata',
  disabled: !selectedClip,
  run: () => { /* do the thing */ },
}
```

Then reference the id from a menu definition if it belongs in a menu. `disabled` must reflect the real state; a command that silently does nothing is a bug.

The `shortcut` field is display metadata, not an automatic binding. To make the key work, add a branch to the global `keydown` effect in `App.tsx` (it checks modifiers and focused fields first) and add the row to `workspace/ShortcutsDialog.tsx`. Never document a shortcut that has no handler.

## Adding a theme

1. Copy one definition from `web/src/theme/themes/`.
2. Give it a unique id, name, description and tag.
3. Set the nine seed colours and, if needed, fonts and radius.
4. Register it in `web/src/theme/themes/index.ts`.
5. Check every surface, not only the marketplace card: focus rings, disabled buttons, warnings, the timeline and the monitor.

Do not add per-component colour overrides. Components read semantic custom properties that `compile.ts` derives from the seeds. A hardcoded colour will look correct in one theme and broken in the other five.

See [Themes](Themes.md) and [Theme authoring](../theme-authoring.md).

## Adding an endpoint

1. Add a Pydantic request model near the top of `api.py` if there is a body.
2. Resolve the source or clip and return 404 when it does not exist.
3. Return a job for work longer than a request should take: `JOBS.submit(kind, task)`. The task receives `progress(stage, pct, detail)`.
4. Raise `HTTPException` with a specific detail. Do not return an empty success.
5. Add a test in `backend/tests/test_api.py` using `TestClient`.
6. Update `web/src/api.ts` and `web/src/types.ts` together if the frontend consumes it.

Remember that a done job's result is exposed as `analysis`, even for downloads and renders. That shape is a compatibility constraint, not an accident to fix casually.

## Data and schema

`backend/clipper/db.py` creates the SQLite schema with `CREATE TABLE IF NOT EXISTS`. There is no migration framework. A column change needs either an explicit migration in `init()` or a fresh data directory; silently changing the `CREATE` statement leaves existing databases on the old shape.

Analyses are stored as a serialized JSON payload. If you change a domain model, old payloads must still validate, or you must provide a migration. The safe default is an optional field with a default, not a required one.

A `posts` row keeps the `features`, `signals` and `llm` payloads a published clip carried. That is what lets the performance model pair a metric with the exact clip it describes; dropping or renaming one of those columns silently excludes every post from training instead of failing loudly.

## Frontend conventions

- **Clarity before decoration.** One primary action per region. Do not add a control because the space is empty.
- **No dead controls.** A button either performs its action, is disabled with a reason nearby, or does not exist.
- **Keyboard parity.** Anything clickable should be reachable and operable by keyboard; visible focus must survive every theme.
- **Semantic tokens.** Use `var(--ink)`, `var(--muted)`, `var(--line)`, `var(--accent)` and friends; do not hardcode hex values in components.
- **Plain CSS.** There is no CSS framework and no CSS-in-JS. New component styles belong in the existing stylesheet or a focused section file, not in inline styles beyond computed values.
- **No new dependency** unless the platform or React cannot reasonably do the job. The app intentionally ships React plus Vite, nothing else.
- **Respect reduced motion.** The stylesheet already disables transitions under `prefers-reduced-motion`; do not reintroduce motion in JavaScript.

### Responsive work

Check at minimum: 1440 px wide, 1280 px, 1100 px, 900 px, 760 px and 540 px. Also check a short window under 720 px high. The workspace collapses the sidebars before it shrinks the reel to unreadable cards; preserve that order.

Use a fresh browser tab for responsive checks. Resizing an existing tab through automation can be clamped by the host window and produce misleading widths.

### State that persists

Workspace geometry and view state use `clip-factory.workspace.v2`. Theme state uses `clip-factory.theme.v1`. If you add a field, sanitize it on read and give it a default; a stale stored value must not break the first paint.

## Test expectations

When changing the pipeline, cover the behaviour that can regress:

| Change | Test area |
|---|---|
| Gates or window boundaries | `test_pipeline.py` |
| Word snapping or trims | `test_captions.py`, pipeline tests |
| Caption grouping | `test_captions.py` |
| ASS output or render graph | `test_render.py` |
| Timecode and export formats | `test_editors.py` |
| Framing plans | `test_framing.py` |
| API status codes and shapes | `test_api.py` |
| Learning gate (taste re-ranker) | `test_learn.py` |
| Engagement labels and post sync | `test_analytics.py` |
| Performance-model gate and blend caps | `test_personal.py` |
| Weekly schedule and run-now path | `test_weekly.py` |
| Coach rules, preview, apply and undo | `test_coach.py` |
| Publish queue, retries and cancel | `test_publish_queue.py`, `test_api_connect.py` |
| Platform limits and adapters | `test_publish_limits.py`, `test_youtube.py`, `test_x.py` |
| OAuth callback and account storage | `test_oauth.py`, `test_accounts.py`, `test_secrets.py` |

Real encodes are slow and environment-sensitive. Keep one marked `slow` integration test rather than making every unit test invoke ffmpeg. Do not mock ffmpeg so heavily that the filter graph is never exercised.

## Build and desktop

```powershell
cd web
npm run build
cd ../desktop
npm start
```

The desktop shell expects `web/dist`. It prefers the repository virtualenv and falls back to `python` or `python3` on `PATH`. It starts its own sidecar on an ephemeral port and passes that port with `--port`; if you change the health path or the module entry point, update `desktop/main.js` too.

## House rules

- Preserve working backend behaviour unless the task is explicitly to change it.
- Prefer a focused edit over a rewrite that also reformats unrelated code.
- Do not commit generated data, renders, model weights or a populated `data/` directory.
- Leave existing user changes in the working tree alone.
- If a control is intentionally omitted, document the omission where a user will look for it.

---

Next: [Troubleshooting](Troubleshooting.md).
