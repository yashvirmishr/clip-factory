"""Job runner with the resource governor built in.

Two lanes, globally. Everything that runs ffmpeg, whisper or the LLM shares one
"compute" worker, so ASR, scoring and rendering can never overlap - that is the
difference between a 4.5 GB peak and a 9 GB peak on a shared-memory machine.
Network-shaped work (downloads, uploads) runs on its own single "io" worker so a
2 GB VOD fetch no longer blocks an analysis that is already paid for.

Each job also records how long it spent in each stage, so "analysis is slow" can
be answered with numbers instead of guesses.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import traceback
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

COMPUTE = "compute"
IO = "io"

# Downloads, uploads and tool installs are network/disk shaped and
# memory-light, so they get their own lane. Everything else (and any unknown
# kind) stays serialised.
_IO_KINDS = frozenset({"download", "publish", "proxy", "tool"})


def lane_for(kind: str) -> str:
    return IO if kind in _IO_KINDS else COMPUTE


class JobCancelled(Exception):
    """Raised inside a task at the next progress checkpoint after a cancel."""


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"  # queued | running | done | error
    stage: str = ""
    pct: float = 0.0
    detail: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    result: Any = None
    cancel_requested: bool = False
    lane: str = COMPUTE
    timings: dict[str, float] = field(default_factory=dict)
    stage_started: float = 0.0

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload.pop("result", None)
        payload.pop("stage_started", None)
        payload["elapsed"] = round(self.updated_at - self.created_at, 2)
        payload["cancelling"] = self.cancel_requested and self.status == "running"
        return payload


Task = Callable[[Callable[[str, float, str], None]], Any]


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._queues: dict[str, queue.Queue[tuple[str, Task]]] = {
            COMPUTE: queue.Queue(),
            IO: queue.Queue(),
        }
        self._workers: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self._counter = 0

    def _ensure_worker(self, lane: str) -> None:
        worker = self._workers.get(lane)
        if worker and worker.is_alive():
            return
        self._workers[lane] = threading.Thread(
            target=self._loop, args=(lane,), name=f"clip-jobs-{lane}", daemon=True
        )
        self._workers[lane].start()

    @staticmethod
    def _close_stage(job: Job, now: float) -> None:
        """Bank the time spent in the stage that just ended."""

        if job.stage and job.stage_started:
            spent = job.timings.get(job.stage, 0.0) + (now - job.stage_started)
            job.timings[job.stage] = round(spent, 3)

    def _loop(self, lane: str) -> None:
        work = self._queues[lane]
        while True:
            job_id, task = work.get()
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None or job.status == "cancelled":
                    work.task_done()
                    continue
                job.status = "running"
                job.stage_started = time.time()
                job.updated_at = job.stage_started
                logger.info("job %s (%s) started on the %s lane", job_id, job.kind, lane)

            def progress(stage: str, pct: float, detail: str = "", _job_id=job_id) -> None:
                with self._lock:
                    current = self._jobs.get(_job_id)
                    if current is None:
                        return
                    if current.cancel_requested:
                        raise JobCancelled()
                    now = time.time()
                    if stage != current.stage:
                        self._close_stage(current, now)
                        current.stage = stage
                        current.stage_started = now
                    current.pct = round(float(pct), 4)
                    current.detail = detail
                    current.updated_at = now

            try:
                result = task(progress)
                with self._lock:
                    job = self._jobs[job_id]
                    self._close_stage(job, time.time())
                    job.stage_started = 0.0
                    job.status = "done"
                    job.pct = 1.0
                    job.result = result
                    job.updated_at = time.time()
                    logger.info(
                        "job %s (%s) finished in %.1fs %s",
                        job_id,
                        job.kind,
                        job.updated_at - job.created_at,
                        self._format_timings(job.timings),
                    )
            except JobCancelled:
                with self._lock:
                    job = self._jobs[job_id]
                    self._close_stage(job, time.time())
                    job.stage_started = 0.0
                    job.status = "cancelled"
                    job.detail = "Cancelled"
                    job.updated_at = time.time()
                    logger.info("job %s (%s) cancelled", job_id, job.kind)
            except Exception as exc:  # noqa: BLE001 - surfaced to the UI verbatim
                with self._lock:
                    job = self._jobs[job_id]
                    self._close_stage(job, time.time())
                    job.stage_started = 0.0
                    job.status = "error"
                    job.error = f"{type(exc).__name__}: {exc}"
                    job.detail = traceback.format_exc(limit=3)[-400:]
                    job.updated_at = time.time()
                    logger.exception("job %s (%s) failed", job_id, job.kind)
            finally:
                work.task_done()

    @staticmethod
    def _format_timings(timings: dict[str, float]) -> str:
        if not timings:
            return ""
        return " ".join(f"{name}={seconds:.1f}s" for name, seconds in timings.items())

    def submit(self, kind: str, task: Task) -> Job:
        lane = lane_for(kind)
        self._ensure_worker(lane)
        with self._lock:
            self._counter += 1
            job_id = f"{int(time.time() * 1000)}-{self._counter}"
            job = Job(id=job_id, kind=kind, lane=lane)
            self._jobs[job_id] = job
        logger.info("job %s (%s) queued on the %s lane", job_id, kind, lane)
        self._queues[lane].put((job_id, task))
        return job

    def cancel(self, job_id: str) -> Job | None:
        """Request cancellation.

        Queued jobs are dropped immediately. Running jobs keep their status and
        flip the cancel flag; the task stops at its next progress callback and
        the worker marks it cancelled. Long native calls (ffmpeg, whisper)
        therefore finish their current step before the job settles.
        """

        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status in ("done", "error", "cancelled"):
                return job
            job.cancel_requested = True
            job.updated_at = time.time()
            if job.status == "queued":
                job.status = "cancelled"
                job.detail = "Cancelled before it started"
            else:
                job.detail = "Cancelling..."
            logger.info("job %s (%s) cancel requested", job_id, job.kind)
            return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def result(self, job_id: str) -> Any:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.result if job else None

    def list(self, limit: int = 20) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return [j.to_dict() for j in jobs[:limit]]

    def busy(self) -> bool:
        with self._lock:
            return any(j.status in ("queued", "running") for j in self._jobs.values())


JOBS = JobManager()
