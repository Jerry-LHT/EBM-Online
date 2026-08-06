from __future__ import annotations

import json

from benchmark.ebm_application.metasyn.agent import (
    _meta_progress_observer,
    _validate_study_evidence_checkpoint,
)
from ebm_backend.online_pipeline.application.use_cases.run_meta_analysis import (
    MetaAnalysisProgressEvent,
)


def test_study_evidence_checkpoint_requires_identity_and_resume_fields() -> None:
    payload = {
        "study_id": "study-1",
        "study_result_rows": [],
        "resolution_records": [],
        "data_rows": [],
        "coverage": {},
    }

    _validate_study_evidence_checkpoint(payload, study_id="study-1")


def test_study_evidence_checkpoint_rejects_wrong_study() -> None:
    payload = {
        "study_id": "study-2",
        "study_result_rows": [],
        "resolution_records": [],
        "data_rows": [],
        "coverage": {},
    }

    try:
        _validate_study_evidence_checkpoint(payload, study_id="study-1")
    except ValueError as exc:
        assert "study_id" in str(exc)
    else:
        raise AssertionError("wrong-study checkpoint should be rejected")


def test_meta_progress_observer_retains_repeated_events(tmp_path) -> None:
    observer = _meta_progress_observer(tmp_path)
    observer(MetaAnalysisProgressEvent(stage="candidate_resolution", status="running"))
    observer(MetaAnalysisProgressEvent(stage="candidate_resolution", status="completed"))

    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert [event["status"] for event in events] == ["running", "completed"]
    assert (tmp_path / "stages/candidate_resolution.json").exists()
