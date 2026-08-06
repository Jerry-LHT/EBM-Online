"""Deterministic checks for the shared Report discovery and reading Skill."""

from pathlib import Path


_ROOT = (
    Path(__file__).resolve().parents[3]
    / "backend/src/ebm_backend/online_pipeline_v2/infrastructure/agent_execution/skills"
)
_SHARED_SKILL = _ROOT / "shared/find-and-read-reports"
_PARENT_SKILLS = (
    _ROOT / "study_selection/select-studies",
    _ROOT / "study_data_collection/collect-study-data",
    _ROOT / "risk_of_bias/risk-of-bias",
)
_REMOVED_SKILLS = (
    _ROOT / "study_selection/access-selection-reports",
    _ROOT / "study_characteristics/access-characteristics-reports",
    _ROOT / "study_results/access-results-reports",
    _ROOT / "risk_of_bias/access-risk-of-bias-reports",
)


def test_one_shared_report_access_skill_replaces_per_task_copies() -> None:
    assert (_SHARED_SKILL / "SKILL.md").is_file()
    assert (_SHARED_SKILL / "agents/openai.yaml").is_file()
    assert (
        _SHARED_SKILL / "references/discovery-and-reading.md"
    ).is_file()
    assert not (_SHARED_SKILL / "scripts").exists()
    assert all(not path.exists() for path in _REMOVED_SKILLS)


def test_shared_skill_preserves_agent_discovery_and_parent_boundaries() -> None:
    skill = (_SHARED_SKILL / "SKILL.md").read_text(encoding="utf-8")
    method = (
        _SHARED_SKILL / "references/discovery-and-reading.md"
    ).read_text(encoding="utf-8")
    combined = f"{skill}\n{method}"

    assert "No source list, site order, identifier" in skill
    assert "if a DOI fails" in skill
    assert "do not merely retry the DOI" in skill
    assert "401/403/429" in skill
    assert "HTML returned where a PDF was expected" in skill
    assert "Do not repeatedly" in skill
    assert "identity packet" in skill
    assert "HTTP success, a PDF link" in skill
    assert "copyright or" in skill
    assert "licensing uncertainty" in skill
    assert "neither a checklist nor a required order" in method
    assert "classify the" in method
    assert "current route as failed" in method
    assert "challenge/login pages" in method
    assert "fixed source list" in method
    assert "corrections, errata, retractions, expressions of concern" in skill
    assert "complete abstract-only" in skill
    assert "complete registry record" in skill
    assert "Do not create a separate access log" in skill
    assert "fetch_resource.py" not in combined


def test_shared_skill_rejects_access_control_bypass_and_full_text_sidecars() -> None:
    combined = "\n".join(
        (
            (_SHARED_SKILL / "SKILL.md").read_text(encoding="utf-8"),
            (_SHARED_SKILL / "references/discovery-and-reading.md").read_text(
                encoding="utf-8"
            ),
        )
    )

    assert "authentication and access-control bypasses may not" in combined
    assert "Do not authenticate, evade access" in combined
    assert "do not redistribute or save the full text" in combined
    assert "No source list, site order, identifier" in combined
    assert "fixed source list" in combined
    assert "fallback order" in combined
    assert "request-count rule" in combined


def test_shared_skill_reuses_persisted_routes_and_closes_real_investigation() -> None:
    combined = "\n".join(
        (
            (_SHARED_SKILL / "SKILL.md").read_text(encoding="utf-8"),
            (_SHARED_SKILL / "references/discovery-and-reading.md").read_text(
                encoding="utf-8"
            ),
        )
    )
    normalized = " ".join(combined.split()).lower()

    assert "persisted upstream reports" in normalized
    assert "reuse a previously verified route" in normalized
    assert "do not rediscover a report" in normalized
    assert "never bulk-convert bibliographic abstracts" in normalized
    assert "starting record contains only an abstract" in normalized
    assert "do not create a new shared cache" in normalized
    assert "not_started" in normalized
    assert "not_found" in normalized
    assert "unreachable" in normalized
    assert "partial access does not become" in normalized
    assert "never relabel it `unavailable`" in normalized


def test_report_dependent_parent_skills_preserve_reuse_and_task_boundaries() -> None:
    selection = (
        _ROOT / "study_selection/select-studies/SKILL.md"
    ).read_text(encoding="utf-8")
    collection = (
        _ROOT / "study_data_collection/collect-study-data/SKILL.md"
    ).read_text(encoding="utf-8")
    risk = (_ROOT / "risk_of_bias/risk-of-bias/SKILL.md").read_text(
        encoding="utf-8"
    )

    selection = " ".join(selection.split()).lower()
    collection = " ".join(collection.split()).lower()
    risk = " ".join(risk.split()).lower()

    assert "explicit worklist" in selection
    assert "do not bulk-mark" in selection
    assert "persisted report locators" in collection
    assert "do not repeat identity" in collection
    assert "persisted upstream report locators" in risk
    assert "do not treat an upstream abstract-only" in risk


def test_report_contract_keeps_snapshot_identity_access_and_eligibility_separate() -> None:
    selection = (
        _ROOT / "study_selection/select-studies/SKILL.md"
    ).read_text(encoding="utf-8")
    selection_reference = (
        _ROOT / "study_selection/select-studies/references/evidence-and-identity.md"
    ).read_text(encoding="utf-8")
    shared = (_SHARED_SKILL / "SKILL.md").read_text(encoding="utf-8")
    collection = (
        _ROOT / "study_data_collection/collect-study-data/SKILL.md"
    ).read_text(encoding="utf-8")
    collection_reference = (
        _ROOT
        / "study_data_collection/collect-study-data/references/evidence-boundary.md"
    ).read_text(encoding="utf-8")
    combined = " ".join(
        " ".join(
            (selection, selection_reference, shared, collection, collection_reference)
        ).lower().split()
    )

    assert "source snapshot, not proof" in combined
    assert "identity and study association independently of access" in combined
    assert "report access is evidence availability, not an eligibility criterion" in combined
    assert "keyword-assisted triage" in combined
    assert "does not prescribe manual processing" in combined
    assert "none alone proves reading" in combined
    assert "keywords alone do not establish eligibility" in combined
    assert "do not generate one templated" in combined
    assert "absence from an unverified snapshot cannot" in combined


def test_report_work_may_be_batched_without_delegating_professional_claims() -> None:
    selection = " ".join(
        (_ROOT / "study_selection/select-studies/SKILL.md")
        .read_text(encoding="utf-8")
        .lower()
        .split()
    )
    shared = " ".join(
        (_SHARED_SKILL / "SKILL.md").read_text(encoding="utf-8").lower().split()
    )
    collection = " ".join(
        (_ROOT / "study_data_collection/collect-study-data/SKILL.md")
        .read_text(encoding="utf-8")
        .lower()
        .split()
    )

    assert "batching, scripts" in selection
    assert "do not need to imitate manual keystrokes" in selection
    assert "automation may batch discovery" in shared
    assert "any efficient batch or scripted method" in shared
    assert "batching, scripts" in collection
    assert "does not require one model interaction per study" in collection


def test_evidence_search_labels_records_as_snapshots_not_complete_reports() -> None:
    contract = " ".join(
        (
            _ROOT / "evidence_search/evidence-search/references/output-contract.md"
        ).read_text(encoding="utf-8").lower().split()
    )

    assert "source-returned search snapshot and lead" in contract
    assert "not proof that a report was opened" in contract
    assert "do not silently crop returned modules" in contract
    assert "report access and task-specific reading are owned by downstream" in contract


def test_each_parent_task_loads_shared_method_but_owns_its_judgement() -> None:
    for parent in _PARENT_SKILLS:
        content = (parent / "SKILL.md").read_text(encoding="utf-8")
        assert "`find-and-read-reports`" in content
        assert "access-selection-reports" not in content
        assert "access-characteristics-reports" not in content
        assert "access-results-reports" not in content
        assert "access-risk-of-bias-reports" not in content


def test_each_benchmark_runner_loads_the_same_shared_skill() -> None:
    from benchmark.online_pipeline_v2.StudyDataCollection.adapter import (
        run_manual as data_collection_runner,
    )
    from benchmark.online_pipeline_v2.RiskOfBias.adapter.run_manual import (
        _SKILL_PATHS as risk_of_bias_skills,
    )
    from benchmark.online_pipeline_v2.StudySelection.adapter.run_manual import (
        _SKILL_PATHS as selection_skills,
    )

    expected = _SHARED_SKILL.resolve()
    assert selection_skills[2].resolve() == expected
    assert data_collection_runner._SKILL_PATHS[2].resolve() == expected
    assert risk_of_bias_skills[2].resolve() == expected
