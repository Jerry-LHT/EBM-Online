# meta_analysis subtask3 dataset

Files:
- `instances.jsonl`
  - same top-level input shape as Subtask 2:
    - `instance_id`, `review_id`, `analysis_setting`, `included_studies`, `source_context`, `source_refs`
- `gold.jsonl`
  - `instance_id`, `review_id`, `source`
  - `analysis_methods`: list containing the official method record for this setting
    - `setting_id`, `method_id`
    - `effect_measure`, `analysis_model`, `statistical_method`, `ci_level`
    - `overall_estimates_enabled`, `subgroup_estimates_enabled`, `test_for_subgroup_differences`
    - `analysis_included_study_ids`
    - `source`
