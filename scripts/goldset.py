"""Score pick quality against hand-labelled moments.

    ./.venv/Scripts/python.exe scripts/goldset.py benchmarks/gold/demo-stream.json
    ./.venv/Scripts/python.exe scripts/goldset.py benchmarks/gold --limit 5 --json

The shipped demo's audio is tones, so a real model correctly finds nothing.
``--stub`` scores it on the deterministic transcript the labels were written
against; ``--min-f1`` turns the result into a gate instead of a report.

A gold file is JSON:

    {"source": "stream.mp4",
     "notes": "why these moments",
     "moments": [{"start": 51.6, "end": 63.7, "label": "the bit about X"}]}

The source is resolved next to the gold file first, then in the app media folder,
then via ``--video``. Analysis is re-run with ``force`` so the number describes
the current pipeline rather than a cached result - a benchmark that silently
scores yesterday's code is worse than none.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

os.environ.setdefault("CLIPPER_DATA_DIR", str(Path.cwd() / "data"))

from clipper import bench, db, demo, service  # noqa: E402
from clipper.config import SETTINGS  # noqa: E402


def resolve_video(gold_path: Path, name: str, override: str | None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    for candidate in (
        gold_path.parent / name,
        SETTINGS.media_dir() / name,
        Path.cwd() / name,
    ):
        if candidate.exists():
            return candidate.resolve()
    raise SystemExit(
        f"could not find {name!r} for {gold_path.name}: pass --video, or drop the file "
        f"next to the gold file / in {SETTINGS.media_dir()}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pick-quality benchmark")
    parser.add_argument("gold", help="a gold .json file or a directory of them")
    parser.add_argument("--video", default=None, help="source video override")
    parser.add_argument("--limit", type=int, default=5, help="clips to score (default 5)")
    parser.add_argument("--threshold", type=float, default=bench.DEFAULT_THRESHOLD)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--quiet", action="store_true", help="only the totals")
    parser.add_argument(
        "--stub",
        action="store_true",
        help="force the deterministic stub transcript (use for the shipped demo)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="generate the shipped demo when the source is missing",
    )
    parser.add_argument(
        "--min-f1",
        type=float,
        default=None,
        help="exit 1 when mean F1 is below this value",
    )
    args = parser.parse_args(argv)

    if args.stub:
        # The demo's audio is a tone, not speech. Real ASR returns no words and
        # the run stops before scoring, which measures nothing.
        from clipper.pipeline.asr import WhisperCppASR

        WhisperCppASR.available = lambda self: False  # type: ignore[method-assign]

    if args.demo and not args.video:
        args.video = str(demo.generate(SETTINGS.media_dir()))

    db.init()
    target = Path(args.gold)
    fixtures = [(target, bench.load(target))] if target.is_file() else bench.discover(target)
    if not fixtures:
        raise SystemExit(f"no gold files under {target}")

    rows = []
    for path, gold in fixtures:
        video = resolve_video(path, gold.source, args.video)
        if not video.exists():
            rows.append({"fixture": path.stem, "error": f"missing source {video}"})
            continue
        if not args.quiet:
            print(f"\n{path.name}  {video.name}  ({gold.notes[:70]}...)" if gold.notes else f"\n{path.name}")
        source = service.ingest(video, gold.source)
        result = service.analyze(source, limit=max(args.limit, 6), force=True)
        report = bench.evaluate_result(result, gold, limit=args.limit, threshold=args.threshold)
        rows.append({"fixture": path.stem, **report.to_dict()})
        if args.quiet:
            print(report.summary_line(path.stem))
        else:
            print("  " + report.summary_line(path.stem))
            for match in report.matches:
                flag = "dup" if match.duplicate else "hit"
                print(
                    f"    {flag}  clip {match.clip_start:7.1f}-{match.clip_end:7.1f}  "
                    f"cov {match.overlap:4.2f}  {match.gold.label[:56]}"
                )
            for moment in report.missing:
                print(f"    miss  {moment.start:7.1f}-{moment.end:7.1f}          {moment.label[:56]}")

    scored = [row for row in rows if "error" not in row]
    if scored:
        mean_p = sum(row["precision"] for row in scored) / len(scored)
        mean_r = sum(row["recall"] for row in scored) / len(scored)
        totals = {
            "fixtures": len(scored),
            "mean_precision": round(mean_p, 4),
            "mean_recall": round(mean_r, 4),
            "mean_f1": round(
                sum(row["f1"] for row in scored) / len(scored), 4
            ),
        }
    else:
        totals = {"fixtures": 0}

    if args.json:
        print(json.dumps({"totals": totals, "fixtures": rows}, indent=2))
    else:
        print(
            f"\nmean over {totals['fixtures']} fixture(s): "
            f"P@k {totals.get('mean_precision', 0):.2f}  "
            f"R {totals.get('mean_recall', 0):.2f}  F1 {totals.get('mean_f1', 0):.2f}"
        )

    errors = [row for row in rows if "error" in row]
    for row in errors:
        print(f"error: {row['fixture']}: {row['error']}", file=sys.stderr)
    if errors:
        return 1
    if args.min_f1 is not None and totals.get("mean_f1", 0.0) < args.min_f1:
        print(
            f"error: mean F1 {totals.get('mean_f1', 0.0):.2f} is below --min-f1 {args.min_f1:.2f}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
