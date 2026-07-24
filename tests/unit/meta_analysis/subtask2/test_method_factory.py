from __future__ import annotations

from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.factory import (
    build_production_study_evidence_agent,
)


def test_source_workspace_agent_is_the_current_study_evidence_adapter() -> None:
    adapter = build_production_study_evidence_agent()
    assert adapter.__class__.__module__.endswith("source_workspace_agent.method")
    assert callable(adapter.run)
