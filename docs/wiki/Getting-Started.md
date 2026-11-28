# Getting Started

This page takes you from a clean checkout to a rendered clip. The application has two processes in development: a FastAPI sidecar and a Vite frontend. `scripts/run.cmd` can also build the frontend and serve everything from one Python process.

## Requirements

| Requirement | Why |
|---|---|
| Python 3.11+ | The API, pipeline and tests |
| Node.js 20.19+ or 22.12+ | Vite 7 and the React frontend |
| ffmpeg and ffprobe on `PATH` | Media probing, audio extraction, rendering and export; the build must include libass |
| A Chromium-based browser or the Electron shell | Video preview and the full workspace |
| Optional: whisper.cpp binary | Real transcription; without it the app can use an API-supplied subtitle file or the deterministic stub |
| Optional: a local llama.cpp server | LLM re-ranking; without it the labelled heuristic stub is used |
| Optional: `opencv-python-headless` | Face-aware framing (`pip install -r requirements-optional.txt`) |

`yt-dlp` is installed from `requirements.txt` and is only needed for URL imports. Twitch chat replay needs a Twitch VOD URL but no account.

## Install

### Windows

One command creates the virtual environment, installs the requirements, builds
the UI and adds a desktop shortcut:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

It checks for Python 3.11+ and Node 20+, warns when ffmpeg is missing, and is
safe to re-run. Pass `-SkipBuild` to reuse an existing `web\dist`, or
`-NoShortcut` to skip the shortcut.

The manual route:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

cd web
npm install
cd ..
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd web
npm install
cd ..
```

## Run in development

Use two terminals so the frontend can hot-reload while the API stays up.

**Terminal 1 — API**

```powershell
$env:PYTHONPATH = "backend"
$env:CLIPPER_DATA_DIR = "$PWD\data"
.\.venv\Scripts\python.exe -m clipper --port 8756
```

On macOS or Linux:

```bash
PYTHONPATH=backend CLIPPER_DATA_DIR="$PWD/data" .venv/bin/python -m clipper --port 8756
```

`PYTHONPATH=backend` is required. Without it, `python -m clipper` cannot find the package.

**Terminal 2 — frontend**

```bash
cd web
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` to `127.0.0.1:8756`.

### One-command Windows launch

```powershell
.\scripts\run.cmd
```

This builds the frontend when `web\dist` is missing (pass `--rebuild` to force a
fresh build), sets `CLIPPER_DATA_DIR` to the repository's `data` directory,
starts the API on port 8756, and opens the browser. It is the quickest way to run
the production bundle, but it does not hot-reload.

### Build a Windows installer

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1
```

The script builds the UI, unpacks a portable Python 3.12 runtime with the
backend requirements into `.build-release\python`, and packages the Electron
shell with electron-builder. The result is
`dist-installer\ClipFactory-Setup-0.1.0.exe` (per-user install, no admin
prompt). It is unsigned, so Windows SmartScreen warns on first launch. Pass
`-SkipWeb` or `-SkipPython` to reuse existing inputs, and `-NoInstall` when
`desktop\node_modules` is already current.

The installed app carries its own Python and the built UI; ffmpeg, whisper.cpp
and any local model still come from the machine, exactly as in a checkout.

## Run the built app

```bash
cd web
npm run build
cd ..
```

Start the API exactly as above. When `web/dist` exists, FastAPI serves it at the same origin as `/api`; open `http://127.0.0.1:8756`.

### Desktop shell

```bash
cd web
npm run build
cd ../desktop
npm install
npx electron .
```

If Electron exits with `app is undefined`, unset `ELECTRON_RUN_AS_NODE` for that command. The shell starts the Python sidecar and loads the built UI.

## First clip

1. Open the **Library** area in the left rail.
2. Choose **Demo stream** for a generated three-minute source, or press **Add source** and paste a file path / VOD URL.
3. Choose **Analyze**. The header shows Audio, Transcribe, Signals, Score and Select progress.
4. Open the **Clips** area. The selected clip appears in the **Inspector** and the **Monitor**.
5. Approve or reject a few clips. Rejections can carry a short reason, which feeds the local learning loop.
6. Open **Output** in the Inspector, pick a caption preset and framing mode, then choose **Render clip**.
7. Download the MP4, bake the whole reel, or use **Handoff** to export a bundle with OTIO, FCP7 XML, FCP X XML or EDL.

If no ASR model or whisper binary is installed, transcription falls back to an API-supplied subtitle file or the deterministic stub. Subtitle import currently has no control in the interface; it is the `subtitle_path` field on `POST /api/sources/{id}/analyze`. If no local LLM server is running, scoring falls back to the labelled `heuristic-stub`. The full workflow still runs and each clip records which backend produced it. Install models when you want real transcription and model judging; see [Hardware and models](#hardware-and-models).

## Hardware and models

Open **Hardware & models** from the rail's **Settings** menu, the setup banner, or **File → Hardware & models**.

The dialog reports CPU, memory, GPU, CUDA/Vulkan, free disk, ffmpeg and the recommended tier. The **Models** section lists curated ASR, VAD, scoring and face-tracking files with size, fit and install state.

- Downloads are resumable and leave a SHA-256 checksum beside the file.
- **Activate** points the pipeline at a downloaded model and persists the choice.
- For any language other than English, download a **multilingual** Whisper model; an `.en` model only ever produces English, whatever language the analysis asks for.
- **Face tracking (YuNet)** has no Activate button: install it and the render picks it up. It also needs `opencv-python-headless` from `requirements-optional.txt`; without that package the app reports why it is not in use.
- whisper.cpp is not bundled. Put `whisper-cli.exe` in `<data>\bin` or on `PATH`; the dialog reports when the binary is missing.
- A local llama.cpp server is optional. Configure it with `CLIPPER_LLAMA_URL` or `llama_url` in `config.json`.

## Where data lives

| Platform | Default data directory |
|---|---|
| Windows | `%APPDATA%\ClipFactory` |
| macOS / Linux | `$XDG_DATA_HOME/ClipFactory` or `~/.local/share/ClipFactory` |
| `scripts\run.cmd` | The repository's `data` folder |

Set `CLIPPER_DATA_DIR` to override it. The directory contains:

| Path | Contents |
|---|---|
| `clipper.sqlite3` | Sources, analyses, decisions, edits, accounts and post metrics, the publish queue, trained models and state |
| `media/` | Source video downloaded from URLs; local files are referenced in place, not copied |
| `artifacts/` | Per-source transcripts, peaks, signals and candidate artifacts |
| `models/` | Downloaded model files and checksums |
| `renders/` | Rendered MP4 masters |
| `bin/` | Optional local binaries such as `whisper-cli` |
| `config.json` | Optional settings overrides |

The Electron shell overrides the data location with Electron's `userData` folder, normally `%APPDATA%/clip-factory-desktop` on Windows. It keeps the desktop library separate from the browser/dev library.

Changing `CLIPPER_DATA_DIR` points the app at a different library. It does not migrate existing sources, and local sources disappear from the new library unless you re-import them.

## Useful startup options

```bash
./.venv/Scripts/python.exe -m clipper --help
./.venv/Scripts/python.exe -m clipper --reload --log-level debug
```

`--reload` is for API development. Keep the Vite server running separately when you use it.

## Next

- Learn the panels and shortcuts in [The Workspace](The-Workspace.md).
- Understand what you are approving in [Reviewing Clips](Reviewing-Clips.md).
- Publish a clip and let the app learn from how it did in [Publishing](Publishing.md) and [Learning from your posts](Learning.md).
- If something refuses to start, use [Troubleshooting](Troubleshooting.md).
