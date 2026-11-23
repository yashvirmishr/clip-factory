"""Peak-resident-memory sampling.

Used by ``scripts/perf.py`` so the efficiency budget is measured rather than
asserted. Windows uses the process working set via ``GetProcessMemoryInfo``;
elsewhere it falls back to ``resource``.
"""

from __future__ import annotations

import ctypes
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


_get_process_memory = None

def _resolve_windows_probe():
    """Bind K32GetProcessMemoryInfo with real argtypes.

    Without argtypes ctypes passes the pseudo-handle as a 32-bit int and the
    call silently fails, which is exactly how a memory budget ends up reporting
    zeros.
    """
    global _get_process_memory
    if _get_process_memory is not None or os.name != "nt":
        return _get_process_memory
    import ctypes.wintypes as wt

    for dll_name, symbol in (
        ("kernel32", "K32GetProcessMemoryInfo"),
        ("psapi", "GetProcessMemoryInfo"),
    ):
        try:
            dll = ctypes.WinDLL(dll_name, use_last_error=True)
            function = getattr(dll, symbol)
        except (OSError, AttributeError):
            continue
        function.argtypes = [wt.HANDLE, ctypes.POINTER(_ProcessMemoryCounters), wt.DWORD]
        function.restype = wt.BOOL
        _get_process_memory = function
        break
    return _get_process_memory


def current_rss_mb() -> float:
    if os.name == "nt":
        probe = _resolve_windows_probe()
        if probe is not None:
            import ctypes.wintypes as wt

            counters = _ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(_ProcessMemoryCounters)
            handle = ctypes.WinDLL("kernel32").GetCurrentProcess
            handle.restype = wt.HANDLE
            if probe(handle(), ctypes.byref(counters), counters.cb):
                return counters.WorkingSetSize / 1e6
    try:
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    except (ImportError, OSError):
        return 0.0


@dataclass
class MemoryTrace:
    label: str
    peak_mb: float = 0.0
    samples: list[float] = field(default_factory=list)


@contextmanager
def track(label: str, interval: float = 0.05):
    """Context manager yielding a MemoryTrace updated in a background thread."""
    trace = MemoryTrace(label=label)
    stop = threading.Event()

    def sample() -> None:
        while not stop.is_set():
            value = current_rss_mb()
            trace.samples.append(value)
            trace.peak_mb = max(trace.peak_mb, value)
            time.sleep(interval)

    thread = threading.Thread(target=sample, daemon=True)
    trace.peak_mb = current_rss_mb()
    thread.start()
    try:
        yield trace
    finally:
        stop.set()
        thread.join(timeout=1.0)
        trace.peak_mb = max(trace.peak_mb, current_rss_mb())
