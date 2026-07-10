from __future__ import annotations

from benchmark.online_pipeline.meta_analysis.evaluation_common.method_adapters import (
    build_subtask2_targets,
    build_subtask2_tasks,
    targetize_subtask2_gold,
)


def test_build_subtask2_targets_prefers_setting_study_candidates() -> None:
    instance = {
        "instance_id": "meta-analysis::CD003451::1::2::overall",
        "analysis_setting": {
            "setting_id": "setting::CD003451::1::2::overall",
            "eligible_study_candidates": [
                {
                    "study_id": "Minase 2019",
                    "article_id": "pmc::PMC6451935",
                    "extraction_targets": [
                        {"target_id": "target::setting::1::minase-2019::0", "extraction_hint": "Facemask"},
                        {"target_id": "target::setting::1::minase-2019::1", "extraction_hint": "Reverse Twin Block"},
                    ],
                }
            ],
        },
        "article_study_links": [{"study_id": "Minase 2019", "article_id": "pmc::PMC6451935"}],
    }

    targets = build_subtask2_targets(instance=instance, gold={"study_result_rows": []}, hint_policy="legacy")

    assert [target["target_id"] for target in targets] == [
        "target::setting::1::minase-2019::0",
        "target::setting::1::minase-2019::1",
    ]
    assert [target["extraction_hint"] for target in targets] == ["Facemask", "Reverse Twin Block"]


def test_build_subtask2_tasks_prefers_candidate_set_task_id() -> None:
    task_id = "task::setting::CD011769::14::3::subgroup::4::lemonnier-2017"
    instance = {
        "instance_id": "meta-analysis::CD011769::14::3::subgroup::4",
        "analysis_setting": {
            "setting_id": "setting::CD011769::14::3::subgroup::4",
            "eligible_study_candidates": [
                {
                    "study_id": "Lemonnier 2017",
                    "article_id": "pmc::PMC5416661",
                    "extraction_task_id": task_id,
                }
            ],
        },
        "article_study_links": [{"study_id": "Lemonnier 2017", "article_id": "pmc::PMC5416661"}],
    }

    tasks = build_subtask2_tasks(instance=instance, gold={"study_result_candidate_sets": []})

    assert tasks == [
        {
            "extraction_task_id": task_id,
            "target_id": task_id,
            "setting_id": "setting::CD011769::14::3::subgroup::4",
            "study_id": "Lemonnier 2017",
            "article_id": "pmc::PMC5416661",
        }
    ]


def test_build_subtask2_targets_reorders_planned_targets_to_gold_rows() -> None:
    instance = {
        "instance_id": "meta-analysis::example",
        "analysis_setting": {
            "setting_id": "setting::example",
            "eligible_study_candidates": [
                {"study_id": "Study A", "extraction_targets": [{"target_id": "target::a::0"}]},
                {"study_id": "Study B", "extraction_targets": [{"target_id": "target::b::0"}]},
            ],
        },
    }
    gold = {
        "study_result_rows": [
            {"setting_id": "setting::example", "study_id": "Study B"},
            {"setting_id": "setting::example", "study_id": "Study A"},
        ]
    }

    targets = build_subtask2_targets(instance=instance, gold=gold, hint_policy="legacy")

    assert [target["target_id"] for target in targets] == ["target::b::0", "target::a::0"]


def test_build_subtask2_targets_carries_instance_extraction_hint() -> None:
    instance = {
        "instance_id": "meta-analysis::example",
        "analysis_setting": {"setting_id": "setting::example"},
        "article_study_links": [{"study_id": "Study A", "article_id": "pmc::example"}],
        "source_context": {
            "study_row_footnotes": [
                {"study_id": "Study A", "subgroup": "Facemask", "footnote": "three-arm trial"}
            ]
        },
    }
    gold = {"study_result_rows": [{"setting_id": "setting::example", "study_id": "Study A"}]}

    targets = build_subtask2_targets(instance=instance, gold=gold, hint_policy="legacy")

    assert targets[0]["extraction_hint"] == "Facemask ; three-arm trial"


def test_targetize_subtask2_gold_is_idempotent() -> None:
    instance = {
        "instance_id": "meta-analysis::example",
        "analysis_setting": {"setting_id": "setting::example"},
        "article_study_links": [{"study_id": "Study A", "article_id": "pmc::example"}],
    }
    gold = {
        "study_result_rows": [
            {
                "row_id": "gold-row::1",
                "setting_id": "setting::example",
                "study_id": "Study A",
                "data_type": "Dichotomous",
                "result_data": {
                    "experimental_events": 1,
                    "experimental_total": 10,
                    "control_events": 2,
                    "control_total": 10,
                },
            }
        ]
    }

    first = targetize_subtask2_gold(instance=instance, gold=gold)
    second = targetize_subtask2_gold(instance=instance, gold=first)

    assert second["study_result_rows"][0]["result_items"][0]["result_data"] == {
        "experimental_events": 1,
        "experimental_total": 10,
        "control_events": 2,
        "control_total": 10,
    }
    assert "candidate_results" not in second["study_result_rows"][0]
