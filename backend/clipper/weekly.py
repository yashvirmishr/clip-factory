"""The weekly self-improvement loop.

Everything here is local and opt-in by virtue of connecting an account. The
loop runs while the desktop app is open; a closed app simply resumes next time.
"""

from __future__ import annotations

import os
import threading
import time

from . import accounts, analytics, db, personal

INTERVAL_S = 7 * 24 * 3600
STATE_KEY = "weekly_learning"
_stop = threading.Event()
_thread: threading.Thread | None = None
_run_lock = threading.Lock()
_running = False


def status(now: float | None = None) -> dict:
    now = now or time.time()
    state = db.get_state(STATE_KEY, {}) or {}
    last = float(state.get("last_run", 0) or 0)
    next_run = float(state.get("next_run", 0) or 0)
    return {
        "last_run": last,
        "next_run": next_run,
        "due": not last or now >= next_run,
        "interval_days": 7,
        "results": state.get("results", []),
        "training": personal.state(""),
        "running": _running,
    }


def run(now: float | None = None) -> dict:
    global _running
    now = now or time.time()
    # The daemon and the button share one cycle. A second caller waits instead
    # of hitting every platform twice.
    with _run_lock:
        _running = True
        try:
            results = []
            for account in accounts.list_accounts():
                try:
                    summary = analytics.sync_account(account.id, now=now)
                    results.append({
                        "account_id": account.id,
                        "platform": account.platform,
                        "display_name": account.display_name,
                        "ok": True,
                        "new_posts": summary.get("new_posts", 0),
                        "labels": summary.get("labels", {}),
                    })
                except Exception as exc:  # noqa: BLE001 - one bad platform must not stop the loop
                    results.append({
                        "account_id": account.id,
                        "platform": account.platform,
                        "display_name": account.display_name,
                        "ok": False,
                        "error": str(exc)[:300],
                    })
            training = personal.train("", now=now)
            state = {
                "last_run": now,
                "next_run": now + INTERVAL_S,
                "results": results,
                "training": training,
            }
            db.set_state(STATE_KEY, state)
            return state
        finally:
            _running = False


def start() -> bool:
    """Start the daemon loop once. Returns False when disabled or already running."""
    global _thread
    if os.environ.get("CLIPPER_DISABLE_WEEKLY") == "1":
        return False
    if _thread is not None and _thread.is_alive():
        return False
    _stop.clear()

    def loop() -> None:
        # Give startup, migrations and the encoder probe room before touching
        # the network.
        if _stop.wait(20):
            return
        while not _stop.is_set():
            try:
                if status()["due"]:
                    run()
            except Exception:  # noqa: BLE001 - the loop retries next hour
                pass
            if _stop.wait(3600):
                return

    _thread = threading.Thread(target=loop, name="clip-weekly-learning", daemon=True)
    _thread.start()
    return True


def stop() -> None:
    _stop.set()


def clear_for_tests() -> None:
    db.set_state(STATE_KEY, {})
