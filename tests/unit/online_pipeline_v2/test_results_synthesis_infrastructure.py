"""Cross-boundary checks after Results moved into Study Data Collection."""

from pathlib import Path

from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.tasks.evidence_synthesis import (
    evidence_synthesis_output_schema,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.tasks.study_data_collection import (
    study_data_collection_output_schema,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime.skill_loader import (
    load_skill,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.formats.study_results import (
    STUDY_ARMS_HEADERS,
    STUDY_RESULTS_HEADERS,
)


_SKILLS = (
    Path(__file__).parents[3]
    / "backend/src/ebm_backend/online_pipeline_v2/infrastructure/agent_execution/skills"
)
_COLLECTION_SKILL = _SKILLS / "study_data_collection/collect-study-data"
_SYNTHESIS_SKILL = _SKILLS / "evidence_synthesis/synthesize-evidence"


def test_current_revman_projection_headers_remain_fixed() -> None:
    assert STUDY_ARMS_HEADERS == (
        "Study",
        "Arm",
        "Description",
        "Intervention",
    )
    assert "Cases" in STUDY_RESULTS_HEADERS
    assert "Sample size" in STUDY_RESULTS_HEADERS
    assert "Footnotes" in STUDY_RESULTS_HEADERS


def test_agent_control_schemas_are_compact_control_objects() -> None:
    collection = study_data_collection_output_schema()["properties"]
    synthesis = evidence_synthesis_output_schema()["properties"]
    assert "progress" not in collection
    assert "progress" not in synthesis
    assert "human_independent_extraction_satisfied" in collection


def test_current_collection_and_synthesis_skills_load_without_retrieval_scripts() -> None:
    collection = load_skill(_COLLECTION_SKILL)
    synthesis = load_skill(_SYNTHESIS_SKILL)
    assert collection.name == "collect-study-data"
    assert synthesis.name == "synthesize-evidence"
    assert not any("retriev" in path.name for path in _COLLECTION_SKILL.rglob("*.py"))
    assert not any("retriev" in path.name for path in _SYNTHESIS_SKILL.rglob("*.py"))


def test_split_results_skill_is_not_a_current_runtime_contract() -> None:
    assert not (
        _SKILLS / "study_results/extract-study-results/SKILL.md"
    ).exists()
    assert not (
        _SKILLS / "study_characteristics/collect-study-characteristics/SKILL.md"
    ).exists()
