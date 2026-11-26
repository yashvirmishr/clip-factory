"""Measure the real cost of the pipeline, stage by stage.

    python scripts/perf.py [path-to-video] [--stub]

Prints duration and peak resident memory per stage against the budgets the
design promises. Nothing here is estimated: if a number is wrong, fix the code
or fix the budget, not the number.

``--stub`` forces the deterministic stub transcript. Use it for the shipped
demo: its audio is tones, not speech, so a real whisper model correctly finds
nothing and the pipeline stops before scoring. Pass a real video to measure a
real model.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("CLIPPER_DATA_DIR", str(ROOT / "data"))

from clipper import db, demo, service  # noqa: E402
from clipper.config import SETTINGS  # noqa: E402
from clipper.rt import current_rss_mb  # noqa: E402

BUDGETS = {
    "audio": 900.0,
    "transcribe": 1400.0,
    "align": 1100.0,
    "windows": 1000.0,
    "signals": 1100.0,
    "gates": 1100.0,
    "score": 1200.0,
    "select": 1100.0,
    "done": 1200.0,
}


def main() -> int:
    flags = {arg for arg in sys.argv[1:] if arg.startswith("-")}
    paths = [arg for arg in sys.argv[1:] if not arg.startswith("-")]
    if "--stub" in flags:
        # The demo's audio is a tone, not speech. Real ASR returns no words and
        # the run stops at zero windows, which measures nothing. This makes the
        # fixture's synthetic transcript the measured path.
        from clipper.pipeline.asr import WhisperCppASR

        WhisperCppASR.available = lambda self: False  # type: ignore[method-assign]

    db.init()
    if paths:
        path = Path(paths[0])
    else:
        path = demo.generate(SETTINGS.media_dir(), seconds=180)
        print(f"using generated demo clip: {path}")

    source = service.ingest(path, path.name)

    samples: list[tuple[float, float]] = []
    marks: list[tuple[float, str]] = []
    stop = threading.Event()

    def sampler() -> None:
        while not stop.is_set():
            samples.append((time.monotonic(), current_rss_mb()))
            time.sleep(0.03)

    thread = threading.Thread(target=sampler, daemon=True)
    baseline = current_rss_mb()
    thread.start()

    def progress(stage: str, pct: float, detail: str = "") -> None:
        if not marks or marks[-1][1] != stage:
            marks.append((time.monotonic(), stage))

    started = time.monotonic()
    result = service.analyze(source, limit=8, progress=progress, force=True)
    elapsed = time.monotonic() - started
    stop.set()
    thread.join(timeout=1.0)

    marks.append((time.monotonic(), "done"))

    print(f"\nsource      {source.name}  {source.duration:.1f}s")
    print(f"asr         {result.asr_backend}")
    print(f"llm         {result.llm_backend}")
    print(f"windows     {len(result.candidates)} scored, {sum(1 for c in result.candidates if c.rank)} selected")
    print(f"reel        {result.reel_quality * 100:.0f}% quality scorecard")
    print(f"baseline    {baseline:.0f} MB resident before any work\n")

    header = f"{'stage':<12}{'seconds':>9}{'peak MB':>10}{'budget':>9}{'':>6}"
    print(header)
    print("-" * len(header))
    worst = 0.0
    for (t0, stage), (t1, _) in zip(marks, marks[1:]):
        window = [mb for ts, mb in samples if t0 <= ts <= t1]
        peak = max(window) if window else current_rss_mb()
        worst = max(worst, peak)
        budget = BUDGETS.get(stage, 1500.0)
        flag = "ok" if peak <= budget else "OVER"
        print(f"{stage:<12}{t1 - t0:>9.2f}{peak:>10.0f}{budget:>9.0f}{flag:>6}")
    print("-" * len(header))
    print(f"{'total':<12}{elapsed:>9.2f}{worst:>10.0f}")

    if result.asr_backend == "stub":
        print(
            "\nnote: stub ASR was used, so the transcribe figure excludes the whisper\n"
            "      process. Expect roughly +0.5 GB (small.en) to +1.5 GB (medium.en)."
        )
    elif not any(candidate.rank for candidate in result.candidates):
        print(
            "\nnote: no clips came out. The generated demo contains tones, not speech,\n"
            "      so real ASR correctly transcribes nothing. Re-run with --stub for\n"
            "      the pipeline baseline, or pass a real video to measure ASR."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
