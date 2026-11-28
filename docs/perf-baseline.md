# Performance baseline

Measured, not estimated. This file records one run so a later change can be
compared against it; it is not a promise about other hardware. Re-run the two
commands below on the machine you care about.

## Machine

| Part | Value |
|---|---|
| CPU | AMD Ryzen 7 8840HS, 8 cores / 16 threads |
| GPU | AMD Radeon 780M (integrated) |
| OS | Windows |
| Python | 3.14.3 |
| ffmpeg | 9.0.1-full_build (gyan.dev) |

## Analysis

```powershell
$env:PYTHONPATH = "backend"
./.venv/Scripts/python.exe scripts/perf.py --stub
```

The generated demo is 180 s of synthetic video with tone audio, so `--stub` is
the comparable path: real ASR correctly transcribes nothing from tones and the
pipeline stops before scoring.

| Stage | Seconds | Peak MB | Budget MB |
|---|---|---|---|
| baseline (imported, idle) | - | 53 | - |
| audio | 0.15 | 82 | 900 |
| transcribe (stub) | 0.01 | 58 | 1400 |
| align | 0.02 | 56 | 1100 |
| windows | 0.56 | 57 | 1000 |
| signals | 0.11 | 57 | 1100 |
| gates | 0.12 | 58 | 1100 |
| score (heuristic stub) | 0.07 | 58 | 1200 |
| select | 0.08 | 60 | 1100 |
| done | 0.01 | 58 | 1200 |
| **total** | **1.12** | **82** | - |

Result: 66 windows scored, 6 clips selected, 100% reel quality on the shipped
fixture. The `windows` stage is the largest single cost because it includes the
keyframe scene pass and sentence-aligned window construction.

## Render

Measured through the running API on the longest ranked clip in the same fixture
(30.07 s), with `framing=auto`, `preset=hormozi` and `force=true`:

| Phase | Seconds |
|---|---|
| framing plan | 0.67 |
| caption pages | 0.004 |
| ffmpeg encode + mux | 5.15 |
| **job elapsed** | **5.83** |

Output: 1080x1920 H.264/AAC, 5.23 MB for 30.07 s (about 1.4 Mbps), 22 caption
pages. Encoder: `h264_amf` (the AMD hardware path passed its probe). The same
machine falls back to `libx264` at roughly half that speed when the hardware
path is unavailable.

## Frontend

`npm run build`, current tree:

| Artifact | Raw | Gzip |
|---|---|---|
| shell JS | 400.99 kB | 120.77 kB |
| CSS | 170.42 kB | 28.60 kB |
| lazy editor panels | 28.3 kB total | 10.6 kB total |

The four inspector tab panels (`CoachPanel`, `ExportPanel`, `PublishPanel`,
`SubtitleStudio`) load on first use. The dialogs and the theme atelier were
already split.

## What this does not measure

- **Real ASR and a real LLM.** Both are separate processes. Expect roughly
  +0.5 GB for `small.en`, +1.5 GB for `medium.en`, and ~2.0 GB for a 3B
  `llama-server`. `perf.py` prints a reminder when the stub is used.
- **A real VOD.** Synthetic fixtures have regular scene cuts and no music,
  crosstalk or silence. A real stream can spend longer in scene detection and
  produce fewer clips.
- **Thermals and battery.** A laptop that throttles after a minute will not
  reproduce the render figure.
- **Cold start.** The backend probes hardware encoders at startup; that probe is
  outside these stage timings.

## Reproducing a regression check

```powershell
$env:PYTHONPATH = "backend"
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe scripts/perf.py --stub
cd web
npm test
npm run build
```

Compare the analysis table and the gzip sizes. A change that raises peak memory
past a budget prints `OVER` in `perf.py`; that is a failure, not a warning.
