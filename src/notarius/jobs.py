"""Long jobs (transcribe, enroll, speed test) run in a separate process.

A separate process keeps the app responsive, releases every byte of model
memory when the job ends, and can be cancelled by terminating it.  The
worker reports through a small JSON status file the app polls.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from notarius.config import APP_DIR

JOBS_DIR = APP_DIR / "jobs"


@dataclass
class JobStatus:
    id: str
    kind: str  # "transcribe" | "enroll" | "enroll-files" | "tune"
    params: dict
    state: str = "running"  # running | done | failed | cancelled
    stage: str = "start"
    message: str = ""
    started: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    expected_seconds: float | None = None
    result: dict | None = None
    error: str | None = None


def write_status(path: Path, status: JobStatus) -> None:
    status.updated = time.time()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(status), ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def read_status(path: Path) -> JobStatus | None:
    try:
        return JobStatus(**json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None


class JobRunner:
    """At most one job at a time; the app's single point of control."""

    def __init__(self, jobs_dir: Path = JOBS_DIR) -> None:
        self.jobs_dir = jobs_dir
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._status_path: Path | None = None

    def start(self, kind: str, params: dict, expected_seconds: float | None = None) -> JobStatus:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                raise RuntimeError("busy")
            job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
            status_path = self.jobs_dir / f"{job_id}.json"
            status = JobStatus(job_id, kind, params, expected_seconds=expected_seconds)
            write_status(status_path, status)
            log_path = status_path.with_suffix(".log")
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            with log_path.open("w", encoding="utf-8") as log:
                self._proc = subprocess.Popen(
                    [sys.executable, "-m", "notarius.worker", str(status_path)],
                    stdout=log, stderr=subprocess.STDOUT, env=env, creationflags=flags,
                )
            self._status_path = status_path
            return status

    def current(self) -> JobStatus | None:
        """Status of the running or most recent job."""
        with self._lock:
            if self._status_path is None:
                return None
            status = read_status(self._status_path)
            if status and status.state == "running" and self._proc and self._proc.poll() is not None:
                # The worker died without reporting (crash, out of memory).
                status.state = "failed"
                status.error = status.error or "crashed"
                write_status(self._status_path, status)
            return status

    def cancel(self) -> None:
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                return
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            status = read_status(self._status_path) if self._status_path else None
            if status:
                status.state = "cancelled"
                write_status(self._status_path, status)

    def dismiss(self) -> None:
        """Forget a finished job so the home page stops showing it."""
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                self._status_path = None
                self._proc = None
