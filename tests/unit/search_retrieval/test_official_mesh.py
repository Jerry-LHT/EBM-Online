from __future__ import annotations

from io import BytesIO

import pytest

from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.errors import (
    SearchRetrievalStageError,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.official_mesh import (
    OfficialMeshLookupClient,
)


class _FakeResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def test_mesh_lookup_retries_malformed_json_once_and_reuses_details(monkeypatch) -> None:
    payloads = [
        b"not-json",
        b'[{"resource":"https://id.nlm.nih.gov/mesh/D006973","label":"Hypertension"}]',
        b'{"terms":[{"label":"Hypertension","preferred":true},{"label":"Blood Pressure, High"}]}',
    ]
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        payload = payloads[calls]
        calls += 1
        return _FakeResponse(payload)

    monkeypatch.setattr(
        "ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.official_mesh.time.sleep",
        lambda _: None,
    )

    descriptor = OfficialMeshLookupClient(
        opener=opener,
        retries=1,
        requests_per_second=0,
    ).resolve(label="Hypertension")

    assert descriptor is not None
    assert descriptor.heading == "Hypertension"
    assert descriptor.entry_terms == ["Blood Pressure, High"]
    assert calls == 3


def test_mesh_lookup_reports_retry_exhaustion(monkeypatch) -> None:
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        calls += 1
        return _FakeResponse(b"not-json")

    monkeypatch.setattr(
        "ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.official_mesh.time.sleep",
        lambda _: None,
    )

    with pytest.raises(SearchRetrievalStageError) as error:
        OfficialMeshLookupClient(
            opener=opener,
            retries=1,
            requests_per_second=0,
        ).resolve(label="Hypertension")

    assert error.value.stage == "mesh_lookup"
    assert error.value.attempts == 2
    assert calls == 2


def test_mesh_lookup_retries_invalid_descriptor_shape_once(monkeypatch) -> None:
    payloads = [
        b'["invalid"]',
        b'[{"resource":"https://id.nlm.nih.gov/mesh/D006973","label":"Hypertension"}]',
        b'{"terms":[{"label":"Hypertension","preferred":true}]}',
    ]
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        payload = payloads[calls]
        calls += 1
        return _FakeResponse(payload)

    monkeypatch.setattr(
        "ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.official_mesh.time.sleep",
        lambda _: None,
    )

    descriptor = OfficialMeshLookupClient(
        opener=opener,
        retries=1,
        requests_per_second=0,
    ).resolve(label="Hypertension")

    assert descriptor is not None
    assert descriptor.heading == "Hypertension"
    assert calls == 3
