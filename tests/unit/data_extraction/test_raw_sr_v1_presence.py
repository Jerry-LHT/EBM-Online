from benchmark.online_pipeline.data_extraction.pilots.raw_sr_v1.build_pilot import (
    PROSE_SLICE_CHARS,
    TABLE_SLICE_CHARS,
    build_presence_slice,
    select_presence_matches,
)


def test_presence_slices_obey_source_limits() -> None:
    prose = {
        "kind": "section",
        "text": "a" * 800 + "19" + "b" * 800,
    }
    table = {
        "kind": "table",
        "text": "<table>" + "a" * 1200 + "2.88" + "b" * 1200 + "</table>",
    }

    prose_slice = build_presence_slice(source=prose, start=800, end=802)
    table_slice = build_presence_slice(source=table, start=1207, end=1211)

    assert len(prose_slice) <= PROSE_SLICE_CHARS
    assert "19" in prose_slice
    assert len(table_slice) <= TABLE_SLICE_CHARS
    assert "2.88" in table_slice


def test_presence_selection_caps_fields_and_total() -> None:
    matches = []
    for field_index in range(4):
        for occurrence_index in range(5):
            matches.append(
                {
                    "occurrence_id": f"occ-{field_index}-{occurrence_index}",
                    "field": f"field_{field_index}",
                    "value": "19",
                    "source_kind": "section",
                    "source_title": "Results",
                }
            )

    selected = select_presence_matches(matches)

    assert len(selected) == 8
    for field_index in range(4):
        assert (
            sum(item["field"] == f"field_{field_index}" for item in selected)
            <= 3
        )
