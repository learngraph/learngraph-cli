from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .auth import AuthManager
from .types import (
    IngestionJob,
    IngestionJobAcceptedResponse,
    IngestionUsageLimitResponse,
)


class IngestionApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class IngestionApiConfig:
    base_url: str
    resources_base_url: str
    timeout_s: float

    @staticmethod
    def from_env() -> "IngestionApiConfig":
        base_url = os.getenv("LEARNGRAPH_INGESTION_BASE_URL", "").strip().rstrip("/")
        if not base_url:
            raise IngestionApiError(
                "Missing LEARNGRAPH_INGESTION_BASE_URL. "
                "Set full base path, e.g. http://localhost:8080/service-ingestion/v1"
            )
        resources_base_url = os.getenv("LEARNGRAPH_RESOURCES_BASE_URL", "").strip().rstrip("/")
        if not resources_base_url:
            resources_base_url = "http://localhost:8081/service-resources/v1"
        return IngestionApiConfig(
            base_url=base_url,
            resources_base_url=resources_base_url,
            timeout_s=float(os.getenv("LEARNGRAPH_INGESTION_TIMEOUT_S", "30")),
        )


class IngestionApiClient:
    def __init__(self, config: IngestionApiConfig, auth: AuthManager):
        self.config = config
        self.auth = auth

    def submit_topic_ingestion(
        self,
        topic: str,
        *,
        coalesce_threshold: float | None = None,
        max_resources_per_topic: int | None = None,
    ) -> IngestionJobAcceptedResponse | IngestionUsageLimitResponse:
        payload: dict[str, Any] = {"topics": [topic]}
        if coalesce_threshold is not None:
            payload["coalesce_threshold"] = coalesce_threshold
        if max_resources_per_topic is not None:
            payload["max_resources_per_topic"] = max_resources_per_topic
        body = self._request_json("POST", "/generate-topic-graphs", payload=payload)
        return self._parse_submit_response(body)

    def submit_resource_ingestion(
        self,
        *,
        url: str,
        reference: str | None = None,
        resource_uuid: str | None = None,
        publish: bool | None = None,
        seed_topic_title: str | None = None,
    ) -> IngestionJobAcceptedResponse | IngestionUsageLimitResponse:
        item: dict[str, Any] = {"url": url}
        if reference:
            item["reference"] = reference
        if resource_uuid:
            item["resource_uuid"] = resource_uuid
        if publish is not None:
            item["publish"] = publish
        if seed_topic_title:
            item["seed_topic_title"] = seed_topic_title
        body = self._request_json("POST", "/ingest-resources", payload={"urls": [item]})
        return self._parse_submit_response(body)

    def upload_local_file(
        self, local_path: Path, *, publish: bool | None = None
    ) -> tuple[str, str]:
        """
        Upload local file through resources service and return (reference, resource_uuid).
        """
        filename = local_path.name
        guessed_content_type, _ = mimetypes.guess_type(str(local_path))
        payload: dict[str, Any] = {
            "filename": filename,
            "content_type": guessed_content_type or "application/octet-stream",
        }
        if publish is not None:
            payload["publish"] = publish

        link = self._request_json_resources("POST", "/resources/upload-link", payload=payload)
        upload_url = link.get("upload_url")
        object_key = link.get("object_key")
        reference = link.get("reference")
        resource_uuid = link.get("resource_uuid")
        content_type = link.get("content_type") or payload["content_type"]
        if not upload_url or not object_key or not reference or not resource_uuid:
            raise IngestionApiError("Invalid upload-link response from resources service.")

        self._upload_to_presigned_url(local_path, upload_url, content_type)
        self._request_json_resources(
            "POST",
            "/resources/uploads/confirm",
            payload={"object_key": object_key},
        )

        return str(reference), str(resource_uuid)

    def get_job(self, job_id: str) -> IngestionJob:
        body = self._request_json("GET", f"/ingestions/{job_id}")
        return IngestionJob.from_dict(body)

    def _parse_submit_response(
        self, payload: dict[str, Any]
    ) -> IngestionJobAcceptedResponse | IngestionUsageLimitResponse:
        if payload.get("allowed") is False:
            return IngestionUsageLimitResponse.from_dict(payload)
        return IngestionJobAcceptedResponse(
            job_id=payload["job_id"],
            status=payload["status"],
        )

    def _request_json(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        headers = {
            "Authorization": self.auth.authorization_header(),
            "Content-Type": "application/json",
        }
        url = f"{self.config.base_url}{path}"
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=payload,
                timeout=self.config.timeout_s,
            )
        except requests.RequestException as exc:
            raise IngestionApiError(f"Request failed: {exc}") from exc

        if response.status_code >= 400:
            if response.status_code in (401, 403):
                raise IngestionApiError(
                    f"Unauthorized ({response.status_code}). Try `learngraph auth login`."
                )
            raise IngestionApiError(
                f"API error ({response.status_code}) on {path}: {response.text.strip()}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise IngestionApiError(f"Invalid JSON response from {path}") from exc

    def _request_json_resources(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        headers = {
            "Authorization": self.auth.authorization_header(),
            "Content-Type": "application/json",
        }
        url = f"{self.config.resources_base_url}{path}"
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=payload,
                timeout=self.config.timeout_s,
            )
        except requests.RequestException as exc:
            raise IngestionApiError(f"Resources request failed: {exc}") from exc

        if response.status_code >= 400:
            raise IngestionApiError(
                f"Resources API error ({response.status_code}) on {path}: {response.text.strip()}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise IngestionApiError(f"Invalid JSON response from resources {path}") from exc

    def _upload_to_presigned_url(self, local_path: Path, upload_url: str, content_type: str) -> None:
        try:
            with local_path.open("rb") as fh:
                response = requests.put(
                    upload_url,
                    data=fh,
                    headers={"Content-Type": content_type},
                    timeout=self.config.timeout_s,
                )
        except OSError as exc:
            raise IngestionApiError(f"Failed reading local file for upload: {exc}") from exc
        except requests.RequestException as exc:
            raise IngestionApiError(f"Upload to presigned URL failed: {exc}") from exc

        if response.status_code >= 400:
            raise IngestionApiError(
                f"Upload failed ({response.status_code}) to presigned URL: {response.text.strip()}"
            )

