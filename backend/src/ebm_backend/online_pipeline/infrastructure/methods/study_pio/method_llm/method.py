"""LLM-assisted Study PIO extraction method.

This method consumes only workflow inputs: question PICO, included study IDs,
and cleaned article content. It does not read benchmark gold labels.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from ebm_backend.online_pipeline.domain.article import ArticleTable, CleanedArticle
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.study_characteristics import (
    StudyComparatorCharacteristics,
    StudyInterventionCharacteristics,
    StudyOutcomeCharacteristics,
    StudyPIOCharacteristics,
    StudyPopulationCharacteristics,
)
from ebm_backend.online_pipeline.infrastructure.llm import LLMConfig, call_llm_json, load_llm_config
from ebm_backend.online_pipeline.infrastructure.methods.study_pio.method_rule.method import Method as RuleMethod


SYSTEM_PROMPT = """You are a clinical evidence extraction assistant for Cochrane-style study characteristics.

Extract study-level PIO characteristics for ONE included study from the supplied
article snippets and the review question PICO.

Cochrane-style framing:
- The review PICO defines the review's intended population, intervention,
  comparison, and important outcomes.
- The study-level PIO should describe what this included study actually
  recruited, delivered, compared, and measured/reported, while staying aligned
  with the review PICO.
- Population, intervention, and comparator usually define study eligibility.
  Outcomes are often broader review outcomes and may include benefits and harms.

Definitions:
- population: participants actually enrolled in this study, including eligibility,
  setting, sample size, age/sex or disease-severity baseline details, and
  important baseline condition when available.
- interventions: experimental or active arms/procedures used in this study.
- comparators: control, placebo, usual care, sham, waiting list, or alternative
  arms used in this study.
  Include duration, frequency, delivery mode, provider/supervision, and setting
  when available.
- outcomes: outcomes or measures assessed in this study. First prioritize
  critical or important review-relevant outcomes that match or are close
  synonyms of the review question PICO O terms, including both benefits and
  harms/adverse effects. Then include primary and secondary outcomes from the
  article when they are meaningful to patients, clinicians, or policy makers.
  Prefer outcome domains, measurement tools, and timepoints over numerical
  result findings.

Rules:
- Use only the supplied article snippets and question PICO.
- Do not use benchmark gold labels or outside knowledge.
- Do not invent details. Leave fields empty when evidence is unavailable.
- Keep descriptions concise but specific enough for semantic matching.
- Include total sample size and per-arm sample sizes in population when the
  article gives them.
- Prefer study-specific evidence over review-level PICO terms.
- Avoid surrogate, interim, biochemical, process, implementation, feasibility,
  resource-use, and economic outcomes unless they are critical or important for
  the review question, match the PICO O terms, or are the only outcome type in
  the supplied evidence.
- If an outcome appears in the review PICO O terms and the snippets show this
  study measured or reported a closely related domain, include the review-aligned
  outcome name even when the article uses a different instrument or wording.
- Return exactly one valid JSON object and no surrounding text.

JSON schema:
{
  "population": "string",
  "interventions": [{"label": "string", "description": "string"}],
  "comparators": [{"label": "string", "description": "string"}],
  "outcomes": [{"outcome_label": "string", "measurement": "string"}],
  "warnings": ["string"]
}"""


class Method:
    def __init__(self) -> None:
        self.llm_config_path: Path | None = None
        self.fallback = RuleMethod()

    def configure_for_benchmark(
        self,
        *,
        llm_config: str | Path = "llm.local.json",
        workers: int = 1,
        run_dir: str | Path | None = None,
        resume: bool = False,
    ) -> None:
        self.llm_config_path = Path(llm_config)

    def run(
        self,
        *,
        question_pico: QuestionPICO,
        included_studies: list[str],
        articles: list[CleanedArticle],
    ) -> list[StudyPIOCharacteristics]:
        config = load_llm_config(self.llm_config_path or Path("llm.local.json"))
        if config is None:
            raise RuntimeError("Missing LLM config for study_pio.method_llm")

        articles_by_study = {article.study_id: article for article in articles}
        results: list[StudyPIOCharacteristics] = []
        for study_id in included_studies:
            article = articles_by_study.get(study_id)
            if article is None and len(articles) == 1:
                article = articles[0]
            if article is None:
                continue
            fallback_item = self._fallback_item(
                question_pico=question_pico,
                study_id=study_id,
                article=article,
            )
            item = self._extract_one(
                config=config,
                question_pico=question_pico,
                study_id=study_id,
                article=article,
                fallback_item=fallback_item,
            )
            results.append(item)
        return results

    def _fallback_item(
        self,
        *,
        question_pico: QuestionPICO,
        study_id: str,
        article: CleanedArticle,
    ) -> StudyPIOCharacteristics:
        fallback = self.fallback.run(
            question_pico=question_pico,
            included_studies=[study_id],
            articles=[article],
        )
        if fallback:
            return fallback[0]
        return StudyPIOCharacteristics(
            study_id=study_id,
            population=StudyPopulationCharacteristics(description=""),
            interventions=[],
            comparators=[],
            outcomes=[],
            notes="Empty fallback: no matching cleaned article was available.",
        )

    def _extract_one(
        self,
        *,
        config: LLMConfig,
        question_pico: QuestionPICO,
        study_id: str,
        article: CleanedArticle,
        fallback_item: StudyPIOCharacteristics,
    ) -> StudyPIOCharacteristics:
        prompt = _build_user_prompt(question_pico=question_pico, study_id=study_id, article=article)
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                parsed = call_llm_json(config=config, system=SYSTEM_PROMPT, prompt=prompt)
                return _merge_with_fallback(
                    study_id=study_id,
                    question_pico=question_pico,
                    parsed=parsed,
                    fallback_item=fallback_item,
                )
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                prompt = (
                    f"{prompt}\n\nYour previous response was not valid JSON. "
                    "Return exactly one JSON object following the requested schema."
                )
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                break
        return _with_note(
            fallback_item,
            f"LLM extraction failed; used rule fallback. Error: {type(last_error).__name__}: {last_error}",
        )


def build_method() -> Method:
    return Method()


def _build_user_prompt(*, question_pico: QuestionPICO, study_id: str, article: CleanedArticle) -> str:
    payload = {
        "study_id": study_id,
        "article_title": article.metadata.title,
        "question_pico": {
            "P": list(question_pico.P),
            "I": list(question_pico.I),
            "C": list(question_pico.C),
            "O": list(question_pico.O),
        },
        "article_snippets": _article_snippets(article=article, question_pico=question_pico),
        "table_snippets": _table_snippets(article.tables),
    }
    return (
        "Extract the study-level PIO characteristics for this included study. "
        "For outcomes, map article evidence to the review question PICO O terms first; "
        "include unmatched article outcomes only when they are primary/secondary or otherwise important benefit/harm outcomes. "
        "For intervention/comparator, report arm content, dose/duration/frequency, provider, and setting when present. "
        "Return JSON only.\n\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )


def _article_snippets(*, article: CleanedArticle, question_pico: QuestionPICO) -> list[dict[str, str]]:
    query_terms = _pico_terms(question_pico)
    outcome_terms = _pico_terms_from_values(question_pico.O)
    scored: list[tuple[int, int, dict[str, str]]] = []
    for index, section in enumerate(article.xml_content.sections):
        title = _clean_text(section.title or "Section")
        for chunk_index, chunk in enumerate(_section_chunks(str(section.text or "")), start=1):
            text = _clean_text(chunk)
            if not text:
                continue
            chunk_title = _chunk_title(default_title=title, chunk=chunk)
            score = _section_score(
                title=chunk_title,
                text=text,
                query_terms=query_terms,
                outcome_terms=outcome_terms,
            )
            snippet = {
                "section_id": section.section_id or f"section-{index + 1}",
                "title": chunk_title,
                "text": _truncate(text, 3500),
            }
            scored.append((score, -(index * 1000 + chunk_index), snippet))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)

    selected: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for _, _, snippet in scored[:28]:
        section_id = f"{snippet['section_id']}::{snippet['title']}::{snippet['text'][:120]}"
        if section_id in seen_ids:
            continue
        seen_ids.add(section_id)
        selected.append(snippet)

    total_chars = 0
    bounded: list[dict[str, str]] = []
    for snippet in selected:
        text = snippet["text"]
        remaining = 65_000 - total_chars
        if remaining <= 0:
            break
        if len(text) > remaining:
            snippet = {**snippet, "text": _truncate(text, remaining)}
        bounded.append(snippet)
        total_chars += len(snippet["text"])
    return bounded


def _section_score(*, title: str, text: str, query_terms: set[str], outcome_terms: set[str]) -> int:
    lowered_title = title.lower()
    lowered_text = text.lower()
    score = 0
    title_keywords = {
        "abstract": 18,
        "summary": 12,
        "method": 40,
        "material": 35,
        "participant": 45,
        "patient": 35,
        "population": 45,
        "eligibility": 45,
        "inclusion": 45,
        "intervention": 45,
        "procedure": 35,
        "treatment": 35,
        "random": 25,
        "outcome": 45,
        "main outcome": 65,
        "primary outcome": 65,
        "secondary outcome": 55,
        "endpoint": 45,
        "efficacy": 35,
        "adverse": 35,
        "measure": 30,
        "assessment": 25,
        "follow up": 25,
        "follow-up": 25,
        "result": 18,
    }
    text_keywords = {
        "participants": 8,
        "patients": 6,
        "eligible": 8,
        "inclusion": 8,
        "exclusion": 6,
        "intervention": 8,
        "control": 8,
        "placebo": 8,
        "usual care": 8,
        "sham": 8,
        "randomized": 6,
        "randomised": 6,
        "outcome": 8,
        "main outcome": 16,
        "primary outcome": 18,
        "secondary outcome": 14,
        "primary endpoint": 18,
        "secondary endpoint": 14,
        "adverse event": 12,
        "adverse effect": 12,
        "follow-up": 8,
        "measured": 5,
        "assessed": 5,
    }
    for keyword, weight in title_keywords.items():
        if keyword in lowered_title:
            score += weight
    for keyword, weight in text_keywords.items():
        if keyword in lowered_text:
            score += weight
    for term in query_terms:
        if len(term) >= 4:
            if term in lowered_title:
                score += 10
            if term in lowered_text:
                score += 3
    for term in outcome_terms:
        if len(term) >= 4:
            if term in lowered_title:
                score += 24
            if term in lowered_text:
                score += 12
    return score


def _section_chunks(text: str) -> list[str]:
    raw = text.strip()
    if not raw:
        return []
    pieces = re.split(r"(?=^\s{0,3}#{1,6}\s+)", raw, flags=re.MULTILINE)
    blocks: list[str] = []
    for piece in pieces:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", piece) if part.strip()]
        current: list[str] = []
        current_len = 0
        for paragraph in paragraphs:
            paragraph_len = len(paragraph)
            if current and current_len + paragraph_len > 2600:
                blocks.append("\n\n".join(current))
                current = []
                current_len = 0
            current.append(paragraph)
            current_len += paragraph_len
        if current:
            blocks.append("\n\n".join(current))
    if not blocks:
        return [raw]
    return blocks


def _chunk_title(*, default_title: str, chunk: str) -> str:
    first_line = chunk.strip().splitlines()[0] if chunk.strip() else ""
    match = re.match(r"\s{0,3}#{1,6}\s+(.+)", first_line)
    if match:
        heading = _clean_text(match.group(1))
        if heading and heading.lower() not in default_title.lower():
            return f"{default_title} / {heading}"
    return default_title


def _table_snippets(tables: list[ArticleTable]) -> list[dict[str, str]]:
    scored: list[tuple[int, int, dict[str, str]]] = []
    for index, table in enumerate(tables):
        caption = _clean_text(table.caption)
        rows_text = _rows_text(table.rows)
        text = "\n".join(part for part in [caption, rows_text] if part)
        if not text:
            continue
        lowered = text.lower()
        score = 0
        for keyword in ("participant", "baseline", "intervention", "outcome", "measure", "arm", "group"):
            if keyword in lowered:
                score += 10
        scored.append(
            (
                score,
                -index,
                {
                    "table_id": table.table_id or f"table-{index + 1}",
                    "caption": caption,
                    "text": _truncate(text, 3500),
                },
            )
        )
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [snippet for _, _, snippet in scored[:6]]


def _rows_text(rows: list[Any]) -> str:
    lines = []
    for row in rows[:20]:
        if isinstance(row, dict):
            values = [f"{key}: {value}" for key, value in row.items() if str(value).strip()]
            line = " | ".join(values)
        elif isinstance(row, list):
            line = " | ".join(str(value) for value in row if str(value).strip())
        else:
            line = str(row)
        line = _clean_text(line)
        if line:
            lines.append(line)
    return "\n".join(lines)


def _merge_with_fallback(
    *,
    study_id: str,
    question_pico: QuestionPICO,
    parsed: dict[str, Any],
    fallback_item: StudyPIOCharacteristics,
) -> StudyPIOCharacteristics:
    population = _text_from_value(parsed.get("population"))
    interventions = _interventions_from_payload(parsed.get("interventions"))
    comparators = _comparators_from_payload(parsed.get("comparators"))
    outcomes = _outcomes_from_payload(parsed.get("outcomes"))

    if not population:
        population = fallback_item.population.description
    if not interventions:
        interventions = fallback_item.interventions
    if not comparators:
        comparators = fallback_item.comparators
    if not outcomes:
        outcomes = fallback_item.outcomes
    outcomes = _augment_process_outcomes_with_pico(outcomes=outcomes, question_pico=question_pico)

    warnings = [str(item).strip() for item in parsed.get("warnings") or [] if str(item).strip()]
    note = "LLM extraction with rule fallback for missing fields."
    if warnings:
        note = f"{note} Warnings: {'; '.join(warnings[:3])}"
    return StudyPIOCharacteristics(
        study_id=study_id,
        population=StudyPopulationCharacteristics(description=population),
        interventions=interventions,
        comparators=comparators,
        outcomes=outcomes,
        notes=note,
    )


def _interventions_from_payload(value: Any) -> list[StudyInterventionCharacteristics]:
    return [
        StudyInterventionCharacteristics(
            label=_short_label(item.get("label") or item.get("name") or item.get("description")),
            description=_clean_text(item.get("description") or item.get("text") or item.get("label") or item.get("name")),
        )
        for item in _list_of_dicts(value)
        if _clean_text(item.get("description") or item.get("text") or item.get("label") or item.get("name"))
    ]


def _comparators_from_payload(value: Any) -> list[StudyComparatorCharacteristics]:
    return [
        StudyComparatorCharacteristics(
            label=_short_label(item.get("label") or item.get("name") or item.get("description")),
            description=_clean_text(item.get("description") or item.get("text") or item.get("label") or item.get("name")),
        )
        for item in _list_of_dicts(value)
        if _clean_text(item.get("description") or item.get("text") or item.get("label") or item.get("name"))
    ]


def _outcomes_from_payload(value: Any) -> list[StudyOutcomeCharacteristics]:
    return [
        StudyOutcomeCharacteristics(
            outcome_label=_short_label(item.get("outcome_label") or item.get("label") or item.get("name") or item.get("measurement")),
            measurement=_clean_text(item.get("measurement") or item.get("description") or item.get("text") or item.get("outcome_label")),
        )
        for item in _list_of_dicts(value)
        if _clean_text(item.get("measurement") or item.get("description") or item.get("text") or item.get("outcome_label"))
    ]


def _augment_process_outcomes_with_pico(
    *,
    outcomes: list[StudyOutcomeCharacteristics],
    question_pico: QuestionPICO,
) -> list[StudyOutcomeCharacteristics]:
    if not outcomes or not question_pico.O:
        return outcomes
    outcome_text = " ".join(outcome.measurement for outcome in outcomes).lower()
    process_terms = (
        "implementation",
        "feasibility",
        "appropriateness",
        "adoption",
        "fidelity",
        "acceptability",
        "penetration",
        "sustainability",
        "survey response",
        "qualitative interview",
        "interviews with",
        "monthly audit",
        "screening eligibility",
        "recruitment",
        "withdrawal",
        "loss to follow",
        "receipt timing",
        "timely intervention",
        "referrals",
    )
    if not any(term in outcome_text for term in process_terms):
        return outcomes
    existing = {token for outcome in outcomes for token in _pico_terms_from_values([outcome.measurement])}
    augmented = list(outcomes)
    for item in question_pico.O:
        text = _clean_text(item)
        if not text:
            continue
        item_terms = _pico_terms_from_values([text])
        if item_terms & existing:
            continue
        existing.update(item_terms)
        augmented.append(
            StudyOutcomeCharacteristics(
                outcome_label=_short_label(text),
                measurement=text,
            )
        )
    return augmented


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        text = _clean_text(value)
        return [{"description": text}] if text else []
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        if isinstance(item, dict):
            items.append(item)
        else:
            text = _clean_text(item)
            if text:
                items.append({"description": text})
    return items


def _text_from_value(value: Any) -> str:
    if isinstance(value, dict):
        return _clean_text(value.get("description") or value.get("text") or value.get("label"))
    return _clean_text(value)


def _with_note(item: StudyPIOCharacteristics, note: str) -> StudyPIOCharacteristics:
    return StudyPIOCharacteristics(
        study_id=item.study_id,
        population=item.population,
        interventions=item.interventions,
        comparators=item.comparators,
        outcomes=item.outcomes,
        notes=note,
    )


def _pico_terms(question_pico: QuestionPICO) -> set[str]:
    return _pico_terms_from_values([*question_pico.P, *question_pico.I, *question_pico.C, *question_pico.O])


def _pico_terms_from_values(values: list[str]) -> set[str]:
    stopwords = {
        "and",
        "for",
        "the",
        "with",
        "from",
        "measurement",
        "procedure",
        "subscale",
        "scale",
    }
    terms: set[str] = set()
    for value in values:
        lowered = str(value).lower()
        if lowered.strip():
            terms.add(re.sub(r"[^a-z0-9]+", " ", lowered).strip())
        for token in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", lowered):
            token = token.strip("-")
            if token and token not in stopwords:
                terms.add(token)
    return terms


def _clean_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20].rstrip() + " [... truncated]"


def _short_label(value: Any) -> str:
    text = _clean_text(value)
    return text[:80].rstrip(" ,.;:") or "unspecified"
