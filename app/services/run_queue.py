"""Background run execution — an in-process task queue for pipeline runs.

This backs the **async bonus** (spec §4.2): ``POST /run?async=true`` enqueues a
run and returns immediately with ``status: "queued"``; a background worker then
executes the DAG and transitions the run to ``running`` and finally to a terminal
state, which the caller polls via ``GET /api/v1/runs/{run_uuid}``.

Design
------
The queue is deliberately abstracted behind :class:`RunQueue` so the execution
backend is swappable. The default :class:`ThreadPoolRunQueue` runs jobs in an
in-process :class:`~concurrent.futures.ThreadPoolExecutor` — real background
execution with **no external broker**, so the system still runs from a single
command with zero credentials. For a horizontally-scaled production deployment
the same interface is satisfied by a Celery/RQ-backed implementation (the worker
function is already a plain ``(run_uuid: str) -> None`` callable); see the README.

Robustness
----------
The worker callable is expected to own its own database sessions and to record
terminal state itself. This module adds a defensive outer guard so that an
unexpected exception in a worker is logged and never escapes to crash the pool
thread.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from app.config import Settings, get_settings
from app.observability.logging import get_logger

_logger = get_logger("service.run_queue")

# A worker executes a single run identified by its UUID.
RunWorker = Callable[[str], None]


class RunQueue(ABC):
    """Abstract submit/shutdown interface for background run execution."""

    @abstractmethod
    def submit(self, run_uuid: str) -> None:
        """Schedule ``run_uuid`` for background execution."""

    @abstractmethod
    def shutdown(self, *, wait: bool = False) -> None:
        """Stop accepting work and release resources."""


class ThreadPoolRunQueue(RunQueue):
    """A :class:`RunQueue` backed by an in-process thread pool."""

    def __init__(self, worker: RunWorker, *, max_workers: int) -> None:
        self._worker = worker
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="run-worker"
        )
        self._shutdown = False

    def submit(self, run_uuid: str) -> None:
        if self._shutdown:  # pragma: no cover - defensive
            raise RuntimeError("run queue is shut down")
        self._executor.submit(self._guarded, run_uuid)

    def _guarded(self, run_uuid: str) -> None:
        """Run the worker, ensuring no exception escapes the pool thread."""
        try:
            self._worker(run_uuid)
        except Exception:  # pragma: no cover - worker marks failure itself
            _logger.exception("run_queue.worker_crashed", run_uuid=run_uuid)

    def shutdown(self, *, wait: bool = False) -> None:
        self._shutdown = True
        self._executor.shutdown(wait=wait, cancel_futures=not wait)


# --------------------------------------------------------------------------- #
# Process-wide queue accessor
# --------------------------------------------------------------------------- #
_run_queue: RunQueue | None = None


def init_run_queue(settings: Settings | None = None) -> RunQueue:
    """Initialize (or replace) the process-wide run queue and return it."""
    global _run_queue
    settings = settings or get_settings()
    # Late import keeps this module free of a hard dependency on the service that
    # imports it (the worker is injected, not imported at module load).
    from app.services.pipeline_service import execute_run

    if _run_queue is not None:
        _run_queue.shutdown(wait=False)
    _run_queue = ThreadPoolRunQueue(execute_run, max_workers=settings.run_worker_concurrency)
    return _run_queue


def get_run_queue() -> RunQueue:
    """Return the process-wide run queue, lazily initializing it on first use."""
    if _run_queue is None:
        return init_run_queue()
    return _run_queue


def shutdown_run_queue(*, wait: bool = False) -> None:
    """Shut down and clear the process-wide run queue (used on app shutdown)."""
    global _run_queue
    if _run_queue is not None:
        _run_queue.shutdown(wait=wait)
        _run_queue = None


def set_run_queue(queue: RunQueue | None) -> None:
    """Inject a specific queue (used by tests); pass ``None`` to reset."""
    global _run_queue
    _run_queue = queue


__all__ = [
    "RunQueue",
    "RunWorker",
    "ThreadPoolRunQueue",
    "get_run_queue",
    "init_run_queue",
    "set_run_queue",
    "shutdown_run_queue",
]
