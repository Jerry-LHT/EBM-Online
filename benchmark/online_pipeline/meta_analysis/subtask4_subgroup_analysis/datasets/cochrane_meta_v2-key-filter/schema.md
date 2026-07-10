# meta_analysis subtask4 dataset

Files:
- `instances.jsonl`
  - `instance_id`, `review_id`
  - `analysis_setting`
  - `study_result_rows`: canonical official study rows for this setting; duplicated overall/subgroup source rows keep the subgroup assignment
  - `analysis_methods`: official method record for this setting
  - `included_studies`, `source_context`, `source_refs`
- `gold.jsonl`
  - `instance_id`, `review_id`, `source`
  - `subgroup_results`
    - `subgroup_estimates`: list of official subgroup pooled estimates for this setting
      - `subgroup_estimate_id`, `setting_id`, `setting_family_id`, `method_id`, `candidate_id`
      - `subgroup`, `included_study_ids`, `study_count`, `participant_count`
      - `data_type`, `effect_measure`, `analysis_model`, `statistical_method`, `ci_level`
      - `effect_value`, `ci_lower`, `ci_upper`, `heterogeneity`, `estimation_status`, `source_joined`, `source`
    - `subgroup_difference_tests`: family-level official subgroup-difference tests carried with this setting when subgroup gold exists
      - `subgroup_difference_test_id`, `candidate_id`, `setting_family_id`
      - `comparison`, `outcome`, `timepoint`, `data_type`, `effect_measure`
      - `level_estimate_ids`, `chi2`, `df`, `p_value`, `i2_between_subgroups`, `test_status`
