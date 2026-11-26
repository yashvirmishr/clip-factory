"""Clip-quality coaching: specific, evidence-backed fixes, never silent edits.

A suggestion is a diagnosis plus evidence plus an optional reversible action.
Generation only reads the candidate. Applying a trim or hook is a separate,
explicit call and stores the previous state so it can be undone.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from . import db
from .domain import ClipCandidate, stable_id

TERMINAL = (".", "!", "?", "...")


def _evidence(
    *, quote: str = "", start: float | None = None, end: float | None = None,
    metric: str = "", value: Any = None, label: str = "",
) -> dict:
    return {
        "quote": quote,
        "start": None if start is None else round(float(start), 3),
        "end": None if end is None else round(float(end), 3),
        "metric": metric,
        "value": value,
        "label": label,
    }


def _suggestion(
    candidate: ClipCandidate, kind: str, severity: str, title: str, why: str,
    evidence: list[dict], fix: str, *, auto_fixable: bool = False,
    action: dict | None = None,
) -> dict:
    return {
        "id": "sug_" + stable_id(candidate.source_id, candidate.id, kind),
        "source_id": candidate.source_id,
        "clip_id": candidate.id,
        "kind": kind,
        "severity": severity,
        "title": title,
        "why": why,
        "evidence": [item for item in evidence if item],
        "fix": fix,
        "auto_fixable": bool(auto_fixable),
        "action": action or {},
        "status": "open",
    }


def _first_sentence(words) -> tuple[str, float, float]:
    if not words:
        return "", 0.0, 0.0
    end = 0
    for index, word in enumerate(words):
        if word.text.rstrip().endswith(TERMINAL):
            end = index
            break
    else:
        end = len(words) - 1
    selected = words[: end + 1]
    return " ".join(w.text for w in selected).strip(), selected[0].start, selected[-1].end


def _last_terminal(words):
    for word in reversed(words):
        if word.text.rstrip().endswith(TERMINAL):
            return word
    return None


def generate(candidate: ClipCandidate) -> list[dict]:
    """Deterministic checks over one clip. No model, no network, no mutation."""
    features = candidate.features
    words = candidate.words or []
    text = (candidate.text or "").strip()
    out: list[dict] = []
    if not features or not text:
        return out

    first_text, first_start, first_end = _first_sentence(words)
    first_word = words[0] if words else None

    if first_word and first_word.start - candidate.start > 0.7:
        out.append(_suggestion(
            candidate, "dead_air_start", "warn",
            "The clip opens on silence",
            f"{first_word.start - candidate.start:.1f}s pass before the first word.",
            [_evidence(
                quote=first_text[:90], start=candidate.start, end=first_word.start,
                metric="lead_in_s", value=round(first_word.start - candidate.start, 3),
                label="lead-in",
            )],
            "Start on the first word. The trim is reversible.",
            auto_fixable=True,
            action={"type": "trim", "start": round(first_word.start, 3), "end": candidate.end},
        ))

    if first_text and first_end - first_start > 4.2:
        out.append(_suggestion(
            candidate, "slow_hook", "warn",
            "The opening sentence takes too long",
            f"The first sentence runs {first_end - first_start:.1f}s before it lands.",
            [_evidence(
                quote=first_text[:140], start=first_start, end=first_end,
                metric="first_sentence_s", value=round(first_end - first_start, 3),
                label="first sentence",
            )],
            "Cut the setup and open on the claim or the payoff.",
        ))

    if (
        features.hook_lexicon_hits == 0
        and features.question_count == 0
        and features.number_count == 0
    ):
        out.append(_suggestion(
            candidate, "weak_hook", "warn",
            "The first line does not make a promise",
            "No question, number, or hook phrase appears in the clip.",
            [_evidence(
                quote=first_text[:140] or text[:140], start=first_start, end=first_end,
                metric="hook_lexicon_hits", value=0, label="hook signals",
            )],
            "Open with a question, a specific number, or a clear promise.",
        ))

    last = _last_terminal(words)
    if words and last is not None and not words[-1].text.rstrip().endswith(TERMINAL):
        out.append(_suggestion(
            candidate, "mid_sentence_end", "warn",
            "The clip stops mid-sentence",
            "The last spoken word has no terminal punctuation.",
            [_evidence(
                quote=" ".join(w.text for w in words[-8:]),
                start=last.end, end=words[-1].end,
                metric="tail_s", value=round(words[-1].end - last.end, 3),
                label="unfinished tail",
            )],
            "End on the last complete sentence.",
            auto_fixable=True,
            action={"type": "trim", "start": candidate.start, "end": round(last.end, 3)},
        ))

    if candidate.duration > 75:
        out.append(_suggestion(
            candidate, "too_long", "info",
            "This clip is longer than the attention window",
            f"{candidate.duration:.0f}s is past the point most short-form viewers leave.",
            [_evidence(
                metric="duration_s", value=round(candidate.duration, 1),
                label="clip length", quote=text[-100:],
            )],
            "Trim to the strongest 30-45s, or split it into two clips.",
        ))

    if candidate.llm is not None and not candidate.llm.has_payoff:
        out.append(_suggestion(
            candidate, "no_payoff", "warn",
            "The clip sets something up but never pays it off",
            candidate.llm.reason or "The judge did not find a resolution in the clip.",
            [_evidence(
                start=candidate.start, end=candidate.end,
                metric="has_payoff", value=False, label="payoff",
            )],
            "Keep the resolution, or cut the setup that promises one.",
        ))

    if features.speech_coverage < 0.75:
        out.append(_suggestion(
            candidate, "low_speech", "warn",
            "Part of this clip has no usable speech",
            f"Only {features.speech_coverage * 100:.0f}% of the span is covered by transcribed speech.",
            [_evidence(
                metric="speech_coverage", value=round(features.speech_coverage, 3),
                label="speech coverage",
            )],
            "Trim the silent section or add a text-only beat.",
        ))

    if features.mean_word_prob < 0.72:
        out.append(_suggestion(
            candidate, "low_asr_confidence", "info",
            "The transcript is shaky here",
            f"Mean word confidence is {features.mean_word_prob:.0%}; captions may contain errors.",
            [_evidence(
                metric="mean_word_prob", value=round(features.mean_word_prob, 3),
                label="ASR confidence", quote=first_text[:100],
            )],
            "Re-run speech recognition on a cleaner audio track before publishing.",
        ))

    if features.words_per_sec > 5.2:
        out.append(_suggestion(
            candidate, "caption_density", "info",
            "The captions will be hard to read",
            f"{features.words_per_sec:.1f} words/sec is above the comfortable caption pace.",
            [_evidence(
                metric="words_per_sec", value=round(features.words_per_sec, 2),
                label="speech rate", quote=first_text[:100],
            )],
            "Split the captions into smaller pages or slow the delivery.",
        ))

    return out


def _save(candidate: ClipCandidate, suggestions: list[dict]) -> None:
    now = time.time()
    ids = [item["id"] for item in suggestions]
    with db.connect() as conn:
        for item in suggestions:
            conn.execute(
                """
                INSERT INTO suggestions (id, source_id, clip_id, kind, severity, title, why,
                    evidence, fix, auto_fixable, action, status, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title, why=excluded.why, evidence=excluded.evidence,
                    fix=excluded.fix, auto_fixable=excluded.auto_fixable,
                    action=excluded.action, status='open', updated_at=excluded.updated_at
                WHERE suggestions.status IN ('open', 'resolved')
                """,
                (
                    item["id"], candidate.source_id, candidate.id, item["kind"], item["severity"],
                    item["title"], item["why"], json.dumps(item["evidence"]), item["fix"],
                    1 if item["auto_fixable"] else 0, json.dumps(item["action"]), "open", now, now,
                ),
            )
        # A condition that no longer exists must not keep showing an open card.
        # Applied rows stay, so their undo value is not thrown away.
        placeholders = ",".join("?" for _ in ids) if ids else "''"
        conn.execute(
            f"""UPDATE suggestions SET status='resolved', updated_at=?
                WHERE source_id=? AND clip_id=? AND status='open'
                  AND id NOT IN ({placeholders})""",
            (now, candidate.source_id, candidate.id, *ids),
        )


def refresh(candidate: ClipCandidate) -> list[dict]:
    generated = generate(candidate)
    _save(candidate, generated)
    return list_for_clip(candidate.source_id, candidate.id)


def _row(row) -> dict:
    return {
        "id": row["id"],
        "source_id": row["source_id"],
        "clip_id": row["clip_id"],
        "kind": row["kind"],
        "severity": row["severity"],
        "title": row["title"],
        "why": row["why"],
        "evidence": json.loads(row["evidence"] or "[]"),
        "fix": row["fix"],
        "auto_fixable": bool(row["auto_fixable"]),
        "action": json.loads(row["action"] or "{}"),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_for_clip(source_id: str, clip_id: str, include_closed: bool = True) -> list[dict]:
    query = "SELECT * FROM suggestions WHERE source_id=? AND clip_id=?"
    if not include_closed:
        query += " AND status='open'"
    query += " ORDER BY CASE severity WHEN 'warn' THEN 0 ELSE 1 END, created_at"
    with db.connect() as conn:
        rows = conn.execute(query, (source_id, clip_id)).fetchall()
    return [_row(row) for row in rows]


def get(suggestion_id: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM suggestions WHERE id=?", (suggestion_id,)).fetchone()
    return _row(row) if row else None


def dismiss(suggestion_id: str) -> dict:
    with db.connect() as conn:
        conn.execute(
            "UPDATE suggestions SET status='dismissed', updated_at=? WHERE id=?",
            (time.time(), suggestion_id),
        )
    item = get(suggestion_id)
    if item is None:
        raise KeyError("suggestion not found")
    return item


def preview(candidate: ClipCandidate, suggestion: dict) -> dict:
    action = suggestion.get("action") or {}
    if action.get("type") == "trim":
        start = float(action.get("start", candidate.start))
        end = float(action.get("end", candidate.end))
        kept = [
            word for word in candidate.words
            if word.end > start + 1e-6 and word.start < end - 1e-6
        ]
        return {
            "type": "trim",
            "before": {"start": candidate.start, "end": candidate.end},
            "after": {"start": round(start, 3), "end": round(end, 3)},
            "before_text": candidate.text,
            "after_text": " ".join(word.text for word in kept).strip(),
            "duration_s": round(max(0.0, end - start), 3),
        }
    if action.get("type") == "hook":
        current = candidate.llm.hook if candidate.llm else ""
        return {
            "type": "hook",
            "before": {"hook": current},
            "after": {"hook": action.get("hook", "")},
            "before_text": current,
            "after_text": action.get("hook", ""),
        }
    return {"type": "none", "before": {}, "after": {}, "before_text": candidate.text, "after_text": candidate.text}


def apply(
    source_id: str,
    clip_id: str,
    suggestion_id: str,
    *,
    trim_fn: Callable[[float, float], ClipCandidate] | None = None,
    hook_fn: Callable[[str], None] | None = None,
    candidate: ClipCandidate | None = None,
) -> dict:
    item = get(suggestion_id)
    if item is None:
        raise KeyError("suggestion not found")
    if item["clip_id"] != clip_id or item["source_id"] != source_id:
        raise KeyError("suggestion does not belong to this clip")
    if item["status"] == "applied":
        return {"suggestion": item, "changed": False, "reason": "already applied"}
    action = item["action"]
    if not action or not item["auto_fixable"]:
        raise ValueError("this suggestion needs a manual edit; preview it first")
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    if action.get("type") == "trim":
        if trim_fn is None:
            from . import service
            from . import db as database

            source = database.get_source(source_id)
            if source is None:
                raise KeyError("source not found")
            trim_fn = lambda start, end: service.trim_clip(source, clip_id, start, end)
        current = candidate
        before = {"start": current.start, "end": current.end} if current else {}
        updated = trim_fn(float(action["start"]), float(action["end"]))
        after = {"start": updated.start, "end": updated.end}
    elif action.get("type") == "hook":
        if hook_fn is None:
            def hook_fn(value: str) -> None:
                db.save_clip_edit(source_id, clip_id, "hook", {"hook": value})
        current = candidate
        before = {"hook": current.llm.hook if current and current.llm else ""}
        hook_fn(str(action.get("hook", "")))
        after = {"hook": action.get("hook", "")}
    else:
        raise ValueError("unsupported suggestion action")

    action = dict(action)
    action["before"] = before
    with db.connect() as conn:
        conn.execute(
            "UPDATE suggestions SET status='applied', action=?, updated_at=? WHERE id=?",
            (json.dumps(action), time.time(), suggestion_id),
        )
    return {"suggestion": get(suggestion_id), "changed": True, "before": before, "after": after}


def undo(
    source_id: str,
    clip_id: str,
    suggestion_id: str,
    *,
    trim_fn: Callable[[float, float], ClipCandidate] | None = None,
    hook_fn: Callable[[str], None] | None = None,
) -> dict:
    item = get(suggestion_id)
    if item is None:
        raise KeyError("suggestion not found")
    if item["clip_id"] != clip_id or item["source_id"] != source_id:
        raise KeyError("suggestion does not belong to this clip")
    if item["status"] != "applied":
        raise ValueError("only an applied suggestion can be undone")
    action = item["action"]
    before = action.get("before") or {}
    if action.get("type") == "trim":
        if trim_fn is None:
            from . import service
            from . import db as database

            source = database.get_source(source_id)
            if source is None:
                raise KeyError("source not found")
            trim_fn = lambda start, end: service.trim_clip(source, clip_id, start, end)
        trim_fn(float(before["start"]), float(before["end"]))
    elif action.get("type") == "hook":
        if hook_fn is None:
            def hook_fn(value: str) -> None:
                db.save_clip_edit(source_id, clip_id, "hook", {"hook": value})
        hook_fn(str(before.get("hook", "")))
    action = dict(action)
    action["before"] = {}
    with db.connect() as conn:
        conn.execute(
            "UPDATE suggestions SET status='open', action=?, updated_at=? WHERE id=?",
            (json.dumps(action), time.time(), suggestion_id),
        )
    return {"suggestion": get(suggestion_id), "undone": True}
