from pathlib import Path

from benchmark.online_pipeline_v2.RiskOfBias.adapter.materialize import (
    build_selection_artifact,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.packages import (
    FileSelectionPackageStore,
)


ROOT = Path(__file__).resolve().parents[3]
CASE_ROOT = (
    ROOT
    / "benchmark"
    / "online_pipeline_v2"
    / "StudyDataCollection" / "CharacteristicsOfStudies"
    / "data"
    / "candidates"
    / "input"
    / "CD000143"
)
def test_selection_materializer_contains_only_requested_study(tmp_path: Path) -> None:
    store = FileSelectionPackageStore(tmp_path / "selection")
    artifact = build_selection_artifact(
        studies_csv=CASE_ROOT / "studies.csv",
        reports_csv=CASE_ROOT / "reports.csv",
        study_id="study_000002",
        store=store,
        review_id="pilot-review",
        protocol_version="pilot-protocol-v1",
    )

    assert artifact.summary.included_count == 1
    assert artifact.summary.reports_sought_count == 1
    manifest = store.validate(artifact.package_ref)
    assert manifest["collections"]["studies"]["record_count"] == 1
    assert manifest["collections"]["reports"]["record_count"] == 1
    assert manifest["collections"]["study_decisions"]["record_count"] == 1
