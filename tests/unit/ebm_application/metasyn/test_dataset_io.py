from pathlib import Path

from benchmark.ebm_application.metasyn.io import case_payload, load_case, write_json
from benchmark.ebm_application.metasyn.models import PilotArticle, PilotCase


def test_case_round_trip(tmp_path: Path) -> None:
    case = PilotCase(
        case_id=1,
        title="Title",
        question="Question",
        pico={"P": [], "I": [], "C": [], "O": [], "O_expanded": []},
        inclusion_criteria=[],
        exclusion_criteria=[],
        articles=[PilotArticle(7, "8", "Article", "Abstract", None)],
        gold={"Effect_Direction": "Positive"},
    )
    write_json(tmp_path / "cases" / "1.json", case_payload(case))
    loaded = load_case(tmp_path, 1)
    assert loaded == case
    assert loaded.articles[0].evidence_tier == "abstract_only"
