# meta_analysis subtask5 dataset

Files:
- `instances.jsonl`
  - `instance_id`, `review_id`
  - `analysis_setting`
  - `study_result_rows`: canonical official study rows for this setting; duplicated overall/subgroup source rows keep the subgroup assignment
  - `analysis_methods`: official method record for this setting
  - `included_studies`, `source_context`, `source_refs`
- `gold.jsonl`
  - `instance_id`, `review_id`, `source`
  - `overall_estimates`: list of official overall pooled estimates for this setting
    - `overall_estimate_id`, `setting_id`, `setting_family_id`, `method_id`, `candidate_id`
    - `included_study_ids`, `study_count`, `participant_count`
    - `data_type`, `effect_measure`, `analysis_model`, `statistical_method`, `ci_level`
    - `effect_value`, `ci_lower`, `ci_upper`
    - `prediction_interval`, `heterogeneity`, `effect_test`
    - `estimation_status`, `source_joined`, `source`
