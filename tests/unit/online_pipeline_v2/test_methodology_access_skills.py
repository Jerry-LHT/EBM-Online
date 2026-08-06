"""Deterministic checks for shared methodology discovery and reading."""

from pathlib import Path


_ROOT = (
    Path(__file__).resolve().parents[3]
    / "backend/src/ebm_backend/online_pipeline_v2/infrastructure/agent_execution/skills"
)
_SHARED_SKILL = _ROOT / "shared/find-and-read-methodology"
_PARENT_SKILLS = (
    _ROOT / "q2protocol/draft-q2protocol",
    _ROOT / "evidence_search/evidence-search",
    _ROOT / "study_selection/select-studies",
    _ROOT / "study_data_collection/collect-study-data",
    _ROOT / "risk_of_bias/risk-of-bias",
    _ROOT / "evidence_synthesis/synthesize-evidence",
    _ROOT / "grade_summary_of_findings/grade-evidence-and-build-sof",
    _ROOT / "systematic_review_reporting/compose-systematic-review",
)


def test_shared_methodology_skill_is_small_and_provider_neutral() -> None:
    assert (_SHARED_SKILL / "SKILL.md").is_file()
    assert (_SHARED_SKILL / "agents/openai.yaml").is_file()
    assert (
        _SHARED_SKILL
        / "references/authority-discovery-and-sufficiency.md"
    ).is_file()
    assert not (_SHARED_SKILL / "scripts").exists()
    assert not (_SHARED_SKILL / "assets").exists()


def test_shared_methodology_skill_requires_execution_bearing_authority() -> None:
    skill = (_SHARED_SKILL / "SKILL.md").read_text(encoding="utf-8")
    reference = (
        _SHARED_SKILL
        / "references/authority-discovery-and-sufficiency.md"
    ).read_text(encoding="utf-8")
    combined = f"{skill}\n{reference}"

    assert "version landing pages" in skill
    assert "is not evidence" in skill
    assert "required sections or steps" in skill
    assert "conditional paths" in skill
    assert "llm_fallback" in skill
    assert "never present that knowledge as a read authority" in skill
    assert "existing methodology, authority, decision" in skill
    assert "Do not create a separate methodology artifact" in skill
    assert "authority access gap is" in skill
    assert "return `completed` with a warning" in skill
    assert "required professional step or target remains" in skill
    assert "not a required document checklist" in reference
    assert "No fixed site list" in combined
    assert "Do not reproduce an external standard" in combined


def test_all_eight_parent_tasks_use_the_shared_methodology_boundary() -> None:
    for parent in _PARENT_SKILLS:
        content = (parent / "SKILL.md").read_text(encoding="utf-8")
        assert "`find-and-read-methodology`" in content


def test_current_direct_benchmark_runners_stage_the_shared_skill() -> None:
    from benchmark.online_pipeline_v2.EvidenceSearch.experiments.run_upstream_protocol import (
        METHODOLOGY_SKILL as search_methodology,
    )
    from benchmark.online_pipeline_v2.GRADE.adapter.run_manual import (
        _METHODOLOGY_SKILL_PATH as grade_methodology,
    )
    from benchmark.online_pipeline_v2.Q2Protocol.experiments.run_protocol_with_pubmed import (
        METHODOLOGY_SKILL as protocol_methodology,
    )
    from benchmark.online_pipeline_v2.RiskOfBias.adapter.run_manual import (
        _SKILL_PATHS as risk_paths,
    )
    from benchmark.online_pipeline_v2.StudyDataCollection.adapter.run_manual import (
        _SKILL_PATHS as collection_paths,
    )
    from benchmark.online_pipeline_v2.StudySelection.adapter.run_manual import (
        _SKILL_PATHS as selection_paths,
    )

    expected = _SHARED_SKILL.resolve()
    assert risk_paths[1].resolve() == expected
    assert collection_paths[1].resolve() == expected
    assert selection_paths[1].resolve() == expected
    assert protocol_methodology.resolve() == expected
    assert search_methodology.resolve() == expected
    assert grade_methodology.resolve() == expected

    synthesis_runner = (
        Path(__file__).resolve().parents[3]
        / "benchmark/online_pipeline_v2/EvidenceSynthesis/adapter/run_manual.py"
    ).read_text(encoding="utf-8")
    assert 'shared/find-and-read-methodology' in synthesis_runner
    assert "skill_paths=(_SYNTHESIS_SKILL, _METHODOLOGY_SKILL)" in synthesis_runner


def test_evidence_synthesis_limits_web_to_methodology() -> None:
    skill = (_ROOT / "evidence_synthesis/synthesize-evidence/SKILL.md").read_text(
        encoding="utf-8"
    )
    contract = (
        _ROOT
        / "evidence_synthesis/synthesize-evidence/references/task-contract.md"
    ).read_text(encoding="utf-8")

    assert "Web and network access may be used only" in skill
    assert "closed scientific evidence set" in skill
    assert "Web access is limited to" in contract
    assert "Studies,\nReports, new result data" in contract

    task_source = (
        Path(__file__).resolve().parents[3]
        / "backend/src/ebm_backend/online_pipeline_v2/infrastructure/"
        "agent_execution/tasks/evidence_synthesis.py"
    ).read_text(encoding="utf-8")
    assert "enable_workspace_network=True" in task_source
    assert "enable_web_search=True" in task_source
    assert "do not retrieve scientific evidence" in task_source
