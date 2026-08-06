import json

from benchmark.ebm_application.beyond_abstracts.artifacts import ArtifactStore


def test_artifact_store_retains_append_only_events_and_stage_snapshots(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.start_stage("meta/planning", detail={"model": "fake"})
    store.json("meta/planning/input.json", {"question": "Q"})
    store.complete_stage("meta/planning")

    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert [event["status"] for event in events] == ["running", "completed"]
    assert json.loads((tmp_path / "meta/planning/status.json").read_text())["status"] == "completed"

