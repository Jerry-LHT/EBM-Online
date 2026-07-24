"""Versioned article-level cache for successful RoB 1 domain judgements."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Protocol

from ebm_backend.online_pipeline.domain.risk_of_bias import RoB1DomainJudgement
from ebm_backend.online_pipeline.domain.serialization import (
    from_jsonable,
    to_jsonable,
)
from ebm_backend.online_pipeline.infrastructure.llm import LLMConfig
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_onestep_llm.article_evidence import (
    ARTICLE_EVIDENCE_VERSION,
)
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_onestep_llm.domain_assessor import (
    domain_contract_fingerprint,
)
from ebm_backend.online_pipeline.infrastructure.persistence.atomic_io import (
    atomic_write_json,
    read_json,
)


ROB_METHOD_VERSION = "rob1_article_onestep_v1"


class RoBDomainJudgementCache(Protocol):
    def get(
        self,
        *,
        key: str,
        domain: str,
    ) -> RoB1DomainJudgement | None:
        ...

    def put(
        self,
        *,
        key: str,
        domain: str,
        judgement: RoB1DomainJudgement,
    ) -> None:
        ...


@dataclass(frozen=True)
class FileRoBDomainJudgementCache:
    root: Path

    def get(
        self,
        *,
        key: str,
        domain: str,
    ) -> RoB1DomainJudgement | None:
        path = self._path(key)
        if not path.exists():
            return None
        payload = read_json(path)
        if not isinstance(payload, dict):
            raise ValueError("Cached RoB domain entry must be an object")
        if payload.get("key") != key or payload.get("domain") != domain:
            raise ValueError("Cached RoB domain identity mismatch")
        judgement = from_jsonable(payload["judgement"], RoB1DomainJudgement)
        if judgement.domain != domain:
            raise ValueError("Cached RoB judgement contains the wrong domain")
        return judgement

    def put(
        self,
        *,
        key: str,
        domain: str,
        judgement: RoB1DomainJudgement,
    ) -> None:
        if judgement.domain != domain:
            raise ValueError("RoB cache domain and judgement domain must match")
        atomic_write_json(
            self._path(key),
            {
                "key": key,
                "domain": domain,
                "method_version": ROB_METHOD_VERSION,
                "article_evidence_version": ARTICLE_EVIDENCE_VERSION,
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "judgement": judgement,
            },
        )

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"


def build_domain_cache_key(
    *,
    config: LLMConfig,
    domain: str,
    evidence: str,
) -> str:
    payload = {
        "method_version": ROB_METHOD_VERSION,
        "article_evidence_version": ARTICLE_EVIDENCE_VERSION,
        "evidence_sha256": sha256(evidence.encode("utf-8")).hexdigest(),
        "domain": domain,
        "domain_contract_sha256": domain_contract_fingerprint(domain),
        "model": {
            "base_url": config.base_url.rstrip("/"),
            "model": config.model,
            "api_mode": config.api_mode,
            "temperature": config.temperature,
        },
    }
    encoded = json.dumps(
        to_jsonable(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
