# Contributing

Clip Factory is a local-first Python + React app. Keep changes small, keep the
existing behaviour unless the task is explicitly to change it, and leave user
edits in the working tree alone.

The full development guide - where things live, how to add an endpoint, a
command or a theme, and the frontend conventions - is
[docs/wiki/Development.md](docs/wiki/Development.md). This page is the short
version.

## Setup

```powershell
py -3 -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
cd web
npm install
```

Optional face tracking needs the packages in `requirements-optional.txt`, and a
YuNet model. Nothing else is optional.

## Gates

Run these before opening a pull request:

```powershell
$env:PYTHONPATH = "backend"
./.venv/Scripts/python.exe -m pytest -q

./.venv/Scripts/python.exe scripts/copy-lint.py

cd web
npm test
npm run build
```

`pytest` includes a few real encodes and takes a minute; `-m "not slow"` skips
them for a fast pass. `npm run build` is also the TypeScript typecheck.
`scripts/copy-lint.py` checks user-facing copy, and CI runs all four gates.

For a performance or pick-quality change, also run:

```powershell
$env:PYTHONPATH = "backend"
./.venv/Scripts/python.exe scripts/perf.py --stub
./.venv/Scripts/python.exe scripts/goldset.py benchmarks/gold/demo-stream.json
```

The current numbers are in [docs/perf-baseline.md](docs/perf-baseline.md). A
change that prints `OVER` against a memory budget is a regression.

## What a change needs

- **A test for behaviour that can regress.** The backend uses FastAPI's test
  client and temporary fixtures; the frontend uses Vitest for logic that a
  screenshot cannot show. Pure layout changes can be verified by hand.
- **No new runtime dependency** unless the platform or React cannot reasonably
  do the job. The app ships React plus Vite.
- **No dead controls.** A button performs its action, is disabled with a reason
  nearby, or does not exist.
- **Plain CSS and semantic tokens.** No Tailwind, no CSS-in-JS, no hardcoded
  colours in components.
- **Honest docs.** If a capability is absent, say so in
  [Limitations](docs/wiki/Limitations.md) rather than implying it exists. Update
  the README and wiki when a number, a preset or a command changes.
- **No generated data.** Do not commit renders, model weights, a populated
  `data/`, `.tmp-run/` or test scratch directories.

## Commits

Use a short imperative subject, optionally with a conventional prefix, and say
what changed and why in the body when the diff is not obvious:

```text
fix(publish): keep feature vectors server-side and guard retries
docs: correct the two-lane job model
```

One logical change per commit. Do not reformat unrelated files in the same
commit.

## License

By contributing you agree that your contribution is licensed under the
[MIT License](LICENSE).
