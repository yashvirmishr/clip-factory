"""Versioned scoring policy.

Weights and gate thresholds are still edited in ``config.py``, but an analysis
must record *which* policy produced it. The active policy is a database row: a
config change is a candidate, not an automatic promotion. That makes rollback
and A/B evaluation possible without mutating historical analyses.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from . import db
from .config import SETTINGS


@dataclass(frozen=True)
class Policy:
    version: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0

    def as_dict(self) -> dict:
        return {"version": self.version, "created_at": self.created_at, **self.payload}


def config_payload() -> dict[str, Any]:
    """The parts of SETTINGS that affect ranking and clip boundaries."""
    return {
        "weights": SETTINGS.weights.normalised(),
        "blend": asdict(SETTINGS.blend),
        "gates": asdict(SETTINGS.gates),
        "windows": asdict(SETTINGS.windows),
        "captions": asdict(SETTINGS.captions),
    }


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def version_for(payload: dict[str, Any] | None = None) -> str:
    payload = payload if payload is not None else config_payload()
    return "p_" + hashlib.sha1(_canonical(payload).encode("utf-8")).hexdigest()[:12]


def snapshot() -> Policy:
    payload = config_payload()
    return Policy(version=version_for(payload), payload=payload, created_at=time.time())


def _row_to_policy(row) -> Policy:
    try:
        payload = json.loads(row["payload"])
    except (json.JSONDecodeError, TypeError):
        payload = {}
    return Policy(version=row["version"], payload=payload, created_at=row["created_at"])


def active() -> Policy:
    """Return the promoted policy, creating one from current config if needed."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM policy_versions WHERE active=1 ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if row is not None:
        return _row_to_policy(row)
    candidate = snapshot()
    activate(candidate.version, payload=candidate.payload)
    return candidate


def activate(version: str, payload: dict[str, Any] | None = None) -> Policy:
    """Promote ``version``. Unknown versions may be inserted with a payload."""
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM policy_versions WHERE version=?", (version,)).fetchone()
        if row is None:
            if payload is None:
                raise KeyError(f"unknown policy version: {version}")
            conn.execute(
                "INSERT INTO policy_versions (version, created_at, payload, active) VALUES (?,?,?,0)",
                (version, time.time(), _canonical(payload)),
            )
            row = conn.execute("SELECT * FROM policy_versions WHERE version=?", (version,)).fetchone()
        conn.execute("UPDATE policy_versions SET active=0")
        conn.execute("UPDATE policy_versions SET active=1 WHERE version=?", (version,))
        row = conn.execute("SELECT * FROM policy_versions WHERE version=?", (version,)).fetchone()
    return _row_to_policy(row)


def list_versions() -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT version, created_at, active, payload FROM policy_versions ORDER BY created_at DESC"
        ).fetchall()
    out: list[dict] = []
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except (json.JSONDecodeError, TypeError):
            payload = {}
        out.append({
            "version": row["version"],
            "created_at": row["created_at"],
            "active": bool(row["active"]),
            "payload": payload,
        })
    return out


def clear_for_tests() -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM policy_versions")
