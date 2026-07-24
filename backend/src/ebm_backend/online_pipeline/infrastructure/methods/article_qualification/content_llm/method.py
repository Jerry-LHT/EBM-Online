"""One-call content classifier with one bounded retry and successful-result cache."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
import time
from typing import Any
import unicodedata

from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.article_qualification import (
    ArticleQualificationAssessment,
    ArticleQualificationDecision,
    ArticleReportRole,
    RandomizationStatus,
    ResultsReportStatus,
    TrialDesign,
)
from ebm_backend.online_pipeline.domain.common import EvidenceSourceSpan
from ebm_backend.online_pipeline.domain.serialization import to_jsonable
from ebm_backend.online_pipeline.infrastructure.llm import LLMConfig, call_llm_json
from ebm_backend.online_pipeline.infrastructure.methods.article_qualification.content_llm.cache import (
    ArticleQualificationCache,
    build_cache_key,
    fingerprint,
)
from ebm_backend.online_pipeline.infrastructure.methods.article_qualification.content_llm.evidence import (
    QualificationEvidenceBundle,
    build_qualification_evidence,
    resolve_input_token_budget,
)
from ebm_backend.online_pipeline.infrastructure.methods.article_qualification.errors import (
    ArticleQualificationConfigurationError,
    ArticleQualificationInvocationError,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.llm_support import (
    screening_llm_config,
)
from ebm_backend.online_pipeline.infrastructure.persistence.atomic_io import (
    atomic_write_json,
)


MAX_ATTEMPTS = 2
PROMPT_VERSION = "article_qualification_v1"


@dataclass(frozen=True)
class ContentBasedArticleQualifier:
    config: LLMConfig | dict[str, Any] | None = None
    llm_caller: Any = call_llm_json
    cache: ArticleQualificationCache | None = None
    debug_root: Path | None = None
    prompt_dir: Path = Path(__file__).resolve().parent / "prompts"

    def run(self, *, article: CleanedArticle) -> ArticleQualificationAssessment:
        try:
            config = screening_llm_config(self.config)
        except Exception as exc:
            raise ArticleQualificationConfigurationError(
                "Article qualification LLM configuration is unavailable"
            ) from exc
        evidence = build_qualification_evidence(
            article=article,
            input_token_budget=resolve_input_token_budget(config),
        )
        system = (self.prompt_dir / "system.txt").read_text(encoding="utf-8").strip()
        user_template = (self.prompt_dir / "user.txt").read_text(encoding="utf-8")
        prompt = user_template.format(evidence=evidence.format())
        schema = _schema()
        cache_key = build_cache_key(
            study_id=article.study_id,
            config=config,
            evidence=evidence,
            prompt_fingerprint=fingerprint(
                {"version": PROMPT_VERSION, "system": system, "user": user_template}
            ),
            schema_fingerprint=fingerprint(schema),
        )
        if self.cache is not None:
            try:
                cached = self.cache.get(key=cache_key)
            except (OSError, ValueError, TypeError, KeyError):
                cached = None
            if cached is not None:
                _write_debug(
                    root=self.debug_root,
                    key=cache_key,
                    article=article,
                    config=config,
                    evidence=evidence,
                    cache_hit=True,
                    attempts=[],
                    payload=None,
                    assessment=cached,
                    elapsed_ms=0,
                )
                return cached

        call_config = dict(config)
        call_config["sdk_max_retries"] = 0
        call_config["json_marker_retry_enabled"] = False
        started = time.monotonic()
        attempt_records: list[dict[str, Any]] = []
        last_payload: dict[str, Any] | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                payload = self.llm_caller(
                    config=call_config,
                    system=system,
                    prompt=prompt,
                    temperature=_temperature(call_config),
                    max_output_tokens=2_000,
                    json_schema=schema,
                    json_schema_name="article_qualification_v1",
                )
                last_payload = payload
                assessment = _parse(
                    payload,
                    article=article,
                    evidence=evidence,
                )
            except Exception as exc:
                attempt_records.append(
                    {
                        "attempt": attempt,
                        "status": "failed",
                        "error_type": type(exc).__name__,
                        "failure_code": getattr(exc, "failure_code", None),
                        "message": str(exc)[:500],
                    }
                )
                if attempt == MAX_ATTEMPTS:
                    _write_debug(
                        root=self.debug_root,
                        key=cache_key,
                        article=article,
                        config=config,
                        evidence=evidence,
                        cache_hit=False,
                        attempts=attempt_records,
                        payload=last_payload,
                        assessment=None,
                        elapsed_ms=int((time.monotonic() - started) * 1_000),
                    )
                    raise ArticleQualificationInvocationError(
                        article_id=article.study_id,
                        attempts=attempt,
                    ) from exc
                continue
            attempt_records.append({"attempt": attempt, "status": "succeeded"})
            _write_debug(
                root=self.debug_root,
                key=cache_key,
                article=article,
                config=config,
                evidence=evidence,
                cache_hit=False,
                attempts=attempt_records,
                payload=payload,
                assessment=assessment,
                elapsed_ms=int((time.monotonic() - started) * 1_000),
            )
            if self.cache is not None:
                try:
                    self.cache.put(key=cache_key, assessment=assessment)
                except (OSError, ValueError, TypeError, KeyError):
                    pass
            return assessment
        raise AssertionError("unreachable")


def _parse(
    payload: dict[str, Any],
    *,
    article: CleanedArticle,
    evidence: QualificationEvidenceBundle,
) -> ArticleQualificationAssessment:
    decision = ArticleQualificationDecision(_required(payload, "decision"))
    report_role = ArticleReportRole(_required(payload, "report_role"))
    randomization = RandomizationStatus(_required(payload, "randomization_status"))
    trial_design = TrialDesign(_required(payload, "trial_design"))
    results_status = ResultsReportStatus(_required(payload, "results_report_status"))
    quantitative = payload.get("has_quantitative_results")
    if quantitative is not None and not isinstance(quantitative, bool):
        raise ValueError("has_quantitative_results must be boolean or null")
    reason = _required(payload, "reason")
    spans = _spans(payload.get("evidence_spans"), evidence=evidence)

    # Conservative, general consistency gate.  Uncertain evidence advances;
    # it is never converted into an exclusion by engineering code.
    if decision == ArticleQualificationDecision.PASS and not (
        report_role == ArticleReportRole.PRIMARY_RESULTS
        and randomization == RandomizationStatus.RANDOMIZED
        and results_status == ResultsReportStatus.RESULTS_REPORTED
    ):
        decision = ArticleQualificationDecision.ADVANCE_UNCERTAIN
        reason = f"Model pass was not fully supported by its structured facts. {reason}"
    if decision == ArticleQualificationDecision.EXCLUDE and (
        report_role == ArticleReportRole.UNCLEAR
        and randomization == RandomizationStatus.UNCLEAR
        and results_status == ResultsReportStatus.UNCLEAR
    ):
        decision = ArticleQualificationDecision.ADVANCE_UNCERTAIN
        reason = f"No positive exclusion fact was supplied. {reason}"

    return ArticleQualificationAssessment(
        study_id=article.study_id,
        decision=decision,
        report_role=report_role,
        randomization_status=randomization,
        trial_design=trial_design,
        results_report_status=results_status,
        has_quantitative_results=quantitative,
        reason=reason,
        source_spans=spans,
        evidence_coverage=evidence.coverage,
    )


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "decision": {
                "type": "string",
                "enum": [
                    ArticleQualificationDecision.PASS.value,
                    ArticleQualificationDecision.EXCLUDE.value,
                    ArticleQualificationDecision.ADVANCE_UNCERTAIN.value,
                ],
            },
            "report_role": {
                "type": "string",
                "enum": [value.value for value in ArticleReportRole],
            },
            "randomization_status": {
                "type": "string",
                "enum": [value.value for value in RandomizationStatus],
            },
            "trial_design": {
                "type": "string",
                "enum": [value.value for value in TrialDesign],
            },
            "results_report_status": {
                "type": "string",
                "enum": [value.value for value in ResultsReportStatus],
            },
            "has_quantitative_results": {"type": ["boolean", "null"]},
            "reason": {"type": "string"},
            "evidence_spans": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "decision",
            "report_role",
            "randomization_status",
            "trial_design",
            "results_report_status",
            "has_quantitative_results",
            "reason",
            "evidence_spans",
        ],
        "additionalProperties": False,
    }


def _spans(
    value: Any,
    *,
    evidence: QualificationEvidenceBundle,
) -> list[EvidenceSourceSpan]:
    if not isinstance(value, list):
        raise ValueError("evidence_spans must be a list")
    spans: list[EvidenceSourceSpan] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("evidence_spans must contain strings")
        clean = item.strip()
        if not clean:
            continue
        source_id = _matching_source(clean, evidence.sources)
        if source_id is not None:
            spans.append(EvidenceSourceSpan(source_id=source_id, text=clean))
    return spans


def _matching_source(span: str, sources: dict[str, str]) -> str | None:
    for source_id, text in sources.items():
        if span in text:
            return source_id
    normalized = _normalize(span)
    for source_id, text in sources.items():
        if normalized and normalized in _normalize(text):
            return source_id
    return None


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).translate(
        str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-"})
    )
    return re.sub(r"\s+", " ", normalized).strip()


def _required(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip().lower()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _temperature(config: dict[str, Any]) -> float | None:
    value = config.get("temperature")
    return float(value) if value is not None and str(value).strip() else None


def _write_debug(
    *,
    root: Path | None,
    key: str,
    article: CleanedArticle,
    config: object,
    evidence: QualificationEvidenceBundle,
    cache_hit: bool,
    attempts: list[dict[str, Any]],
    payload: dict[str, Any] | None,
    assessment: ArticleQualificationAssessment | None,
    elapsed_ms: int,
) -> None:
    if root is None:
        return
    path = root / key[:2] / f"{key}.json"
    # Preserve the original provider call and model output.  A later cache hit
    # must not replace that richer trace with an empty invocation record.
    if cache_hit and path.exists():
        return
    model = {
        name: (
            config.get(name) if isinstance(config, dict) else getattr(config, name, None)
        )
        for name in (
            "base_url",
            "model",
            "api_mode",
            "temperature",
            "context_window_tokens",
            "screening_input_token_budget",
        )
    }
    try:
        atomic_write_json(
            path,
            {
                "stage": "article_qualification",
                "study_id": article.study_id,
                "cache_key": key,
                "cache_hit": cache_hit,
                "model": model,
                "evidence_coverage": evidence.coverage,
                "evidence_sources": [
                    {
                        "source_id": block.source_id,
                        "kind": block.kind,
                        "coverage": block.coverage,
                        "label": block.label,
                        "start_char": block.start_char,
                        "end_char": block.end_char,
                        "total_chars": block.total_chars,
                        "text_sha256": sha256(block.text.encode("utf-8")).hexdigest(),
                        "text": block.text,
                    }
                    for block in evidence.blocks
                ],
                "attempts": attempts,
                "elapsed_ms": elapsed_ms,
                "model_output": payload,
                "assessment": to_jsonable(assessment),
            },
        )
    except (OSError, UnicodeEncodeError, TypeError, ValueError):
        # Debug observability must not change the medical workflow result.
        return
