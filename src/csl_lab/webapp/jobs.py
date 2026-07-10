from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class JobState:
    job_id: str
    kind: str
    status: str = "queued"  # queued|running|done|error
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    message: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, JobState] = {}
        self._lock = threading.Lock()

    def create(self, kind: str) -> JobState:
        job_id = uuid.uuid4().hex[:12]
        job = JobState(job_id=job_id, kind=kind)
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> JobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **kwargs: Any) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for k, v in kwargs.items():
                setattr(job, k, v)
            job.updated_at = _utc_now()

    def run_in_thread(self, job: JobState, fn: Callable[[], dict[str, Any]]) -> None:
        def _target() -> None:
            self.update(job.job_id, status="running", message="running")
            try:
                result = fn()
                self.update(
                    job.job_id,
                    status="done",
                    message="done",
                    result=result or {},
                    error=None,
                )
            except Exception as exc:  # noqa: BLE001
                self.update(
                    job.job_id,
                    status="error",
                    message="error",
                    error=f"{exc}\n{traceback.format_exc()}",
                )

        threading.Thread(target=_target, daemon=True).start()


jobs = JobManager()
