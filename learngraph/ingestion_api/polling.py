from __future__ import annotations

import time
from dataclasses import dataclass

from .client import IngestionApiClient
from .types import IngestionJob


TERMINAL_STATUSES = {"succeeded", "failed"}


def is_job_complete(job: IngestionJob) -> bool:
    return (job.stage == "completed") or (job.status in TERMINAL_STATUSES)


@dataclass(frozen=True)
class PollingConfig:
    interval_seconds: float = 5.0
    timeout_seconds: float | None = None


class PollTimeoutError(TimeoutError):
    pass


def wait_for_job(client: IngestionApiClient, job_id: str, cfg: PollingConfig) -> IngestionJob:
    started = time.monotonic()
    # Mirror web behavior: immediate refresh, then periodic polling.
    while True:
        job = client.get_job(job_id)
        if is_job_complete(job):
            return job
        if cfg.timeout_seconds is not None:
            elapsed = time.monotonic() - started
            if elapsed >= cfg.timeout_seconds:
                raise PollTimeoutError(f"Timed out waiting for job {job_id}")
        time.sleep(cfg.interval_seconds)

