"""Versioned cache for review-independent article-type assessments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Protocol

from ebm_backend.online_pipeline.domain.article_qualification import (
    ArticleQualificationAssessment,
)
from ebm_backend.online_pipeline.domain.serialization import from_jsonable, to_jsonable
from ebm_backend.online_pipeline.infrastructure.methods.article_qualification.content_llm.evidence import (
    EVIDENCE_PACK_VERSION,
    QualificationEvidenceBundle,
)
from ebm_backend.online_pipeline.infrastructure.persistence.atomic_io import (
    atomic_write_json,
    read_json,
)


METHOD_VERSION = "content_article_qualification_v1"


class ArticleQualificationCache(Protocol):
    def get(self, *, key: str) -> ArticleQualificationAssessment | None:
        ...

    def put(self, *, key: str, assessment: ArticleQualificationAssessment) -> None:
        ...


@dataclass(frozen=True)
class FileArticleQualificationCache:
    root: Path

    def get(self, *, key: str) -> ArticleQualificationAssessment | None:
        path = self._path(key)
        if not path.exists():
            return None
        payload = read_json(path)
        if not isinstance(payload, dict) or payload.get("key") != key:
            raise ValueError("Cached article qualification identity mismatch")
        return from_jsonable(payload["assessment"], ArticleQualificationAssessment)

    def put(self, *, key: str, assessment: ArticleQualificationAssessment) -> None:
        atomic_write_json(
            self._path(key),
            {
                "key": key,
                "method_version": METHOD_VERSION,
                "evidence_pack_version": EVIDENCE_PACK_VERSION,
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "assessment": assessment,
            },
        )

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"


def build_cache_key(
    *,
    study_id: str,
    config: object,
    evidence: QualificationEvidenceBundle,
    prompt_fingerprint: str,
    schema_fingerprint: str,
) -> str:
    if isinstance(config, dict):
        model = {
            "base_url": str(config.get("base_url") or "").rstrip("/"),
            "model": str(config.get("model") or ""),
            "api_mode": str(config.get("api_mode") or ""),
            "temperature": config.get("temperature"),
            "context_window_tokens": config.get("context_window_tokens"),
            "screening_input_token_budget": config.get(
                "screening_input_token_budget"
            ),
        }
    else:
        model = {
            name: getattr(config, name, None)
            for name in (
                "base_url",
                "model",
                "api_mode",
                "temperature",
                "context_window_tokens",
                "screening_input_token_budget",
            )
        }
    payload: dict[str, Any] = {
        "method_version": METHOD_VERSION,
        "study_id": study_id,
        "evidence_pack_version": EVIDENCE_PACK_VERSION,
        "evidence": evidence.format(),
        "coverage": evidence.coverage,
        "prompt_fingerprint": prompt_fingerprint,
        "schema_fingerprint": schema_fingerprint,
        "model": model,
    }
    encoded = json.dumps(
        to_jsonable(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def fingerprint(value: object) -> str:
    encoded = json.dumps(
        to_jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
