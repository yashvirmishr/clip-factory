import threading
import time

from clipper.jobs import JobManager


def wait_for(predicate, timeout=4.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_queued_job_is_cancelled_without_running():
    manager = JobManager()
    started = threading.Event()
    release = threading.Event()

    def blocker(progress):
        started.set()
        release.wait(5)
        return "first"

    first = manager.submit("test", blocker)
    assert started.wait(2)

    second = manager.submit("test", lambda progress: "second")
    assert second.status == "queued"
    cancelled = manager.cancel(second.id)
    assert cancelled is not None
    assert cancelled.status == "cancelled"

    release.set()
    assert wait_for(lambda: first.status == "done")
    # The worker skips a job that was cancelled while it sat in the queue.
    assert manager.get(second.id).status == "cancelled"


def test_running_job_stops_at_the_next_progress_checkpoint():
    manager = JobManager()
    started = threading.Event()

    def long_task(progress):
        started.set()
        for step in range(400):
            time.sleep(0.01)
            progress("working", step / 400)
        return "finished"

    job = manager.submit("test", long_task)
    assert started.wait(2)
    manager.cancel(job.id)
    assert job.cancel_requested is True

    assert wait_for(lambda: manager.get(job.id).status == "cancelled", timeout=4)
    assert manager.get(job.id).detail == "Cancelled"


def test_cancel_unknown_job_returns_none():
    manager = JobManager()
    assert manager.cancel("missing") is None
