"""Demo fixtures and the optional training-set export.

The demo generator makes a synthetic stream-shaped video with ffmpeg, so the
whole app is explorable on a machine with no models, no media and no network.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import db
from .llm.prompts import SYSTEM_PROMPT

DEMO_SECONDS = 180

# Smooth amplitude modulation with deep troughs: exercises the speech mask
# without needing real speech. No commas - ffmpeg's filter parser would split
# them as option separators.
_AUDIO_EXPR = (
    "0.16*sin(2*PI*200*t)"
    "*(0.55+0.45*sin(2*PI*0.25*t))"
    "*(0.5+0.5*sin(2*PI*0.09*t))"
)


def generate(target_dir: Path, seconds: int = DEMO_SECONDS) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    out = target_dir / "demo-stream.mp4"
    if out.exists() and out.stat().st_size > 10_000:
        return out
    audio_src = f"aevalsrc={_AUDIO_EXPR}:s=16000:d={seconds}"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size=960x540:rate=30:duration={seconds}",
        "-f", "lavfi", "-i", audio_src,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k",
        "-shortest", str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:400] or "ffmpeg failed")
    return out


def build_training_export() -> list[str]:
    """JSONL: SFT pairs from approvals, DPO triples from hook edits.

    Exported, not trained in-app. Under ~1,000 clean examples few-shot
    prompting beats a LoRA, and the UI says so.
    """
    lines: list[str] = []
    for row in db.list_decisions(limit=10000):
        if row.get("action") != "approve" or not row.get("text"):
            continue
        judgement = {
            "score": row.get("llm_score") or 0,
            "hook": row.get("hook", ""),
            "title": "",
            "reason": row.get("reason", "") or "creator approved this clip",
            "understands_standalone": True,
            "has_payoff": True,
        }
        lines.append(
            json.dumps(
                {
                    "type": "sft",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": row["text"]},
                        {"role": "assistant", "content": json.dumps(judgement)},
                    ],
                }
            )
        )
    for edit in db.list_hook_edits(limit=10000):
        if not edit.get("before") or not edit.get("after"):
            continue
        lines.append(
            json.dumps(
                {
                    "type": "dpo",
                    "prompt": "Rewrite this hook the way the creator would.",
                    "chosen": edit["after"],
                    "rejected": edit["before"],
                }
            )
        )
    return lines
