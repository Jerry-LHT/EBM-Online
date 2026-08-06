"""Repository layout checks for Online Pipeline v2 Agent Skills."""

from pathlib import Path

from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime.skill_loader import (
    load_skill,
)


_INFRASTRUCTURE_ROOT = (
    Path(__file__).resolve().parents[3]
    / "backend/src/ebm_backend/online_pipeline_v2/infrastructure"
)
_SKILLS_ROOT = _INFRASTRUCTURE_ROOT / "agent_execution" / "skills"
_EXPECTED_TASK_SKILLS = {
    ("evidence_search", "evidence-search"),
    ("evidence_synthesis", "synthesize-evidence"),
    ("grade_summary_of_findings", "grade-evidence-and-build-sof"),
    ("q2protocol", "draft-q2protocol"),
    ("risk_of_bias", "risk-of-bias"),
    ("study_data_collection", "collect-study-data"),
    ("study_selection", "select-studies"),
    ("systematic_review_reporting", "compose-systematic-review"),
}
_EXPECTED_SHARED_SKILLS = {
    ("shared", "find-and-read-methodology"),
    ("shared", "find-and-read-reports"),
}
_EXPECTED_SKILLS = _EXPECTED_TASK_SKILLS | _EXPECTED_SHARED_SKILLS


def test_repository_skills_are_grouped_under_one_business_asset_root() -> None:
    skill_files = tuple(sorted(_SKILLS_ROOT.glob("*/*/SKILL.md")))
    actual = {
        (
            skill_file.parent.parent.name,
            skill_file.parent.name,
        )
        for skill_file in skill_files
    }

    assert actual == _EXPECTED_SKILLS
    assert not tuple(_INFRASTRUCTURE_ROOT.glob("*/skills/*/SKILL.md"))
    assert {
        path.name
        for path in _INFRASTRUCTURE_ROOT.iterdir()
        if path.is_dir() and path.name != "__pycache__"
    } == {
        "agent_execution",
        "agent_runtime",
        "background",
        "grade",
        "persistence",
        "systematic_review",
    }


def test_every_repository_skill_passes_the_runtime_loader() -> None:
    for business, skill_name in sorted(_EXPECTED_SKILLS):
        package = load_skill(_SKILLS_ROOT / business / skill_name)

        assert package.name == skill_name
        assert package.source_path == (
            _SKILLS_ROOT / business / skill_name
        ).resolve()
        assert len(package.sha256) == 64


def test_composition_root_owns_all_task_skill_bindings() -> None:
    from ebm_backend.online_pipeline_v2.interfaces.api.dependencies import (
        _configured_skill_paths_by_task,
        _METHODOLOGY_ACCESS_SKILL_PATH,
        _REPORT_ACCESS_SKILL_PATH,
        _TASK_COMPANION_SKILL_PATHS,
        _TASK_SKILL_PATHS,
    )

    expected_paths = {
        (_SKILLS_ROOT / business / skill_name).resolve()
        for business, skill_name in _EXPECTED_TASK_SKILLS
    }
    assert {path.resolve() for path in _TASK_SKILL_PATHS.values()} == expected_paths
    methodology = (
        _SKILLS_ROOT / "shared" / "find-and-read-methodology"
    ).resolve()
    report_access = (
        _SKILLS_ROOT / "shared" / "find-and-read-reports"
    ).resolve()
    assert set(_TASK_COMPANION_SKILL_PATHS) == set(_TASK_SKILL_PATHS)
    for task, companions in _TASK_COMPANION_SKILL_PATHS.items():
        expected = (
            (methodology, report_access)
            if task
            in {"study_selection", "study_data_collection", "risk_of_bias"}
            else (methodology,)
        )
        assert tuple(path.resolve() for path in companions) == expected
    assert _METHODOLOGY_ACCESS_SKILL_PATH.resolve() == methodology
    assert _REPORT_ACCESS_SKILL_PATH.resolve() == (
        _SKILLS_ROOT / "shared" / "find-and-read-reports"
    ).resolve()
    configured = _configured_skill_paths_by_task()
    for task, companions in _TASK_COMPANION_SKILL_PATHS.items():
        assert configured[task] == (_TASK_SKILL_PATHS[task], *companions)
    assert configured["study_data_collection"] == (
        _TASK_SKILL_PATHS["study_data_collection"],
        _METHODOLOGY_ACCESS_SKILL_PATH,
        _REPORT_ACCESS_SKILL_PATH,
    )

    application_root = _INFRASTRUCTURE_ROOT.parent / "application"
    for source in application_root.rglob("*.py"):
        content = source.read_text(encoding="utf-8")
        assert "_SKILL_PATH" not in content
        assert "infrastructure/agent_execution/skills" not in content
