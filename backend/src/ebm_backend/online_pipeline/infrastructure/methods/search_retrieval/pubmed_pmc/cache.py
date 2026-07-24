"""Local positive-result cache for PubMed and PMC retrieval artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import time

from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.serialization import (
    from_jsonable,
    to_jsonable,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.models import (
    PubMedArticleMetadata,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.xml_cleaner import (
    XML_CLEANER_VERSION,
)
from ebm_backend.online_pipeline.infrastructure.persistence.atomic_io import (
    atomic_write_gzip_text,
    atomic_write_json,
    read_gzip_text,
    read_json,
)


DEFAULT_PROVIDER_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60


@dataclass(frozen=True)
class PubMedPmcFileCache:
    root: Path
    ttl_seconds: int = DEFAULT_PROVIDER_CACHE_TTL_SECONDS

    def get_metadata(self, *, pmid: str) -> PubMedArticleMetadata | None:
        path = self._identified_path("pubmed_metadata", pmid, ".json")
        if not self._is_fresh(path):
            return None
        payload = read_json(path)
        if not isinstance(payload, dict) or payload.get("pmid") != pmid:
            raise ValueError("Cached PubMed metadata identity mismatch")
        return from_jsonable(payload["value"], PubMedArticleMetadata)

    def put_metadata(self, *, metadata: PubMedArticleMetadata) -> None:
        atomic_write_json(
            self._identified_path("pubmed_metadata", metadata.pmid, ".json"),
            {"pmid": metadata.pmid, "value": metadata},
        )

    def get_pmcid(self, *, pmid: str) -> str | None:
        path = self._identified_path("pmid_to_pmcid", pmid, ".json")
        if not self._is_fresh(path):
            return None
        payload = read_json(path)
        if not isinstance(payload, dict) or payload.get("pmid") != pmid:
            raise ValueError("Cached PMID-to-PMCID identity mismatch")
        pmcid = str(payload.get("pmcid") or "").strip()
        return pmcid or None

    def put_pmcid(self, *, pmid: str, pmcid: str) -> None:
        atomic_write_json(
            self._identified_path("pmid_to_pmcid", pmid, ".json"),
            {"pmid": pmid, "pmcid": pmcid},
        )

    def get_xml(self, *, pmcid: str) -> str | None:
        path = self._identified_path("pmc_xml", pmcid, ".xml.gz")
        if not self._is_fresh(path):
            return None
        return read_gzip_text(path)

    def put_xml(self, *, pmcid: str, xml_text: str) -> None:
        atomic_write_gzip_text(
            self._identified_path("pmc_xml", pmcid, ".xml.gz"),
            xml_text,
        )

    def cleaned_article_key(
        self,
        *,
        xml_text: str,
        metadata: PubMedArticleMetadata,
    ) -> str:
        payload = {
            "cleaner_version": XML_CLEANER_VERSION,
            "xml_sha256": sha256(xml_text.encode("utf-8")).hexdigest(),
            "metadata": to_jsonable(metadata),
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    def get_cleaned_article(self, *, key: str) -> CleanedArticle | None:
        path = self.root / "cleaned_articles" / key[:2] / f"{key}.json.gz"
        if not path.exists():
            return None
        payload = json.loads(read_gzip_text(path))
        if not isinstance(payload, dict) or payload.get("key") != key:
            raise ValueError("Cached CleanedArticle identity mismatch")
        if payload.get("cleaner_version") != XML_CLEANER_VERSION:
            return None
        return from_jsonable(payload["value"], CleanedArticle)

    def put_cleaned_article(self, *, key: str, article: CleanedArticle) -> None:
        payload = json.dumps(
            to_jsonable(
                {
                    "key": key,
                    "cleaner_version": XML_CLEANER_VERSION,
                    "value": article,
                }
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
        atomic_write_gzip_text(
            self.root / "cleaned_articles" / key[:2] / f"{key}.json.gz",
            payload,
        )

    def _identified_path(self, namespace: str, value: str, suffix: str) -> Path:
        digest = sha256(value.encode("utf-8")).hexdigest()
        return self.root / namespace / digest[:2] / f"{digest}{suffix}"

    def _is_fresh(self, path: Path) -> bool:
        if not path.exists() or self.ttl_seconds <= 0:
            return False
        return time.time() - path.stat().st_mtime <= self.ttl_seconds
