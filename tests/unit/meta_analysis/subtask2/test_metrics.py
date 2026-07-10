from benchmark.online_pipeline.meta_analysis.subtask2_study_results.evaluation.metrics import evaluate_predictions


def test_subtask2_metrics_use_workflow_targets_and_field_rates() -> None:
    gold_by_id = {
        "i1": {
            "study_result_rows": [
                {
                    "row_id": "target::setting::1::a-2020::0",
                    "setting_id": "setting::1",
                    "study_id": "A 2020",
                    "review_label": "review_level_denominator_mismatch",
                    "data_type": "Dichotomous",
                    "result_data": {
                        "experimental_events": 1,
                        "experimental_total": 10,
                        "control_events": 2,
                        "control_total": 10,
                    },
                },
                {
                    "row_id": "target::setting::1::b-2021::0",
                    "setting_id": "setting::1",
                    "study_id": "B 2021",
                    "data_type": "Dichotomous",
                    "result_data": {
                        "experimental_events": 3,
                        "experimental_total": 12,
                        "control_events": 4,
                        "control_total": 12,
                    },
                },
            ],
        },
        "i2": {
            "study_result_rows": [
                {
                    "row_id": "target::setting::2::c-2022::0",
                    "setting_id": "setting::2",
                    "study_id": "C 2022",
                    "data_type": "Continuous",
                    "result_data": {
                        "experimental_mean": 1.0,
                        "experimental_sd": 0.5,
                        "experimental_total": 20,
                        "control_mean": 2.0,
                        "control_sd": 0.6,
                        "control_total": 20,
                    },
                },
                {
                    "row_id": "target::setting::2::c-2022::1",
                    "setting_id": "setting::2",
                    "study_id": "C 2022",
                    "data_type": "Continuous",
                    "result_data": {
                        "experimental_mean": 1.2,
                        "experimental_sd": 0.5,
                        "experimental_total": 20,
                        "control_mean": 2.0,
                        "control_sd": 0.6,
                        "control_total": 20,
                    },
                },
            ],
        },
    }
    predictions = [
        {
            "instance_id": "i1",
            "study_result_rows": [
                {
                    "row_id": "target::setting::1::a-2020::0",
                    "setting_id": "setting::1",
                    "study_id": "A 2020",
                    "data_type": "Dichotomous",
                    "result_data": {
                        "experimental_events": 1,
                        "experimental_total": 10,
                        "control_events": 9,
                        "control_total": 10,
                    },
                }
            ],
        },
        {
            "instance_id": "i2",
            "study_result_rows": [
                {
                    "row_id": "target::setting::2::c-2022::0",
                    "setting_id": "setting::2",
                    "study_id": "C 2022",
                    "data_type": "Continuous",
                    "result_data": {
                        "experimental_mean": 1.0,
                        "experimental_sd": 0.5,
                        "experimental_total": 20,
                        "control_mean": 2.0,
                        "control_sd": 0.6,
                        "control_total": 20,
                    },
                }
            ],
        },
    ]

    metrics = evaluate_predictions(predictions, gold_by_id)

    assert metrics["comparison_count"] == 4
    assert metrics["evaluable_target_count"] == 4
    assert metrics["duplicate_gold_target_count"] == 0
    assert metrics["target_completion_rate"] == 0.5
    assert metrics["target_numeric_close_rate"] == 0.25
    assert metrics["target_value_only_close_rate"] == 0.25
    assert metrics["field_close_rate"] == 9 / 20
    assert metrics["value_only_field_close_rate"] == 5 / 12
    assert metrics["denominator_field_close_rate"] == 4 / 8
    assert metrics["field_close_rates"]["experimental_total"] == 0.5
    assert metrics["review_label_counts"] == {"review_level_denominator_mismatch": 1}


def test_subtask2_legacy_metrics_fallback_to_extraction_task_id() -> None:
    gold_by_id = {
        "i1": {
            "study_result_rows": [
                {
                    "row_id": "target::setting::1::a-2020::0",
                    "setting_id": "setting::1",
                    "study_id": "A 2020",
                    "data_type": "Dichotomous",
                    "result_data": {
                        "experimental_events": 1,
                        "experimental_total": 10,
                        "control_events": 2,
                        "control_total": 10,
                    },
                }
            ],
        }
    }
    predictions = [
        {
            "instance_id": "i1",
            "study_result_rows": [
                {
                    "row_id": "task::setting::1::a-2020",
                    "extraction_task_id": "task::setting::1::a-2020",
                    "setting_id": "setting::1",
                    "study_id": "A 2020",
                    "extraction_status": "extracted",
                    "data_type": "Dichotomous",
                    "result_data": {
                        "experimental_events": 1,
                        "experimental_total": 10,
                        "control_events": 2,
                        "control_total": 10,
                    },
                }
            ],
        }
    ]

    metrics = evaluate_predictions(predictions, gold_by_id)

    assert metrics["target_completion_rate"] == 1.0
    assert metrics["target_numeric_close_rate"] == 1.0


def test_subtask2_metrics_report_audit_included_subset() -> None:
    gold_by_id = {
        "i1": {
            "study_result_rows": [
                {
                    "row_id": "target::setting::1::a-2020::0",
                    "setting_id": "setting::1",
                    "study_id": "A 2020",
                    "review_label": "source_data_missing_not_for_eval",
                    "data_type": "Dichotomous",
                    "result_data": {
                        "experimental_events": 1,
                        "experimental_total": 10,
                        "control_events": 2,
                        "control_total": 10,
                    },
                },
                {
                    "row_id": "target::setting::1::b-2021::0",
                    "setting_id": "setting::1",
                    "study_id": "B 2021",
                    "review_label": "suggested_for_eval",
                    "data_type": "Dichotomous",
                    "result_data": {
                        "experimental_events": 3,
                        "experimental_total": 12,
                        "control_events": 4,
                        "control_total": 12,
                    },
                },
            ],
        }
    }
    predictions = [
        {
            "instance_id": "i1",
            "study_result_rows": [
                {
                    "row_id": "target::setting::1::a-2020::0",
                    "setting_id": "setting::1",
                    "study_id": "A 2020",
                    "extraction_status": "extracted",
                    "data_type": "Dichotomous",
                    "result_data": {
                        "experimental_events": 1,
                        "experimental_total": 10,
                        "control_events": 2,
                        "control_total": 10,
                    },
                }
            ],
        }
    ]

    metrics = evaluate_predictions(predictions, gold_by_id)

    assert metrics["audit_material_problem_target_count"] == 1
    assert metrics["audit_included_target_count"] == 1
    assert metrics["audit_included_target_completion_rate"] == 0.0


def test_subtask2_candidate_set_metrics_match_rows_without_slots() -> None:
    gold_by_id = {
        "i1": {
            "study_result_candidate_sets": [
                {
                    "extraction_task_id": "task::setting::1::study-a",
                    "study_id": "Study A",
                    "review_label": "review_level_denominator_mismatch",
                    "gold_candidate_results": [
                        {
                            "data_type": "Dichotomous",
                            "result_data": {
                                "experimental_events": 2,
                                "experimental_total": 23,
                                "control_events": 1,
                                "control_total": 7,
                            },
                        },
                        {
                            "data_type": "Dichotomous",
                            "result_data": {
                                "experimental_events": 0,
                                "experimental_total": 21,
                                "control_events": 1,
                                "control_total": 7,
                            },
                        },
                    ],
                }
            ],
        }
    }
    predictions = [
        {
            "instance_id": "i1",
            "study_result_rows": [
                {
                    "row_id": "task::setting::1::study-a",
                    "study_id": "Study A",
                    "extraction_status": "extracted",
                    "candidate_results": [
                        {
                            "match_status": "matched",
                            "include_in_estimate": True,
                            "data_type": "Dichotomous",
                            "result_data": {
                                "experimental_events": 0,
                                "experimental_total": 21,
                                "control_events": 1,
                                "control_total": 7,
                            },
                        },
                        {
                            "match_status": "matched",
                            "include_in_estimate": True,
                            "data_type": "Dichotomous",
                            "result_data": {
                                "experimental_events": 2,
                                "experimental_total": 23,
                                "control_events": 1,
                                "control_total": 7,
                            },
                        },
                    ],
                }
            ],
        }
    ]

    metrics = evaluate_predictions(predictions, gold_by_id)

    assert metrics["comparison_count"] == 1
    assert metrics["candidate_gold_row_count"] == 2
    assert metrics["candidate_matched_row_count"] == 2
    assert metrics["candidate_row_recall"] == 1.0
    assert metrics["candidate_row_precision"] == 1.0
    assert metrics["candidate_value_only_recall"] == 1.0
    assert metrics["full_set_recall_rate"] == 1.0
    assert metrics["downstream_ready_rate"] == 1.0
    assert metrics["review_label_counts"] == {"review_level_denominator_mismatch": 1}


def test_subtask2_metrics_separate_value_only_from_denominators() -> None:
    gold_by_id = {
        "i1": {
            "study_result_rows": [
                {
                    "row_id": "target::setting::1::a-2020::0",
                    "setting_id": "setting::1",
                    "study_id": "A 2020",
                    "data_type": "Dichotomous",
                    "result_data": {
                        "experimental_events": 2,
                        "experimental_total": 23,
                        "control_events": 1,
                        "control_total": 7,
                    },
                }
            ],
        }
    }
    predictions = [
        {
            "instance_id": "i1",
            "study_result_rows": [
                {
                    "row_id": "target::setting::1::a-2020::0",
                    "setting_id": "setting::1",
                    "study_id": "A 2020",
                    "data_type": "Dichotomous",
                    "result_data": {
                        "experimental_events": 2,
                        "experimental_total": 22,
                        "control_events": 1,
                        "control_total": 22,
                    },
                    "candidate_results": [
                        {
                            "data_type": "Dichotomous",
                            "result_data": {
                                "experimental_events": 2,
                                "experimental_total": 22,
                                "control_events": 1,
                                "control_total": 22,
                            },
                        }
                    ],
                }
            ],
        }
    ]

    metrics = evaluate_predictions(predictions, gold_by_id)

    assert metrics["target_numeric_close_rate"] == 0.0
    assert metrics["target_value_only_close_rate"] == 1.0
    assert metrics["denominator_field_close_rate"] == 0.0
    assert metrics["candidate_numeric_recall_rate"] == 0.0
    assert metrics["candidate_value_only_recall_rate"] == 1.0


def test_subtask2_item_coverage_does_not_mix_fields_across_candidates() -> None:
    gold_by_id = {
        "i1": {
            "study_result_rows": [
                {
                    "row_id": "target::setting::1::a-2020::0",
                    "setting_id": "setting::1",
                    "study_id": "A 2020",
                    "data_type": "Dichotomous",
                    "result_data": {
                        "experimental_events": 2,
                        "experimental_total": 20,
                        "control_events": 3,
                        "control_total": 20,
                    },
                }
            ]
        }
    }
    predictions = [
        {
            "instance_id": "i1",
            "study_result_rows": [
                {
                    "row_id": "target::setting::1::a-2020::0",
                    "setting_id": "setting::1",
                    "study_id": "A 2020",
                    "result_items": [
                        {
                            "match_status": "possible",
                            "data_type": "Dichotomous",
                            "result_data": {"experimental_events": 2, "experimental_total": 20},
                        },
                        {
                            "match_status": "possible",
                            "data_type": "Dichotomous",
                            "result_data": {"control_events": 3, "control_total": 20},
                        },
                    ],
                }
            ],
        }
    ]

    metrics = evaluate_predictions(predictions, gold_by_id)

    assert metrics["candidate_item_complete_recall"] == 0.0
    assert metrics["candidate_item_any_value_recall"] == 1.0
    assert metrics["candidate_item_field_coverage"] == 0.5
    assert metrics["candidate_field_recall_rate"] == 1.0
