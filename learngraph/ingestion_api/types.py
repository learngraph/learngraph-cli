from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


JobStatus = Literal["queued", "running", "succeeded", "failed"]
JobType = Literal["resource_ingestion", "topic_ingestion", "feedback_ingestion"]


@dataclass(frozen=True)
class IngestionJobAcceptedResponse:
    job_id: str
    status: JobStatus


@dataclass(frozen=True)
class IngestionJobResult:
    central_topic_id: str | None = None
    created_topic_ids: list[str] | None = None
    reused_topic_ids: list[str] | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "IngestionJobResult":
        return IngestionJobResult(
            central_topic_id=payload.get("central_topic_id"),
            created_topic_ids=payload.get("created_topic_ids"),
            reused_topic_ids=payload.get("reused_topic_ids"),
            tokens_in=payload.get("tokens_in"),
            tokens_out=payload.get("tokens_out"),
        )


@dataclass(frozen=True)
class IngestionJob:
    job_id: str
    type: JobType
    status: JobStatus
    created_at: str
    stage: str | None = None
    progress: str | None = None
    error: str | None = None
    warnings: list[str] | None = None
    result: IngestionJobResult | None = None

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "IngestionJob":
        result_payload = payload.get("result")
        result = None
        if isinstance(result_payload, dict):
            result = IngestionJobResult.from_dict(result_payload)

        return IngestionJob(
            job_id=payload["job_id"],
            type=payload["type"],
            status=payload["status"],
            created_at=payload["created_at"],
            stage=payload.get("stage"),
            progress=payload.get("progress"),
            error=payload.get("error"),
            warnings=payload.get("warnings"),
            result=result,
        )


@dataclass(frozen=True)
class IngestionUsageLimitResponse:
    allowed: Literal[False]
    usage_percent: float
    used_tokens: int | None = None
    limit_tokens: int | None = None
    window_start_at: str | None = None

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "IngestionUsageLimitResponse":
        return IngestionUsageLimitResponse(
            allowed=False,
            usage_percent=float(payload.get("usage_percent", 0)),
            used_tokens=payload.get("used_tokens"),
            limit_tokens=payload.get("limit_tokens"),
            window_start_at=payload.get("window_start_at"),
        )

