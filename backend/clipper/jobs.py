"""Job runner with the resource governor built in.

One worker thread, globally. ASR, LLM scoring and rendering therefore can never
overlap, which is the difference between a 4.5 GB peak and a 9 GB peak on a
shared-memory machine.
"""

from __future__ import annotations

import queue
import threading
import time
import traceback
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


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

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload.pop("result", None)
        payload["elapsed"] = round(self.updated_at - self.created_at, 2)
        return payload


Task = Callable[[Callable[[str, float, str], None]], Any]


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._queue: queue.Queue[tuple[str, Task]] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()
        self._counter = 0

    def _ensure_worker(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._loop, name="clip-jobs", daemon=True)
        self._worker.start()

    def _loop(self) -> None:
        while True:
            job_id, task = self._queue.get()
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    self._queue.task_done()
                    continue
                job.status = "running"
                job.updated_at = time.time()

            def progress(stage: str, pct: float, detail: str = "") -> None:
                with self._lock:
                    current = self._jobs.get(job_id)
                    if current is None:
                        return
                    current.stage = stage
                    current.pct = round(float(pct), 4)
                    current.detail = detail
                    current.updated_at = time.time()

            try:
                result = task(progress)
                with self._lock:
                    job = self._jobs[job_id]
                    job.status = "done"
                    job.pct = 1.0
                    job.result = result
                    job.updated_at = time.time()
            except Exception as exc:  # noqa: BLE001 - surfaced to the UI verbatim
                with self._lock:
                    job = self._jobs[job_id]
                    job.status = "error"
                    job.error = f"{type(exc).__name__}: {exc}"
                    job.detail = traceback.format_exc(limit=3)[-400:]
                    job.updated_at = time.time()
            finally:
                self._queue.task_done()

    def submit(self, kind: str, task: Task) -> Job:
        self._ensure_worker()
        with self._lock:
            self._counter += 1
            job_id = f"{int(time.time() * 1000)}-{self._counter}"
            job = Job(id=job_id, kind=kind)
            self._jobs[job_id] = job
        self._queue.put((job_id, task))
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
