# Raw Data

本目录存放 benchmark 构建所需的原始数据或冻结数据源，例如下载归档、本地 CSV/XLSX、提取后的 metadata、私有源导出，以及为了重建当前已提交 benchmark dataset 所需的小型 source snapshot。

标准化 benchmark 产物不要放在这里。下面这些文件应放在各模块自己的 dataset 目录中：

```text
benchmark/online_pipeline/<module>/datasets/<dataset_name>/
```

典型标准化产物包括：

- `instances.jsonl`
- `gold.jsonl`
- `split_manifest.json`
- `build_manifest.json`
- `schema.md`

默认 builder 会把下载后的原始数据放到 source 专属子目录，例如：

```text
benchmark/online_pipeline/raw_data/q2crbench3_clinical_questions/
benchmark/online_pipeline/raw_data/csmed_ft/
```

原始源文件通常不提交。builder 也可以通过 `--source-url` 读取本地 raw 文件。如果上游目录没有提交，例如 `sr-cleaned/`，只应把当前 benchmark 可复现所需的最小 source 文件复制到本目录。

## Study PIO

Study PIO 使用以下冻结本地 source：

```text
benchmark/online_pipeline/raw_data/cleaned_sr/
benchmark/online_pipeline/raw_data/cleaned_articles/
benchmark/online_pipeline/raw_data/pmc_xml/
benchmark/online_pipeline/raw_data/indexes/
```

`cleaned_articles/` 是 Study PIO builder 使用的静态 cleaned article snapshot。正常 dataset build 直接读取这些 JSON 文件，不重新清洗 PMC XML。`pmc_xml/` 只作为 provenance 保留，并在刷新冻结 cleaned article snapshot 时作为补充输入。

## Risk of Bias

Risk of Bias 使用模块专属冻结 source snapshot：

```text
benchmark/online_pipeline/raw_data/risk_of_bias/
  source_reviews/
  study_links/
  indexes/
```

其中：

- `source_reviews/` 包含用于重建 gold labels 的 SR characteristics。
- `study_links/` 包含 study-level link metadata。
- article content 复用 `benchmark/online_pipeline/raw_data/cleaned_articles`，不在 `risk_of_bias/` 下重复存放。

RoB builder 会把这些 source layer join 成标准化 benchmark 产物；它不会把预先 join 好的 final dataset 直接当作 benchmark dataset。

## Meta Analysis

当前 Meta Analysis v2 及其 Subtask 2 的 `cochrane_meta_v2-key-filter` 派生集依赖以下冻结数据：

```text
benchmark/online_pipeline/raw_data/meta_analysis/
  source/official_analysis_csv_snapshot/
  intermediate/
```

`official_analysis_csv_snapshot/` 是官方 Cochrane analysis CSV 快照。`intermediate/` 中的
`setting_cleaned.jsonl`、analysis family、study-result rows、overall/subgroup estimates 与 source
reports 是当前 v2 builder 的输入或审计产物；即使部分文件名包含 preview、audit 或 report，也不应因名称而
归档，除非已经确认新的构建链不再读取或复现它们。

## GRADE

当前四个 GRADE domain 的唯一保留版本是 `grade_v4`。其构建依赖：

```text
benchmark/online_pipeline/raw_data/grade/
  source/legacy_grade_benchmark_v2/
  source/legacy_release_splits/
  intermediate/alignment_v3/
  intermediate/meta_analysis_workflow_for_alignment_v3/
  intermediate/setting_cleaning/
benchmark/online_pipeline/raw_data/analysis_settings/grade_required_v1/
```

这里的 `legacy_grade_benchmark_v2` 与 `legacy_release_splits` 是 v4 builder 使用的冻结 source 名称，
不是可删除的旧 benchmark。`alignment_v3` 是当前 `grade_v4` 的正式对齐产物；其内部复用了旧版本命名的
实现函数，但不表示该数据可以归档。

历史 smoke 数据、已停用的 v3 数据构建产物和不再被当前 builder 引用的中间文件应移动到对应模块的
`archive/`。`archive/` 只用于本地审计和复现实验历史，已被 Git 忽略，不能作为普通构建输入或提交内容。
