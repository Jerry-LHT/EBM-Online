# Online EBM Workflow Specification

本文档定义 Online EBM workflow 中各在线模块的任务边界、输入输出、领域对象和模块流向。

当前阶段只处理在线 workflow，不纳入离线索引构建、离线全文清洗、离线数据沉淀等模块。

本文档只描述模块规范，不描述具体实现方法。

## 1. Overall Online Flow

### 1.1 Workflow Goal

Online EBM workflow 从用户输入的临床问题开始，经过问题结构化、在线检索、文献筛选、纳入研究特征抽取、Risk of Bias 判断、Meta Analysis 和 Four-domain GRADE Assessment，最终输出每个 SoF row 对应的四个 GRADE downgrade domain judgements。

当前 workflow 的最终产物是：

```text
SoFRowGRADEAssessment[]
```

每个 `SoFRowGRADEAssessment` 对应一个 selected `AnalysisSetting / evidence body`，并包含四个并行 GRADE domain judgements：

```text
risk_of_bias
inconsistency
indirectness
imprecision
```

本 workflow 只定义在线流程中的模块边界、输入输出和模块间数据流，不描述具体实现方法。

### 1.2 Global Scope and Constraints

当前 workflow 的全局约束如下：

- 只处理 online workflow，不纳入离线索引构建、离线全文清洗、离线数据沉淀等过程。
- 只处理 RCT evidence。
- 当前 workflow 采用 one main RCT = one study 的对象约定，不处理同一研究多报告归并。
- 当前 Meta Analysis 只支持 `Dichotomous` 和 `Continuous` 两类 outcome data。
- 当前 Meta Analysis 主路径仍以 pairwise estimate 为下游目标：一个 experimental arm 对一个 control arm。
- Subtask 2 可记录 multi-arm shared-control 关系，但不在该阶段拆分或合并 arm；这些 items 必须在 effect calculation 前经过 downstream analysis resolution。cluster RCT、crossover RCT、adjusted contrast-level data、time-to-event、rate、ordinal 或 count outcome 暂不处理。
- 当前 Risk of Bias Assessment 固定采用 RoB 1 七域框架；这是本 workflow 的固定方法选择。
- 当前 GRADE 只覆盖四个 downgrade domains：`risk_of_bias`、`inconsistency`、`indirectness`、`imprecision`。
- 当前 Four-domain GRADE Assessment 仅对已形成 meta-analysis effect estimate 的 evidence body 输出 judgement。
- 当前 Search & Article Retrieval 是面向 online workflow 的 question-guided retrieval layer，不等价于完整 systematic review search。
- 当前不处理 `publication_bias`，也不输出 final five-domain overall certainty label。

### 1.3 Core Data Objects

workflow 中的核心数据对象如下：


<table>
  <thead>
    <tr>
      <th>Object</th>
      <th>Produced By</th>
      <th>Consumed By</th>
      <th>Role</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>question_pico</code></td>
      <td>Module 1: Q2PICO</td>
      <td>Modules 2, 3, 4, 6, 7</td>
      <td>当前问题的 question-level PICO；用于检索、study-level PIO 抽取、analysis setting 定义和 indirectness 判断。对 review-level study screening，主要使用其中的 P/I/C 作为问题锚点</td>
    </tr>
    <tr>
      <td><code>CleanedArticle[]</code></td>
      <td>Module 2: Search &amp; Article Retrieval</td>
      <td>Modules 3, 4, 5, 6</td>
      <td>在线检索并清洗后的候选文章正文和表格</td>
    </tr>
    <tr>
      <td><code>screening_criteria</code></td>
      <td>Module 3: Study Screening</td>
      <td>Module 7</td>
      <td>当前问题的纳入/排除标准；作为 indirectness 的辅助上下文</td>
    </tr>
    <tr>
      <td><code>included_studies</code></td>
      <td>Module 3: Study Screening</td>
      <td>Modules 4, 5, 6</td>
      <td>通过筛选进入后续证据分析的 RCT study IDs</td>
    </tr>
    <tr>
      <td><code>StudyPIOCharacteristics[]</code></td>
      <td>Module 4: Study-level PIO Characteristics Extraction</td>
      <td>Modules 6, 7</td>
      <td>纳入研究中与当前问题相关的 study-level population、intervention/comparator 和 outcomes 信息</td>
    </tr>
    <tr>
      <td><code>RiskOfBiasAssessment[]</code></td>
      <td>Module 5: Risk of Bias Assessment</td>
      <td>Module 7</td>
      <td>纳入 RCT studies 的 study-level RoB judgements</td>
    </tr>
    <tr>
      <td><code>MetaAnalysisResultPackage</code></td>
      <td>Module 6: Meta Analysis</td>
      <td>Module 7</td>
      <td>包含 analysis settings、study result rows、overall estimates、subgroup estimates 和 subgroup difference tests</td>
    </tr>
    <tr>
      <td><code>SoFRowGRADEAssessment[]</code></td>
      <td>Module 7: Four-domain GRADE Assessment</td>
      <td>workflow output</td>
      <td>每个 selected SoF row / evidence body 的四个 GRADE domain judgements</td>
    </tr>
  </tbody>
</table>


### 1.4 Module Flow

workflow 包含七个在线模块：

1. `Q2PICO`：将用户自然语言临床问题转换为结构化 `question_pico`。
2. `Search & Article Retrieval`：根据 `question_pico` 生成在线检索式，检索 RCT 文献，并返回 `CleanedArticle[]`。
3. `Study Screening`：根据用户问题、question-level PICO 中与 review eligibility 相关的 P/I/C 信息、全局 RCT 约束和候选文章生成 `screening_criteria`，并确定 `included_studies`。
4. `Study-level PIO Characteristics Extraction`：从 included studies 的清洗文章中抽取与当前问题相关的 study-level PIO characteristics。
5. `Risk of Bias Assessment`：对 included RCT studies 进行固定 RoB 1 domains 的 study-level risk-of-bias 判断。
6. `Meta Analysis`：基于 included studies 定义 `AnalysisSetting`，抽取 study-level result data，并生成 overall/subgroup estimates 和 subgroup difference tests。
7. `Four-domain GRADE Assessment`：以 `AnalysisSetting / evidence body` 为单位，并行生成四个 GRADE downgrade domain judgements。

### 1.5 Overall Workflow Description

整体流程可以理解为从“问题定义”到“证据体确定”再到“GRADE domain judgement”的连续在线过程。

**问题结构化**

1. 用户输入一个自然语言临床问题。
2. `Q2PICO` 将该问题转换为 `question_pico`。
3. `question_pico` 成为后续模块共享的问题锚点，用于约束检索、study-level PIO 抽取、analysis setting 定义和 GRADE indirectness 判断。对 review-level screening，主要使用其中的 P/I/C 信息。

**在线检索与候选文章清洗**

1. `Search & Article Retrieval` 接收 `question_pico`。
2. 该模块生成面向 RCT evidence 的在线检索式。
3. 检索模块返回候选 RCT 文献，并将其整理为 `CleanedArticle[]`。
4. `CleanedArticle[]` 是后续 screening、study-level PIO extraction、RoB assessment 和 Meta Analysis 的共同文章证据来源。

**Study Screening 与纳入研究集合确定**

1. `Study Screening` 接收 `question_pico` 和候选 `CleanedArticle[]`。
2. 该模块先生成 `screening_criteria`，再对候选文章进行 include / exclude 判断。
3. screening 的核心输出是 `included_studies`，即进入后续证据分析的 RCT study IDs。
4. 当前 workflow 中，review-level study screening 不以目标 outcome 是否已报告作为主要纳入标准；研究即使未报告目标 outcome，也可在 screening 阶段纳入，并在后续模块中判断其是否贡献某个 analysis setting。
5. 从这一阶段开始，后续模块原则上只围绕 `included_studies` 展开，不再处理被排除的候选文献。

**Included Study Appraisal**

1. `Study-level PIO Characteristics Extraction` 基于 `question_pico`、`included_studies` 和对应 `CleanedArticle[]`，抽取每个纳入研究中与当前问题相关的 population、intervention/comparator 和 outcomes 信息。
2. 该模块输出 `StudyPIOCharacteristics[]`，用于支持 Meta Analysis 的 setting 识别，也用于 GRADE indirectness 判断。
3. `Risk of Bias Assessment` 基于 `included_studies` 和对应 `CleanedArticle[]`，对每个纳入 RCT study 输出固定 RoB 1 domains 的 study-level judgement。
4. 该模块输出 `RiskOfBiasAssessment[]`，用于 GRADE risk_of_bias domain 判断。

**Evidence Synthesis**

1. `Meta Analysis` 接收 `question_pico`、`included_studies`、对应 `CleanedArticle[]`，并可使用 `StudyPIOCharacteristics[]` 作为辅助上下文。
2. 该模块首先定义可分析的 `AnalysisSetting`，每个 setting 对应一个具体的 population scope、comparison、outcome、timepoint、subgroup 和 data type 组合。
3. 在每个 setting 下，Meta Analysis 抽取 study-level result data，形成 `StudyResultRow[]`。
4. 之后模块决定 analysis method，并在可计算时生成 `OverallEstimate`、`SubgroupEstimate` 和 `SubgroupDifferenceTest`。
5. Module 6 的模块级输出统一打包为 `MetaAnalysisResultPackage`，作为 GRADE 的核心上游输入。

**Four-domain GRADE Assessment**

1. `Four-domain GRADE Assessment` 接收 `question_pico`、可选 `screening_criteria`、`StudyPIOCharacteristics[]`、`RiskOfBiasAssessment[]` 和 `MetaAnalysisResultPackage`。
2. 该模块遍历 `MetaAnalysisResultPackage.analysis_settings`，每个 `AnalysisSetting` 先定义一个内部评估单元，并为当前版本选择一个严格 1:1 对应的 SoF row 输出对象。
3. 对 overall setting，GRADE 使用 matching `OverallEstimate` 的 `included_study_ids` 定义 evidence body。
4. 对 subgroup-level setting，GRADE 使用 matching `SubgroupEstimate` 的 `included_study_ids` 定义 evidence body。
5. 在同一个 evidence body 上，Module 7 并行判断 `risk_of_bias`、`inconsistency`、`indirectness` 和 `imprecision` 四个 domains。
6. 最终 workflow 输出 `SoFRowGRADEAssessment[]`；当前 v1 中一个 SoF row 严格对应一个 selected analysis setting / evidence body，并承载该 evidence body 的四个 GRADE downgrade domain judgements。

### 1.6 Evidence Body Flow

`AnalysisSetting` 是 Meta Analysis 产出的最终分析单元，也是 GRADE Assessment 的内部评估单元。

Module 7 不重新筛选 study，不重新抽取 study result data，不重新计算 meta-analysis，也不重新判断 Risk of Bias。它只消费上游模块已经生成的结构化结果。

Evidence body 的确定规则如下：

1. Module 7 遍历 `MetaAnalysisResultPackage.analysis_settings`。
2. 如果当前 `AnalysisSetting.subgroup.factor` 和 `AnalysisSetting.subgroup.level` 均为空，则该 setting 对应的 effect estimate 来自 matching `OverallEstimate`。
3. 如果当前 `AnalysisSetting.subgroup` 非空，则该 setting 对应的 effect estimate 来自 matching `SubgroupEstimate`。
4. matched estimate 的 `included_study_ids` 定义当前 setting 的 evidence body。
5. Module 7 使用该 `included_study_ids` 过滤 `RiskOfBiasAssessment[]` 和 `StudyPIOCharacteristics[]`。
6. Module 7 对同一个 evidence body 并行生成 `risk_of_bias`、`inconsistency`、`indirectness` 和 `imprecision` 四个 domain judgements。

### 1.7 Workflow Diagram

Online EBM Workflow

## 2. Module 1: Q2PICO

### 2.1 Task Definition

Q2PICO 模块负责将用户输入的自然语言临床问题转换为结构化 PICO 表示。

任务单位：

```text
one clinical question
```

该模块只负责识别临床问题中的 population、intervention、comparator 和 outcome。它不负责检索式生成、文献检索、纳排筛选、analysis setting 推断或 GRADE 判断。

### 2.2 Input

模块输入为用户给出的 clinical question。

```json
{
  "question_text": "In adults with depression, do selective serotonin reuptake inhibitors improve remission compared with placebo?"
}
```

字段说明：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>question_text</code></td>
      <td>string</td>
      <td>yes</td>
      <td>用户输入的自然语言临床问题；该字段是 online workflow 的起点，来源为用户原始问题</td>
    </tr>
  </tbody>
</table>


### 2.3 Output

模块输出为结构化 PICO slots。

```json
{
  "P": ["adults with depression"],
  "I": ["selective serotonin reuptake inhibitors"],
  "C": ["placebo"],
  "O": ["remission"]
}
```

`QuestionPICO` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>P</code></td>
      <td>list[string]</td>
      <td>yes</td>
      <td>Population / participants</td>
    </tr>
    <tr>
      <td><code>I</code></td>
      <td>list[string]</td>
      <td>yes</td>
      <td>Intervention / exposure / index treatment</td>
    </tr>
    <tr>
      <td><code>C</code></td>
      <td>list[string]</td>
      <td>yes</td>
      <td>Comparator / control</td>
    </tr>
    <tr>
      <td><code>O</code></td>
      <td>list[string]</td>
      <td>yes</td>
      <td>Outcome</td>
    </tr>
  </tbody>
</table>


输出约束：

- 四个字段 `P/I/C/O` 必须同时存在。
- 每个字段的值必须是 string list。
- 如果问题中某个 slot 没有明确表达，该字段输出空 list。
- 输出内容应表示问题本身可支持的 PICO 信息，不应包含文献证据、研究结果或下游推断。
- 后续模块统一使用 `question_pico` 指代 Q2PICO 的规范化输出对象；`question_pico` 内部字段即 `P/I/C/O`。


## 3. Module 2: Search & Article Retrieval

### 3.1 Task Definition

Search & Article Retrieval 模块负责根据 Q2PICO 的结构化临床问题生成检索式，并在线检索 RCT 文献，返回清洗后的候选文章。

该模块的目标是为 online workflow 提供 question-guided RCT retrieval。它服务于当前产品工作流中的候选证据发现，不等价于 Cochrane-style comprehensive systematic search。

该模块包含两个任务：

1. `Search Query Generation`
2. `Article Retrieval`

全局约束：当前 workflow 只处理 RCT evidence。因此检索式生成和文章检索都默认面向 RCT 文献，不在本模块中支持 observational studies、case reports、reviews 或 guidelines。

该模块不负责判断文章是否最终纳入，也不负责从文章中抽取 meta-analysis 数据。

### 3.2 Input

模块级输入包括 Q2PICO 输出和检索执行配置。


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Source</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>P</code></td>
      <td>list[string]</td>
      <td>yes</td>
      <td>Q2PICO</td>
      <td>Population / participants</td>
    </tr>
    <tr>
      <td><code>I</code></td>
      <td>list[string]</td>
      <td>yes</td>
      <td>Q2PICO</td>
      <td>Intervention / exposure</td>
    </tr>
    <tr>
      <td><code>C</code></td>
      <td>list[string]</td>
      <td>yes</td>
      <td>Q2PICO</td>
      <td>Comparator / control</td>
    </tr>
    <tr>
      <td><code>O</code></td>
      <td>list[string]</td>
      <td>yes</td>
      <td>Q2PICO</td>
      <td>Outcome</td>
    </tr>
    <tr>
      <td><code>database</code></td>
      <td>list[string]</td>
      <td>yes</td>
      <td>workflow config</td>
      <td>检索数据库，例如 PubMed / PMC</td>
    </tr>
    <tr>
      <td><code>filters</code></td>
      <td>SearchFilters</td>
      <td>yes</td>
      <td>workflow config</td>
      <td>RCT-only、全文可得性、语言、发表时间等检索约束</td>
    </tr>
    <tr>
      <td><code>max_results</code></td>
      <td>integer</td>
      <td>yes</td>
      <td>workflow config</td>
      <td>最大返回文章数量</td>
    </tr>
  </tbody>
</table>

`SearchFilters` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>study_design</code></td>
      <td>string?</td>
      <td>no</td>
      <td>检索设计过滤，例如 <code>RCT</code></td>
    </tr>
    <tr>
      <td><code>full_text_required</code></td>
      <td>boolean?</td>
      <td>no</td>
      <td>是否要求全文可得</td>
    </tr>
    <tr>
      <td><code>language</code></td>
      <td>list[string]?</td>
      <td>no</td>
      <td>语言过滤条件</td>
    </tr>
    <tr>
      <td><code>publication_year_range</code></td>
      <td>string?</td>
      <td>no</td>
      <td>发表时间过滤条件</td>
    </tr>
  </tbody>
</table>


### 3.3 Output

模块级输出包括检索式、检索执行信息和清洗后的候选文章。


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>search_query</code></td>
      <td>string</td>
      <td>生成的检索式</td>
    </tr>
    <tr>
      <td><code>query_used</code></td>
      <td>string</td>
      <td>实际执行的检索式</td>
    </tr>
    <tr>
      <td><code>database</code></td>
      <td>string</td>
      <td>实际检索数据库</td>
    </tr>
    <tr>
      <td><code>total_hits</code></td>
      <td>integer</td>
      <td>检索命中数量</td>
    </tr>
    <tr>
      <td><code>returned_count</code></td>
      <td>integer</td>
      <td>返回数量</td>
    </tr>
    <tr>
      <td><code>articles</code></td>
      <td>list[CleanedArticle]</td>
      <td>清洗后的候选文章</td>
    </tr>
  </tbody>
</table>


### 3.4 Task 1: Search Query Generation

Search Query Generation 负责根据 Q2PICO 输出生成可执行的检索式。

输入：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Source</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>P</code></td>
      <td>list[string]</td>
      <td>yes</td>
      <td>Q2PICO</td>
      <td>Population / participants</td>
    </tr>
    <tr>
      <td><code>I</code></td>
      <td>list[string]</td>
      <td>yes</td>
      <td>Q2PICO</td>
      <td>Intervention / exposure</td>
    </tr>
    <tr>
      <td><code>C</code></td>
      <td>list[string]</td>
      <td>yes</td>
      <td>Q2PICO</td>
      <td>Comparator / control</td>
    </tr>
    <tr>
      <td><code>O</code></td>
      <td>list[string]</td>
      <td>yes</td>
      <td>Q2PICO</td>
      <td>Outcome</td>
    </tr>
  </tbody>
</table>


输出：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>search_query</code></td>
      <td>string</td>
      <td>面向 RCT 文献检索的可执行检索式</td>
    </tr>
  </tbody>
</table>


说明：

- `P/I/C` 是检索式生成的主要语义输入。
- `O` 可作为检索辅助语义输入，但当前模块不承诺其等价于系统综述级高敏感度检索策略。
- 当前 workflow 约束为 RCT-only，因此不需要把 `S` 作为模块输入字段。
- 本任务只生成检索式，不决定检索数据库、检索条数或过滤参数。
- 当前任务目标是生成可执行、可服务下游 workflow 的 online retrieval query，而不是复现完整 systematic review search strategy。

### 3.5 Task 2: Article Retrieval

Article Retrieval 负责执行检索式，返回清洗后的候选文章。

输入：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Source</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>search_query</code></td>
      <td>string</td>
      <td>Search Query Generation</td>
      <td>实际执行的检索式</td>
    </tr>
    <tr>
      <td><code>database</code></td>
      <td>list[string]</td>
      <td>workflow config</td>
      <td>检索数据库，例如 PubMed / PMC</td>
    </tr>
    <tr>
      <td><code>filters</code></td>
      <td>SearchFilters</td>
      <td>workflow config</td>
      <td>RCT-only、全文可得性、语言、发表时间等检索约束</td>
    </tr>
    <tr>
      <td><code>max_results</code></td>
      <td>integer</td>
      <td>workflow config</td>
      <td>最大返回文章数量</td>
    </tr>
  </tbody>
</table>


输出：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>query_used</code></td>
      <td>string</td>
      <td>实际执行的检索式</td>
    </tr>
    <tr>
      <td><code>database</code></td>
      <td>string</td>
      <td>实际检索数据库</td>
    </tr>
    <tr>
      <td><code>total_hits</code></td>
      <td>integer</td>
      <td>检索命中数量</td>
    </tr>
    <tr>
      <td><code>returned_count</code></td>
      <td>integer</td>
      <td>返回数量</td>
    </tr>
    <tr>
      <td><code>articles</code></td>
      <td>list[CleanedArticle]</td>
      <td>清洗后的候选文章</td>
    </tr>
  </tbody>
</table>


### 3.6 CleanedArticle

`CleanedArticle` 表示已经完成基础清洗、可供后续 screening 和 evidence extraction 使用的文章对象。

在当前 workflow 中，study 是后续 screening、RoB、meta-analysis 和 GRADE 的基本对象单位。当前系统采用 one main RCT = one study 的简化约定；每个 `CleanedArticle` 对应一个主要 RCT study，并由 `study_id` 标识。当前版本不处理同一研究多报告归并，由此带来的重复计数风险和信息缺失风险属于已知系统边界。


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>study_id</code></td>
      <td>string</td>
      <td>系统内 study ID；当前约定为一个主要 RCT 对应一个 <code>study_id</code></td>
    </tr>
    <tr>
      <td><code>metadata</code></td>
      <td>ArticleMetadata</td>
      <td>文章元数据</td>
    </tr>
    <tr>
      <td><code>xml_content</code></td>
      <td>ArticleXmlContent</td>
      <td>清洗后的正文内容</td>
    </tr>
    <tr>
      <td><code>tables</code></td>
      <td>list[Table]</td>
      <td>清洗后的表格</td>
    </tr>
    <tr>
      <td><code>source</code></td>
      <td>ArticleSource</td>
      <td>检索来源信息</td>
    </tr>
  </tbody>
</table>


`ArticleMetadata` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>pmid</code></td>
      <td>string?</td>
      <td>PubMed ID</td>
    </tr>
    <tr>
      <td><code>pmc_id</code></td>
      <td>string?</td>
      <td>PMC ID</td>
    </tr>
    <tr>
      <td><code>title</code></td>
      <td>string</td>
      <td>文章标题</td>
    </tr>
    <tr>
      <td><code>source_type</code></td>
      <td>string?</td>
      <td>来源类型，例如 PubMed/PMC</td>
    </tr>
    <tr>
      <td><code>publication_year</code></td>
      <td>string?</td>
      <td>发表年份</td>
    </tr>
    <tr>
      <td><code>mesh_terms</code></td>
      <td>list[string]</td>
      <td>MeSH terms</td>
    </tr>
    <tr>
      <td><code>doi</code></td>
      <td>string?</td>
      <td>DOI；在线检索源提供时填写</td>
    </tr>
  </tbody>
</table>


`ArticleXmlContent` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>sections</code></td>
      <td>list[Section]</td>
      <td>清洗后的正文分节</td>
    </tr>
  </tbody>
</table>


`ArticleSource` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>database</code></td>
      <td>string</td>
      <td>检索数据库</td>
    </tr>
    <tr>
      <td><code>retrieval_rank</code></td>
      <td>integer?</td>
      <td>检索排序</td>
    </tr>
    <tr>
      <td><code>retrieval_score</code></td>
      <td>number?</td>
      <td>检索分数，如果检索源提供</td>
    </tr>
    <tr>
      <td><code>raw_source_url</code></td>
      <td>string?</td>
      <td>原始在线链接</td>
    </tr>
    <tr>
      <td><code>raw_record_id</code></td>
      <td>string?</td>
      <td>检索源原始记录 ID</td>
    </tr>
  </tbody>
</table>


`Section` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>section</code></td>
      <td>string</td>
      <td>分节名称，例如 Abstract、Methods、Results</td>
    </tr>
    <tr>
      <td><code>text</code></td>
      <td>string</td>
      <td>该分节的清洗文本</td>
    </tr>
  </tbody>
</table>


`Table` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>section_path</code></td>
      <td>list[string]</td>
      <td>表格所在章节路径</td>
    </tr>
    <tr>
      <td><code>raw_xml</code></td>
      <td>string</td>
      <td>原始表格 XML 或结构化表格文本</td>
    </tr>
  </tbody>
</table>


字段约束：

- `xml_content` 必须存在。
- `xml_content.sections` 至少应包含 abstract 或正文片段之一。
- `tables` 可以为空 list。
- 不在 `CleanedArticle` 中写入 screening decision、study characteristics、RoB 或 meta-analysis extraction result。


## 4. Module 3: Study Screening

### 4.1 Task Definition

Study Screening 模块负责先生成轻量的 review-level eligibility criteria artifact，再判断检索返回的候选文章是否应纳入后续证据分析。

当前 workflow 中，Study Screening 的 review-level eligibility 主要基于用户问题、question-level PICO 中的 P/I/C 信息以及 study design 约束，不以目标 outcome 是否已报告作为主要纳入标准。

这里的 `screening_criteria` 不是完整 protocol，也不承载 meta-analysis synthesis plan。它只表达用于 study screening 的纳入/排除边界，可以是简明文本、列表或等价的结构化对象。

该模块包含两个子任务：

1. `Screening Criteria Generation`
2. `Article Screening`

该模块只做 study-level include / exclude 判断，不负责生成 analysis setting，不抽取 meta-analysis 数据，不做 risk of bias 或 GRADE。

当前 workflow 只处理 RCT evidence，因此非 RCT、review、guideline、case report 等应被排除。

### 4.2 Input

模块级输入包括用户问题、Q2PICO 输出、全局约束和待筛选候选文章。


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Source</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>question_text</code></td>
      <td>string</td>
      <td>yes</td>
      <td>Q2PICO input</td>
      <td>用户原始临床问题</td>
    </tr>
    <tr>
      <td><code>question_pico</code></td>
      <td>QuestionPICO</td>
      <td>yes</td>
      <td>Q2PICO</td>
      <td>结构化 PICO；内部字段为 <code>P/I/C/O</code></td>
    </tr>
    <tr>
      <td><code>global_constraints</code></td>
      <td>WorkflowConstraints</td>
      <td>yes</td>
      <td>workflow config</td>
      <td>全局约束，例如 <code>study_design = RCT</code></td>
    </tr>
    <tr>
      <td><code>articles</code></td>
      <td>list[CleanedArticle]</td>
      <td>yes</td>
      <td>Search &amp; Article Retrieval</td>
      <td>清洗后的候选文章</td>
    </tr>
  </tbody>
</table>

`WorkflowConstraints` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>study_design</code></td>
      <td>string</td>
      <td>yes</td>
      <td>当前 workflow 固定为 <code>RCT</code></td>
    </tr>
    <tr>
      <td><code>evidence_scope</code></td>
      <td>string?</td>
      <td>no</td>
      <td>额外 workflow-level 证据范围约束</td>
    </tr>
    <tr>
      <td><code>publication_year_range</code></td>
      <td>string?</td>
      <td>no</td>
      <td>可选发表年份范围约束，例如 <code>2000-2024</code>；若提供，应进入 screening criteria</td>
    </tr>
  </tbody>
</table>


### 4.3 Output

模块级输出包括筛选标准、每篇候选文章的筛选判断，以及供下游模块直接消费的已纳入 study ID 列表。


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>screening_criteria</code></td>
      <td>ScreeningCriteria</td>
      <td>生成的纳入/排除标准</td>
    </tr>
    <tr>
      <td><code>decisions</code></td>
      <td>list[ScreeningDecision]</td>
      <td>每篇候选文章的筛选判断</td>
    </tr>
    <tr>
      <td><code>included_studies</code></td>
      <td>list[string]</td>
      <td>由 <code>decisions</code> 中 <code>decision = include</code> 的 <code>study_id</code> 组成；作为 Module 4/5/6 的 included study ID 输入</td>
    </tr>
  </tbody>
</table>


### 4.4 Task 1: Screening Criteria Generation

Screening Criteria Generation 负责根据用户问题、Q2PICO 输出和全局约束生成可执行的纳入/排除标准 artifact。

生成 `screening_criteria` 时，应优先表达与 population、intervention/comparator、study design、发表年份范围和合格报告类型相关的纳入/排除标准；outcome 默认不作为排除研究的条件，仅在存在明确 review-level outcome restriction 时作为辅助上下文使用。

实现可以把 criteria 表达为一个对象或一段文本；只要 Article Screening 可以消费，并能在下游作为 eligibility context 被引用即可。

输入：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Source</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>question_text</code></td>
      <td>string</td>
      <td>yes</td>
      <td>Q2PICO input</td>
      <td>用户原始临床问题</td>
    </tr>
    <tr>
      <td><code>question_pico</code></td>
      <td>QuestionPICO</td>
      <td>yes</td>
      <td>Q2PICO</td>
      <td>结构化 PICO；内部字段为 <code>P/I/C/O</code></td>
    </tr>
    <tr>
      <td><code>global_constraints</code></td>
      <td>WorkflowConstraints</td>
      <td>yes</td>
      <td>workflow config</td>
      <td>全局约束，例如 <code>study_design = RCT</code></td>
    </tr>
  </tbody>
</table>


输出：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>screening_criteria</code></td>
      <td>ScreeningCriteria</td>
      <td>生成的纳入/排除标准</td>
    </tr>
  </tbody>
</table>


`ScreeningCriteria` schema:

`ScreeningCriteria` 是轻量 eligibility artifact。实现上可以采用文本、列表或结构化对象；当前 backend 使用以下兼容对象表示。


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>inclusion</code></td>
      <td>list[string]</td>
      <td>纳入标准</td>
    </tr>
    <tr>
      <td><code>exclusion</code></td>
      <td>list[string]</td>
      <td>排除标准</td>
    </tr>
    <tr>
      <td><code>rationale</code></td>
      <td>string?</td>
      <td>criteria 来源或生成原则说明</td>
    </tr>
  </tbody>
</table>


### 4.5 Task 2: Article Screening

Article Screening 负责基于 `screening_criteria` 判断候选文章是否纳入。

输入：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Source</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>question_text</code></td>
      <td>string</td>
      <td>Q2PICO input</td>
      <td>用户原始临床问题</td>
    </tr>
    <tr>
      <td><code>screening_criteria</code></td>
      <td>ScreeningCriteria</td>
      <td>Screening Criteria Generation</td>
      <td>纳入和排除标准</td>
    </tr>
    <tr>
      <td><code>articles</code></td>
      <td>list[CleanedArticle]</td>
      <td>Search &amp; Article Retrieval</td>
      <td>清洗后的候选文章</td>
    </tr>
  </tbody>
</table>


输出：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>decisions</code></td>
      <td>list[ScreeningDecision]</td>
      <td>每篇候选文章的筛选判断</td>
    </tr>
    <tr>
      <td><code>included_studies</code></td>
      <td>list[string]</td>
      <td>由 <code>decisions</code> 中 <code>decision = include</code> 的 <code>study_id</code> 组成</td>
    </tr>
  </tbody>
</table>


`ScreeningDecision` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>study_id</code></td>
      <td>string</td>
      <td>对应 <code>CleanedArticle.study_id</code></td>
    </tr>
    <tr>
      <td><code>title</code></td>
      <td>string</td>
      <td>文章标题</td>
    </tr>
    <tr>
      <td><code>decision</code></td>
      <td>string</td>
      <td><code>include</code> / <code>exclude</code></td>
    </tr>
    <tr>
      <td><code>rationale</code></td>
      <td>string</td>
      <td>判断依据</td>
    </tr>
    <tr>
      <td><code>exclusion_reason</code></td>
      <td>string?</td>
      <td>排除原因；纳入时为空</td>
    </tr>
    <tr>
      <td><code>failed_criterion</code></td>
      <td>string?</td>
      <td>导致排除的主要标准</td>
    </tr>
    <tr>
      <td><code>evidence_spans</code></td>
      <td>list[string]</td>
      <td>支持判断的原文证据片段</td>
    </tr>
    <tr>
      <td><code>confidence</code></td>
      <td>string?</td>
      <td><code>low</code> / <code>medium</code> / <code>high</code></td>
    </tr>
  </tbody>
</table>


输出约束：

- `included_studies` 是 `decisions` 的 workflow projection，不是独立判断结果。
- `included_studies[*]` 必须能连接到 `CleanedArticle.study_id`。
- 不得仅因候选研究未报告目标 outcome 而直接排除该研究；该研究是否贡献某个 analysis setting，由后续模块判断。


## 5. Module 4: Study-level PIO Characteristics Extraction

### 5.1 Task Definition

Study-level PIO Characteristics Extraction 模块负责从已纳入研究的清洗文章内容中抽取与当前 question-level PICO 相关的 study-level population、intervention/comparator 和 outcomes 信息。

任务单位：

```text
one included study
```

该模块只描述单篇 included study 实际研究、且与当前问题相关的人群、干预/对照组和结局。

当前 workflow 只处理 RCT evidence，因此该模块默认输入为 Study Screening 后判定为 `include` 的 RCT study。

### 5.2 Input

输入为当前问题的 PICO、一篇已纳入研究及其清洗文章内容。


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Source</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>study_id</code></td>
      <td>string</td>
      <td>Study Screening</td>
      <td>已纳入 study 的唯一 ID</td>
    </tr>
    <tr>
      <td><code>question_pico</code></td>
      <td>QuestionPICO</td>
      <td>Q2PICO</td>
      <td>当前问题的 question-level PICO，用于限定 study-level PIO characteristics 的抽取范围</td>
    </tr>
    <tr>
      <td><code>article</code></td>
      <td>CleanedArticle</td>
      <td>Search &amp; Article Retrieval</td>
      <td>该 study 对应的清洗文章内容</td>
    </tr>
  </tbody>
</table>


### 5.3 Output

输出为与当前问题相关的 study-level PIO characteristics。每条输出记录为一个 `StudyPIOCharacteristics`。

`StudyPIOCharacteristics` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>study_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>对应 included study</td>
    </tr>
    <tr>
      <td><code>population</code></td>
      <td>string</td>
      <td>yes</td>
      <td>study 实际纳入且与当前问题相关的人群、疾病状态、年龄、样本量、关键 eligibility</td>
    </tr>
    <tr>
      <td><code>intervention_comparator</code></td>
      <td>string</td>
      <td>yes</td>
      <td>study 中与当前问题相关的干预组、对照组、比较组的合并描述；不强拆独立 comparator 字段</td>
    </tr>
    <tr>
      <td><code>outcomes</code></td>
      <td>string</td>
      <td>yes</td>
      <td>study 中与当前问题相关的结局、时间点、测量方式</td>
    </tr>
  </tbody>
</table>


输出约束：

- `population / intervention_comparator / outcomes` 必须同时存在。
- 如果某个字段在文章中没有足够信息，应输出空字符串。
- `question_pico` 只用于限定抽取范围，不用于补全文章中没有的信息。
- `intervention_comparator` 应保留 intervention、control、placebo、usual care、no treatment 等 study arm 信息。
- 输出应优先覆盖与 `question_pico` 相关的 study population、intervention/comparator arms 和 outcomes。
- 与当前问题无关的背景性内容不应作为主要输出。


## 6. Module 5: Risk of Bias Assessment

### 6.1 Task Definition

Risk of Bias Assessment 模块负责对已纳入 RCT study 进行基于 RoB 1 七域框架的 study-level domain 判断。

任务单位：

```text
one included RCT study
```

当前模块固定采用 RoB 1 作为风险偏倚评估框架；这是本 workflow 的方法选择。对每个 domain 输出风险判断和支持文本。

### 6.2 Fixed RoB Domains

当前 workflow 只处理 RCT，且 Risk of Bias Assessment 固定采用 RoB 1 七域框架，因此本模块输出固定的 RoB 1 七域 judgement。


<table>
  <thead>
    <tr>
      <th>Domain ID</th>
      <th>Domain</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>random_sequence_generation</code></td>
      <td>Random sequence generation (selection bias)</td>
    </tr>
    <tr>
      <td><code>allocation_concealment</code></td>
      <td>Allocation concealment (selection bias)</td>
    </tr>
    <tr>
      <td><code>blinding_participants_personnel</code></td>
      <td>Blinding of participants and personnel (performance bias)</td>
    </tr>
    <tr>
      <td><code>blinding_outcome_assessment</code></td>
      <td>Blinding of outcome assessment (detection bias)</td>
    </tr>
    <tr>
      <td><code>incomplete_outcome_data</code></td>
      <td>Incomplete outcome data (attrition bias)</td>
    </tr>
    <tr>
      <td><code>selective_reporting</code></td>
      <td>Selective reporting (reporting bias)</td>
    </tr>
    <tr>
      <td><code>other_bias</code></td>
      <td>Other bias</td>
    </tr>
  </tbody>
</table>


judgement label set 固定为：

```text
low_risk / unclear_risk / high_risk
```

### 6.3 Input

输入为一篇已纳入 RCT study 及其可用于 RoB 判断的清洗文章内容。


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Source</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>study_id</code></td>
      <td>string</td>
      <td>Study Screening</td>
      <td>已纳入 RCT study 的唯一 ID</td>
    </tr>
    <tr>
      <td><code>article</code></td>
      <td>CleanedArticle</td>
      <td>Search &amp; Article Retrieval</td>
      <td>该 study 的清洗文章内容，包括 methods、results、tables 等可用于 RoB 判断的信息</td>
    </tr>
  </tbody>
</table>


说明：

- RoB domains 是模块固定配置，不作为输入字段传入。
- 输入中不得包含下游标注、参考答案或已知 RoB judgement 字段。
- study-level PIO characteristics 不作为本模块输入。
- RoB judgement 应基于 study report 中与随机化、分配隐藏、盲法、失访、选择性报告等相关的方法学和报告证据。

### 6.4 Output

输出为固定 RoB 1 domains 上的 study-level 判断。


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>study_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>对应 included RCT study</td>
    </tr>
    <tr>
      <td><code>risk_of_bias</code></td>
      <td>list[RiskOfBiasJudgement]</td>
      <td>yes</td>
      <td>每个 RoB domain 的判断</td>
    </tr>
  </tbody>
</table>


`RiskOfBiasJudgement` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>domain_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>固定 RoB 1 domain ID</td>
    </tr>
    <tr>
      <td><code>domain</code></td>
      <td>string</td>
      <td>yes</td>
      <td>RoB 1 domain 名称</td>
    </tr>
    <tr>
      <td><code>judgement</code></td>
      <td>string</td>
      <td>yes</td>
      <td><code>low_risk</code> / <code>unclear_risk</code> / <code>high_risk</code></td>
    </tr>
    <tr>
      <td><code>support_text</code></td>
      <td>string</td>
      <td>yes</td>
      <td>支持该判断的证据文本</td>
    </tr>
  </tbody>
</table>


输出约束：

- 每篇 study 应输出固定 7 个 RoB domains。
- `domain_id` 必须来自固定 RoB 1 domain set。
- `judgement` 必须来自固定 judgement label set。
- `support_text` 应给出可追溯的支持文本；如果依据不足，可为空字符串，但 judgement 仍需输出。


## 7. Module 6: Meta Analysis

### 7.1 Task Definition

Meta Analysis 模块负责在已纳入 RCT studies 的基础上，完成 evidence synthesis 所需的 analysis setting 定义、study-level result data extraction、analysis model decision、subgroup analysis 和 overall estimate calculation。

任务单位：

```text
one online EBM question / one review-level meta-analysis result package
```

该模块对应真实系统综述中的 synthesis preparation 和 meta-analysis 阶段。它先判断哪些 intervention/comparator、outcome、timepoint、subgroup 和 study 集合可以被组织成可分析的 synthesis unit，再从每篇 study 中抽取二分类或连续型 result data，并在可合并时生成 subgroup estimates、overall estimates 和 subgroup difference tests。

该模块包含五个子任务：

1. `Analysis Setting Definition`
2. `Study-level Result Data Extraction`
3. `Analysis Model Decision`
4. `Subgroup Analysis`
5. `Overall Estimate Calculation`

当前 workflow 在本模块只支持两类数据：

```text
Dichotomous
Continuous
```

当前 workflow 在本模块的下游 estimate 目标仍是 pairwise meta-analysis：一个 experimental arm 对一个 control arm，且 study-level result data 可以抽取为 arm-level numeric data。Subtask 2 可记录 multi-arm shared-control 关系，但只保留原始 arm-level result items 和 resolution metadata，不在抽取阶段拆分 shared arm。cluster RCT、crossover RCT、adjusted contrast-level data、time-to-event、rate、ordinal 和 count outcome 暂不在本模块处理。

该模块不重新生成 PICO，不重新筛选 study，不重新判断 Risk of Bias，不做 GRADE certainty assessment。`CandidateSynthesisDimension` 是 Analysis Setting Definition 内部候选层，不进入模块级输出；`AnalysisSetting` 是后续 extraction、estimate calculation 和 GRADE 的最终分析单元。

Benchmark 构建中，`AnalysisSetting` cleaning 是 Meta Analysis 的上游 source-of-truth。Comparison cleaning cache 必须覆盖实际用于 comparison extraction 的完整 candidate 输入，包括 `candidate_id`、`review_id`、`analysis_group`、`analysis_number`、`analysis_name`、`analysis_group_name` 和 `explicit_labels`；旧 cache 或无法校验 source hash 的 setting 不得进入后续 subtask 构建。当前可复现 Meta Analysis benchmark 版本为 `cochrane_meta_v2`，其主构建只接受 `setting_cleaning_v2` / `comparison_v2` 且 source hash 可校验的 setting。

GRADE 可复用 Meta Analysis workflow 的已校验 setting 和 row universe，但 GRADE/shared artifact 不应反向作为 Meta Analysis 主构建的默认来源。Benchmark 实现中，GRADE 对 Meta Analysis workflow 的复用必须写入 GRADE 私有中间目录，例如 `raw_data/grade/intermediate/meta_analysis_workflow_for_<alignment_name>/`；不得把 GRADE 所需的 shared settings 写回 `raw_data/meta_analysis/intermediate/`，否则会污染 Meta Analysis 主数据集。

### 7.2 Input

输入为当前问题、question-level PICO、已纳入研究 ID 和对应清洗文章；`screening_criteria` 和 study-level PIO characteristics 可作为辅助上下文，但不是本模块的必需输入。


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Source</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>review_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>workflow</td>
      <td>当前 online review/question ID；用于连接 Module 6 输出和下游 GRADE</td>
    </tr>
    <tr>
      <td><code>question_text</code></td>
      <td>string</td>
      <td>yes</td>
      <td>Q2PICO input</td>
      <td>用户原始临床问题</td>
    </tr>
    <tr>
      <td><code>question_pico</code></td>
      <td>QuestionPICO</td>
      <td>yes</td>
      <td>Q2PICO</td>
      <td>当前问题的 question-level PICO</td>
    </tr>
    <tr>
      <td><code>included_studies</code></td>
      <td>list[string]</td>
      <td>yes</td>
      <td>Study Screening / workflow projection</td>
      <td>已纳入 RCT studies 的 <code>study_id</code> 列表；由 <code>ScreeningDecision.decision = include</code> 的 records 投影得到</td>
    </tr>
    <tr>
      <td><code>screening_criteria</code></td>
      <td>ScreeningCriteria?</td>
      <td>no</td>
      <td>Study Screening</td>
      <td>可选 eligibility context；用于理解 review-level 纳入/排除边界，不替代 analysis setting finalization</td>
    </tr>
    <tr>
      <td><code>study_characteristics</code></td>
      <td>list[StudyPIOCharacteristics]?</td>
      <td>no</td>
      <td>Study-level PIO Characteristics Extraction</td>
      <td>可选辅助上下文；用于帮助识别 candidate comparison、outcome、timepoint 和 eligible studies，不作为 result data extraction 或 estimate calculation 的硬依赖</td>
    </tr>
    <tr>
      <td><code>articles</code></td>
      <td>list[CleanedArticle]</td>
      <td>yes</td>
      <td>Search &amp; Article Retrieval</td>
      <td>按 <code>included_studies</code> 过滤后的清洗正文和表格，用于判断 outcome measure、timepoint、数据类型和可综合性</td>
    </tr>
  </tbody>
</table>


### 7.3 Output

模块级输出为 `MetaAnalysisResultPackage`。


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>review_id</code></td>
      <td>string</td>
      <td>当前 online review/question ID</td>
    </tr>
    <tr>
      <td><code>analysis_settings</code></td>
      <td>list[AnalysisSetting]</td>
      <td>review-level synthesis units</td>
    </tr>
    <tr>
      <td><code>study_result_rows</code></td>
      <td>list[StudyResultRow]</td>
      <td>study-level result data；也是下游 GRADE 的 contributing study evidence 输入</td>
    </tr>
    <tr>
      <td><code>subgroup_estimates</code></td>
      <td>list[SubgroupEstimate]</td>
      <td>subgroup-level effect estimates</td>
    </tr>
    <tr>
      <td><code>overall_estimates</code></td>
      <td>list[OverallEstimate]</td>
      <td>overall effect estimates</td>
    </tr>
    <tr>
      <td><code>subgroup_difference_tests</code></td>
      <td>list[SubgroupDifferenceTest]</td>
      <td>同一 subgroup factor 下不同 subgroup estimates 的差异检验</td>
    </tr>
  </tbody>
</table>


### 7.4 Subtask 1: Analysis Setting Definition

Analysis Setting Definition 负责从当前 review/question 的 PICO、included studies 和 cleaned articles 中，定义可用于 meta-analysis 的 final synthesis units；如提供 study-level PIO characteristics，可作为辅助上下文使用。

该子任务覆盖两个概念阶段：一是 protocol-like synthesis planning，即判断当前问题下哪些 comparison、outcome、timepoint、subgroup 和 data type 值得作为候选综合维度；二是 review execution finalization，即根据已纳入研究和可用证据把候选维度落成实际可执行的 `AnalysisSetting[]`。在当前 workflow 和 benchmark 中，这两个阶段不作为两个独立模块暴露，模块边界只要求输入上游 context，输出最终 `analysis_settings`。

该子任务包含两个内部步骤：

1. `Candidate Synthesis Dimension Generation`
2. `Analysis Setting Finalization`

`CandidateSynthesisDimension` 是内部候选层，用于记录某个 population/comparison/outcome 下可能的 outcome measures、timepoints、subgroups 和 data types；它不进入模块级输出，也不直接传给下游 GRADE。

`CandidateSynthesisDimension` 不属于外部 API 或 benchmark gold 的必填输出；方法可以显式生成，也可以只作为内部推理过程存在。

`AnalysisSetting` 是最终分析单元，进入模块级输出，并作为 Study-level Result Data Extraction、Analysis Model Decision、Estimate Calculation 和 GRADE 的 join unit。`AnalysisMethod` 是内部中间产物，不进入本子任务输出；必要的 method provenance 写入后续对应的 effect estimate。

#### 7.4.1 Candidate Synthesis Dimension Generation

候选层任务单位：

```text
one population_scope x one comparison x one outcome_concept
```

`CandidateSynthesisDimension` unique key:

```text
population_scope x comparison x outcome_concept
```

输入字段：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Source</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>question_text</code></td>
      <td>string</td>
      <td>Module 1: Q2PICO / workflow</td>
      <td>当前临床问题</td>
    </tr>
    <tr>
      <td><code>question_pico</code></td>
      <td>QuestionPICO</td>
      <td>Module 1: Q2PICO</td>
      <td>question-level PICO，用于约束 candidate 的 population、comparison 和 outcome scope</td>
    </tr>
    <tr>
      <td><code>included_studies</code></td>
      <td>list[string]</td>
      <td>Module 3: Study Screening / workflow projection</td>
      <td>由 <code>ScreeningDecision.decision = include</code> 的 records 投影得到的 <code>study_id</code> 列表</td>
    </tr>
    <tr>
      <td><code>articles</code></td>
      <td>list[CleanedArticle]</td>
      <td>Module 2: Search &amp; Article Retrieval</td>
      <td>按 <code>included_studies</code> 过滤后的清洗正文和表格，是识别 outcome measure、timepoint、subgroup 和 data type 的主要证据源</td>
    </tr>
    <tr>
      <td><code>study_characteristics</code></td>
      <td>list[StudyPIOCharacteristics]?</td>
      <td>Module 4: Study-level PIO Characteristics Extraction</td>
      <td>可选辅助上下文；不作为生成 candidate 的硬依赖</td>
    </tr>
  </tbody>
</table>


输出字段：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>candidate_synthesis_dimensions</code></td>
      <td>list[CandidateSynthesisDimension]</td>
      <td>内部候选 synthesis dimensions；不进入 <code>MetaAnalysisResultPackage</code></td>
    </tr>
  </tbody>
</table>


`CandidateSynthesisDimension` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>candidate_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>当前 review 内稳定候选 ID</td>
    </tr>
    <tr>
      <td><code>population_scope</code></td>
      <td>string</td>
      <td>yes</td>
      <td>候选 synthesis dimension 覆盖的人群范围；即使所有 candidates 相同也需要显式填写</td>
    </tr>
    <tr>
      <td><code>comparison</code></td>
      <td>AnalysisComparison</td>
      <td>yes</td>
      <td>候选 comparison，包含 experimental intervention 和 comparator</td>
    </tr>
    <tr>
      <td><code>outcome_concept</code></td>
      <td>string</td>
      <td>yes</td>
      <td>review-level outcome domain/concept</td>
    </tr>
    <tr>
      <td><code>outcome_measure_candidates</code></td>
      <td>list[string]</td>
      <td>no</td>
      <td>该 outcome concept 下可接受或已观察到的量表、定义或测量方式候选</td>
    </tr>
    <tr>
      <td><code>timepoint_candidates</code></td>
      <td>list[TimepointCandidate]</td>
      <td>no</td>
      <td>该 comparison/outcome 下可能的 timepoint 或 follow-up window；允许多个</td>
    </tr>
    <tr>
      <td><code>subgroup_candidates</code></td>
      <td>list[SubgroupCandidate]</td>
      <td>no</td>
      <td>该 comparison/outcome 下可能的 subgroup factors 和 levels；允许多个</td>
    </tr>
    <tr>
      <td><code>data_type_candidates</code></td>
      <td>list[string]</td>
      <td>no</td>
      <td>可能的数据类型；当前只允许 <code>Dichotomous</code> / <code>Continuous</code></td>
    </tr>
    <tr>
      <td><code>eligible_study_candidates</code></td>
      <td>list[string]</td>
      <td>no</td>
      <td>可能进入该 candidate 的 included study IDs</td>
    </tr>
  </tbody>
</table>


`TimepointCandidate` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>label</code></td>
      <td>string</td>
      <td>yes</td>
      <td>原始或规范化后的 timepoint label</td>
    </tr>
    <tr>
      <td><code>window</code></td>
      <td>string?</td>
      <td>no</td>
      <td>可接受时间窗，例如 0-3 months</td>
    </tr>
    <tr>
      <td><code>source</code></td>
      <td>string?</td>
      <td>no</td>
      <td>候选来源，例如 question, study characteristics, result table, article text</td>
    </tr>
    <tr>
      <td><code>selection_status</code></td>
      <td>string?</td>
      <td>no</td>
      <td><code>selected</code> / <code>not_selected</code> / <code>uncertain</code></td>
    </tr>
  </tbody>
</table>


`SubgroupCandidate` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>factor</code></td>
      <td>string</td>
      <td>yes</td>
      <td>subgroup 因子，例如 age group、baseline severity</td>
    </tr>
    <tr>
      <td><code>levels</code></td>
      <td>list[string]</td>
      <td>yes</td>
      <td>该 subgroup factor 下的 levels</td>
    </tr>
    <tr>
      <td><code>rationale</code></td>
      <td>string?</td>
      <td>no</td>
      <td>该 subgroup 候选的临床或方法学理由</td>
    </tr>
    <tr>
      <td><code>source</code></td>
      <td>string?</td>
      <td>no</td>
      <td>候选来源，例如 protocol, review text, study table, article text</td>
    </tr>
    <tr>
      <td><code>specification_status</code></td>
      <td>string?</td>
      <td>no</td>
      <td><code>pre_specified</code> / <code>exploratory</code></td>
    </tr>
    <tr>
      <td><code>selection_status</code></td>
      <td>string?</td>
      <td>no</td>
      <td><code>selected</code> / <code>not_selected</code> / <code>uncertain</code></td>
    </tr>
  </tbody>
</table>


候选层约束：

- `timepoint_candidates` 和 `subgroup_candidates` 是复数候选集合，不作为下游 synthesis unit。
- `subgroup_candidates` 应按 factor/levels 组织，因为 subgroup difference test 比较的是同一 factor 下不同 levels 的 estimates。
- `outcome_measure_candidates`、`timepoint_candidates`、`subgroup_candidates` 和 `data_type_candidates` 都是候选集合；最终是否能进入 synthesis 由 Analysis Setting Finalization 决定。
- 候选层可以保留不确定或未被选中的候选，但只有被 finalization 选中的组合才会生成 `AnalysisSetting`。
- `exploratory` subgroup 可以进入当前 workflow 输出，但默认按探索性结果解释；`pre_specified` subgroup 在解释优先级上更高。

#### 7.4.2 Analysis Setting Finalization

Analysis Setting Finalization 将 `CandidateSynthesisDimension` 转换为最终 `AnalysisSetting`。

转换关系：

```text
CandidateSynthesisDimension 1 -> n AnalysisSetting
```

`AnalysisSetting` unique key:

```text
population_scope x comparison x outcome_concept x outcome_measure x timepoint x subgroup x data_type
```

`setting_family_id` family key:

```text
population_scope x comparison x outcome_concept x outcome_measure x timepoint x data_type
```

输入字段：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Source</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>candidate_synthesis_dimensions</code></td>
      <td>list[CandidateSynthesisDimension]</td>
      <td>Candidate Synthesis Dimension Generation</td>
      <td>待转换的候选 synthesis dimensions；该对象已经承载 finalization 所需的候选 outcome measure、timepoint、subgroup、data type 和 study scope 信息</td>
    </tr>
  </tbody>
</table>


输出字段：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>analysis_settings</code></td>
      <td>list[AnalysisSetting]</td>
      <td>最终 analysis settings；进入 <code>MetaAnalysisResultPackage</code> 并作为后续子任务的 join unit</td>
    </tr>
  </tbody>
</table>


候选到 final setting 的字段映射：


<table>
  <thead>
    <tr>
      <th>Candidate field</th>
      <th>AnalysisSetting field</th>
      <th>Conversion rule</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>population_scope</code></td>
      <td><code>population_scope</code></td>
      <td>直接继承；即使所有 settings 相同也必须显式填写</td>
    </tr>
    <tr>
      <td><code>comparison</code></td>
      <td><code>comparison.experimental_intervention</code> / <code>comparison.comparator</code></td>
      <td>直接继承并拆入 final comparison 字段</td>
    </tr>
    <tr>
      <td><code>outcome_concept</code></td>
      <td><code>outcome.outcome_concept</code></td>
      <td>直接继承</td>
    </tr>
    <tr>
      <td><code>outcome_measure_candidates[]</code></td>
      <td><code>outcome.outcome_measure</code></td>
      <td>从候选集合中选择单个 outcome measure；多个 selected measures 必须展开为多个 <code>AnalysisSetting</code></td>
    </tr>
    <tr>
      <td><code>timepoint_candidates[]</code></td>
      <td><code>timepoint</code></td>
      <td>从候选集合中选择单个 timepoint；多个 selected timepoints 必须展开为多个 <code>AnalysisSetting</code></td>
    </tr>
    <tr>
      <td><code>subgroup_candidates[]</code></td>
      <td><code>subgroup</code></td>
      <td>不做 subgroup 时绑定为空；做 subgroup 时每个 selected factor-level 绑定为一个 subgroup-level <code>AnalysisSetting</code></td>
    </tr>
    <tr>
      <td><code>data_type_candidates[]</code></td>
      <td><code>data_type</code></td>
      <td>从候选集合中选择单个 data type；如果 <code>Dichotomous</code> 和 <code>Continuous</code> 都被选中，必须展开为多个 <code>AnalysisSetting</code></td>
    </tr>
    <tr>
      <td><code>eligible_study_candidates[]</code></td>
      <td><code>eligible_studies</code> / <code>excluded_studies[]</code></td>
      <td>转换为 final setting 的 eligible study IDs；不进入该 setting 的 studies 写入 <code>excluded_studies[]</code> 及 reason</td>
    </tr>
  </tbody>
</table>


`AnalysisSetting` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>setting_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>当前 review 内稳定 setting ID</td>
    </tr>
    <tr>
      <td><code>setting_family_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>绑定同一 population、comparison、outcome、outcome measure、timepoint 和 data_type 下的 overall setting 与 sibling subgroup-level settings；不包含 subgroup level</td>
    </tr>
    <tr>
      <td><code>candidate_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>来源 <code>CandidateSynthesisDimension.candidate_id</code></td>
    </tr>
    <tr>
      <td><code>population_scope</code></td>
      <td>string</td>
      <td>yes</td>
      <td>该 final synthesis unit 覆盖的人群范围；即使所有 settings 相同也需要显式填写</td>
    </tr>
    <tr>
      <td><code>comparison</code></td>
      <td>AnalysisComparison</td>
      <td>yes</td>
      <td>review-level experimental intervention and comparator</td>
    </tr>
    <tr>
      <td><code>outcome</code></td>
      <td>AnalysisOutcome</td>
      <td>yes</td>
      <td>review-level outcome concept、measure 和 benefit direction</td>
    </tr>
    <tr>
      <td><code>timepoint</code></td>
      <td>AnalysisTimepoint</td>
      <td>yes</td>
      <td>最终绑定的单个 timepoint</td>
    </tr>
    <tr>
      <td><code>subgroup</code></td>
      <td>AnalysisSubgroup</td>
      <td>yes</td>
      <td>overall setting 中 factor/level 为空；subgroup-level setting 中 factor/level 均非空</td>
    </tr>
    <tr>
      <td><code>data_type</code></td>
      <td>string</td>
      <td>yes</td>
      <td><code>Dichotomous</code> / <code>Continuous</code></td>
    </tr>
    <tr>
      <td><code>eligible_studies</code></td>
      <td>list[string]</td>
      <td>yes</td>
      <td>可进入该 setting 的 included study IDs</td>
    </tr>
    <tr>
      <td><code>eligible_study_candidates</code></td>
      <td>list[AnalysisSettingStudyCandidate]</td>
      <td>no</td>
      <td>该 setting 下可贡献 result data 的 study-level extraction plan；用于生成 StudyResultTarget，不进入最终 effect estimate</td>
    </tr>
    <tr>
      <td><code>excluded_studies</code></td>
      <td>list[AnalysisSettingExcludedStudy]</td>
      <td>yes</td>
      <td>不进入该 setting 的 studies 及原因</td>
    </tr>
  </tbody>
</table>


`AnalysisSettingStudyCandidate` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>study_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>当前 setting 下可贡献 result data 的 included study</td>
    </tr>
    <tr>
      <td><code>article_id</code></td>
      <td>string?</td>
      <td>no</td>
      <td>该 study 对应的文章证据 ID；也可由外层 article-study link 解析</td>
    </tr>
    <tr>
      <td><code>extraction_task_id</code></td>
      <td>string?</td>
      <td>no</td>
      <td>当前 setting-study-article 抽取任务 ID；candidate-set 主流程使用该 ID 对齐 Subtask 2 输出</td>
    </tr>
    <tr>
      <td><code>extraction_targets</code></td>
      <td>list[AnalysisSettingExtractionTarget]</td>
      <td>no</td>
      <td>legacy target-slot 计划；仅用于兼容旧 benchmark，不是当前主流程的 row disambiguation 机制</td>
    </tr>
  </tbody>
</table>


`AnalysisSettingExtractionTarget` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>target_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>当前 setting-study-result target 的稳定 ID；Subtask 2 输出 <code>StudyResultRow.row_id</code> 应与其对齐</td>
    </tr>
    <tr>
      <td><code>extraction_hint</code></td>
      <td>string?</td>
      <td>no</td>
      <td>legacy optional 非数值 target descriptor；仅用于兼容已构建数据，不是 Subtask 2 的主要定位依据，也不应替代 method 从 article evidence 中识别 row/arm/timepoint</td>
    </tr>
  </tbody>
</table>


`AnalysisComparison` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>experimental_intervention</code></td>
      <td>string</td>
      <td>yes</td>
      <td>review-level experimental intervention</td>
    </tr>
    <tr>
      <td><code>comparator</code></td>
      <td>string</td>
      <td>yes</td>
      <td>review-level comparator/control</td>
    </tr>
  </tbody>
</table>


`AnalysisOutcome` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>outcome_concept</code></td>
      <td>string</td>
      <td>yes</td>
      <td>review-level outcome domain/concept</td>
    </tr>
    <tr>
      <td><code>outcome_measure</code></td>
      <td>string?</td>
      <td>no</td>
      <td>该 setting 选定的具体量表、定义或测量方式</td>
    </tr>
    <tr>
      <td><code>direction_of_benefit</code></td>
      <td>string?</td>
      <td>no</td>
      <td><code>higher_is_better</code> / <code>lower_is_better</code> / <code>unclear</code></td>
    </tr>
  </tbody>
</table>


`AnalysisTimepoint` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>label</code></td>
      <td>string</td>
      <td>yes</td>
      <td>最终绑定的单个 timepoint；如果资料无明确 timepoint，可填 <code>not_specified</code></td>
    </tr>
    <tr>
      <td><code>window</code></td>
      <td>string?</td>
      <td>no</td>
      <td>可接受时间窗，例如 0-3 months</td>
    </tr>
    <tr>
      <td><code>source</code></td>
      <td>string?</td>
      <td>no</td>
      <td>timepoint 设定来源描述</td>
    </tr>
  </tbody>
</table>


`AnalysisSubgroup` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>factor</code></td>
      <td>string?</td>
      <td>no</td>
      <td>subgroup 因子；overall setting 中为空</td>
    </tr>
    <tr>
      <td><code>level</code></td>
      <td>string?</td>
      <td>no</td>
      <td>subgroup level；overall setting 中为空</td>
    </tr>
    <tr>
      <td><code>rationale</code></td>
      <td>string?</td>
      <td>no</td>
      <td>subgroup 设定理由</td>
    </tr>
    <tr>
      <td><code>specification_status</code></td>
      <td>string?</td>
      <td>no</td>
      <td><code>pre_specified</code> / <code>exploratory</code></td>
    </tr>
  </tbody>
</table>


`AnalysisSettingExcludedStudy` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>study_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>不进入该 setting 的 study ID</td>
    </tr>
    <tr>
      <td><code>note</code></td>
      <td>string</td>
      <td>yes</td>
      <td>不进入该 setting 的原因，例如 wrong comparison、outcome not measured、timepoint incompatible、data unavailable</td>
    </tr>
  </tbody>
</table>


输出约束：

- `analysis_settings` 可以为空 list，表示当前纳入研究不足以形成可综合的 synthesis unit。
- 每个 `AnalysisSetting` 必须定义明确的 `comparison` 和 `outcome`。
- `setting_family_id` 是 overall setting 与 sibling subgroup-level settings 的连接键；同一 family 共享 population、comparison、outcome concept、outcome measure、timepoint 和 data_type，但不包含 subgroup level。
- 不做 subgroup 时，一个 `setting_family_id` 下只生成一个 overall setting，且 `subgroup.factor` 和 `subgroup.level` 均为空。
- 做 subgroup 时，一个 `setting_family_id` 下应保留对应 overall setting，并为每个 selected subgroup factor-level 生成 sibling subgroup-level settings。
- 同一 subgroup factor 下的 sibling subgroup-level settings 必须共享同一个 `setting_family_id`，供后续 subgroup difference test 使用。
- `outcome.outcome_measure` 是从 `outcome_measure_candidates[]` 中选定的单个值；当同一 outcome concept 下存在多个 measure、scale 或 definition 时必须填写；多个 selected outcome measures 必须展开为多个 `AnalysisSetting`。
- `timepoint` 是单数绑定字段；多个 selected timepoints 必须展开为多个 `AnalysisSetting`。
- `subgroup` 是单数或空；`subgroup.factor` 和 `subgroup.level` 均为空表示 overall setting。
- `subgroup.factor` 和 `subgroup.level` 均非空表示 subgroup-level setting。
- `data_type` 是从 `data_type_candidates[]` 中选定的单个值；如果同一 candidate 下 `Dichotomous` 和 `Continuous` 都被选中，必须展开为多个 `AnalysisSetting`。
- 当前只输出 `data_type = Dichotomous` 或 `data_type = Continuous` 的 settings。
- `eligible_studies` 只记录 study IDs，不在本模块内拆解 study-level arm、outcome row 或 numeric data。
- `eligible_study_candidates[].extraction_task_id` 是当前主流程的 setting-study-article 抽取任务 ID。一个 task 可以返回一个或多个 candidate result rows。
- `eligible_study_candidates[].extraction_targets[]` 是 legacy target-slot 计划；当前仅用于兼容旧 benchmark。该字段不得包含 event counts、totals、mean、SD/SE/CI、effect estimate、official row index、gold row ID 或 benchmark-only answer。
- benchmark 可在 `eligible_study_candidates[].extraction_hint_parts` 中保留 official analysis 的非数值上下文，例如 analysis labels、setting subgroup、study-row subgroup/footnote/applicability。该对象用于对比实验和审计；接入 workflow method 前必须按显式 policy 转换为 `StudyResultTask.extraction_hint: string?`。
- `eligible_studies[*]` 必须能通过 study ID 连接到 Search & Article Retrieval 返回的 `CleanedArticle.study_id`。
- `excluded_studies` 只用于记录 review-level setting 排除原因，不替代 Study Screening 的 include/exclude 判断。
- `data_type` 描述该 setting 计划采用的数据类型，不表示已经完成数值抽取。
- `effect_measure` 不属于 `AnalysisSetting` 输出字段；由 Analysis Model Decision 基于 setting 和已抽取的 study-level result data 决定。

### 7.5 Subtask 2: Study-level Result Data Extraction

Study-level Result Data Extraction 从每个 included study 的文章证据中，抽取该 study 在某个 analysis setting
下贡献给 meta-analysis 的一个或多个 candidate result rows。`StudyResultTask` 是 Meta Analysis 模块内部调度对象，
用于把 `AnalysisSetting`、study 和 article/source 绑定到一个抽取任务；它不进入最终 `MetaAnalysisResultPackage`。

任务单位：

```text
one study x one AnalysisSetting x one article/source
```

简单 pairwise RCT 场景下，一个 `study x analysis setting` 通常只返回一个 result item。如果同一 study 在同一
setting 下存在多条 article-local result rows（例如 multi-arm dose arms 均对同一 comparator），method 应在同一个
`StudyResultRow.result_items[]` 中返回多条 `StudyResultItem`。method 内部 item 粒度应对齐到 article-local
`row x experimental arm x control arm`；外层 workflow task unit 仍保持 `one study x one AnalysisSetting x one
article/source`。`result_items[]` 是 Subtask 2 的 canonical result container；primitive result data 只允许出现在
`result_items[].result_data`。`candidate_results[]` 仅作为 legacy alias 保留。

`StudyResultTask` 由 `AnalysisSetting.eligible_study_candidates[]` 展开生成。`extraction_targets` 是 legacy
target-slot 计划；`extraction_hint` 是可选的非数值上下文字符串，可以来自 workflow 上游或 benchmark adapter
按 policy 从 `extraction_hint_parts` 生成。它不得包含 result data、official row index、gold row ID 或
benchmark-only answer，也不是评测 join key。当前 pairwise 主实验集要求 method 主要依据 `AnalysisSetting`
和 article/raw table evidence 定位 article-local result items；当 setting 粒度不足以唯一定位时，method 应返回
`result_items` 并使用 `match_status = possible` 表达语义兼容但未唯一确认。`possible` 不等于错误；它可能是 gold，
也可能因为 review-level setting 本身较粗而需要下游 analysis resolution。如果 `extraction_hint` 明确给出非数值约束
（例如 component、timepoint、study-row note 或 subgroup），method 可用它将兼容 item 标为 `matched`。明显不兼容的
sibling records 不应进入 `result_items[]`，或应标记为 `analysis_disposition = exclude` 仅供 debug。

Method 在文章证据选择阶段应区分 direct result source 和 support source。`AnalysisSetting` 是 review-level 目标，
可能比 article-local result setting 更宽；article 中更细粒度的 result source 可作为 `possible` result evidence
召回，并在后续 candidate/result item 中用 `study_local_note`、`match_status` 和 resolution metadata 区分。
不直接报告目标 result data、但可帮助解释 arms、denominators、population、timepoint、outcome definition 或方法语境的
source 应作为 related/support evidence 保留；`related` 不表示无用或错误。只有既不是可能结果来源、也没有支持价值，
或与目标 setting 明确冲突且没有支持价值的 source，才应在 method 内部 selection 阶段丢弃。

Agentic method 可将 selected text blocks 作为一个 text evidence bundle 进入候选生成和数值抽取；这用于让正文中的
definition、denominator context 和 result statement 在同一语境下被读取。Table evidence 仍应以 single raw table XML
为主要读取单元逐表处理，不应通过 deterministic table parsing 替代 LLM table understanding。

Candidate proposal stage 应显式判断 article-local candidate 的数据类型和目标 `AnalysisSetting.data_type` 的兼容性。
`matched` / `possible` result items 必须是 data-type compatible，或 evidence 本身确实无法判断 data type；语义相关但
data type 明确不兼容的 source/candidate 应保留为 `related` / support trace，而不进入 primitive result extraction。
例如 `Dichotomous` target 的 active result candidates 应可支持 events / total 或可合法推导这些字段；`Continuous`
target 的 active result candidates 应可支持 mean / SD / total 或可合法推导这些字段。该规则是 workflow-level data
contract，不是 source selection 阶段的硬过滤：同一 source 可以同时包含 result evidence 和 support evidence。

Method 在直接抽取和 support-material extraction 之后，可以运行统一的 missing-value recovery stage。该 stage
只面向当前 article-local `StudyResultItem` 仍缺失的 required result fields，LLM 负责基于 raw table/text evidence
判断恢复操作类型：无需算术的语义派生、需要 calculator tool 的算术恢复、需要继续找 evidence，或不可恢复。calculator
tool 只执行确定性算术表达式，不读取文章、不判断 clinical/statistical 语义，也不替代 raw table understanding。

Implementation note: 当前正式实现是 `method_source_local_candidate_extraction`，代码位于 backend 的
`source_local_candidate_extraction/`。该方法完成 source-local candidate discovery、material extraction、
field resolution、need-scoped recovery、deterministic calculation 和 result-item finalization。历史实现保存在本地
`archive/`，不属于运行时依赖，也不作为公共 method 暴露。
recovery 输出必须保留 operation type、输入物料、source refs、semantic rationale 和 calculator trace；不确定或 scope
不兼容时不得强行补值。

如果一个 target 对应的 study/article 报告多个可用 timepoint 或 outcome measure，应按照 `analysis_setting`
和 target 绑定的信息选择对应 result data；不能合并不同 timepoint 或不同 outcome measure 的数据。

输入字段：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Source</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>extraction_task_id</code></td>
      <td>string</td>
      <td>StudyResultTask</td>
      <td>当前 setting-study-article extraction task ID；用于将 method 输出 wrapper row 与抽取任务对齐</td>
    </tr>
    <tr>
      <td><code>setting_id</code></td>
      <td>string</td>
      <td>AnalysisSetting</td>
      <td>当前 analysis setting ID</td>
    </tr>
    <tr>
      <td><code>study_id</code></td>
      <td>string</td>
      <td>ArticleRef / AnalysisSetting.eligible_studies</td>
      <td>当前 study</td>
    </tr>
    <tr>
      <td><code>extraction_hint</code></td>
      <td>string?</td>
      <td>StudyResultTask / StudyResultTarget / benchmark adapter policy</td>
      <td>可选非数值上下文；不得泄漏 result data。可用于约束 component、timepoint、population、denominator scope 或 row-note alignment，但不是评测 join key</td>
    </tr>
    <tr>
      <td><code>article</code></td>
      <td>CleanedArticle</td>
      <td>Search &amp; Article Retrieval</td>
      <td>当前 study 对应的清洗后文章证据</td>
    </tr>
    <tr>
      <td><code>comparison</code></td>
      <td>AnalysisComparison</td>
      <td>AnalysisSetting</td>
      <td>目标 intervention/comparator</td>
    </tr>
    <tr>
      <td><code>outcome</code></td>
      <td>AnalysisOutcome</td>
      <td>AnalysisSetting</td>
      <td>目标 outcome</td>
    </tr>
    <tr>
      <td><code>timepoint</code></td>
      <td>AnalysisTimepoint</td>
      <td>AnalysisSetting</td>
      <td>目标 timepoint；抽取后的 <code>StudyResultRow.timepoint</code> 只保留 <code>AnalysisSetting.timepoint.label</code></td>
    </tr>
    <tr>
      <td><code>subgroup</code></td>
      <td>AnalysisSubgroup</td>
      <td>AnalysisSetting</td>
      <td>目标 subgroup；overall setting 中 factor/level 为空，subgroup-level setting 中 factor/level 均非空</td>
    </tr>
    <tr>
      <td><code>data_type</code></td>
      <td>string</td>
      <td>AnalysisSetting</td>
      <td><code>Dichotomous</code> / <code>Continuous</code></td>
    </tr>
  </tbody>
</table>


输出字段：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>study_result_rows</code></td>
      <td>list[StudyResultRow]</td>
      <td>study-level result data；进入 <code>MetaAnalysisResultPackage</code></td>
    </tr>
  </tbody>
</table>


#### 7.5.1 StudyResultRow Schema

`StudyResultRow` 是 `one study x one AnalysisSetting x one article/source` 的 task-level 公共外壳；实际 article-local
result data 由 `result_items[]` 承载。每个 `StudyResultItem.result_data` 根据 `data_type` 绑定到
`DichotomousResultData` 或 `ContinuousResultData`。本子任务不输出 effect measure；effect measure 属于后续
analysis method 和 effect estimate 层。

当前 workflow 只支持 arm-level result data：二分类数据抽取 events / total，连续型数据抽取 mean / SD / total。直接抽取 adjusted effect estimate、standard error、hazard ratio、rate ratio 或其他 contrast-level result data 不在当前 schema 中表达。


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>row_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>study-level result row ID</td>
    </tr>
    <tr>
      <td><code>setting_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>对应 analysis setting</td>
    </tr>
    <tr>
      <td><code>study_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>当前 study</td>
    </tr>
    <tr>
      <td><code>study_year</code></td>
      <td>string?</td>
      <td>no</td>
      <td>study year</td>
    </tr>
    <tr>
      <td><code>extraction_status</code></td>
      <td>string</td>
      <td>yes</td>
      <td><code>extracted</code> / <code>data_unavailable</code> / <code>not_applicable</code> / <code>ambiguous</code></td>
    </tr>
    <tr>
      <td><code>data_type</code></td>
      <td>string</td>
      <td>yes</td>
      <td><code>Dichotomous</code> / <code>Continuous</code></td>
    </tr>
    <tr>
      <td><code>comparison</code></td>
      <td>StudyResultComparison</td>
      <td>yes</td>
      <td>study-level experimental and control arms</td>
    </tr>
    <tr>
      <td><code>outcome</code></td>
      <td>StudyResultOutcome</td>
      <td>yes</td>
      <td>该 result row 对应的 review-level outcome concept</td>
    </tr>
    <tr>
      <td><code>timepoint</code></td>
      <td>string</td>
      <td>yes</td>
      <td>实际抽取的 timepoint；如果资料无明确 timepoint，填 <code>not_specified</code></td>
    </tr>
    <tr>
      <td><code>subgroup</code></td>
      <td>StudyResultSubgroup</td>
      <td>yes</td>
      <td>actual or applicable subgroup; overall setting 中 factor/level 为空</td>
    </tr>
    <tr>
      <td><code>result_items</code></td>
      <td>list[StudyResultItem]</td>
      <td>yes</td>
      <td>canonical article-local result item container；所有实际 primitive result data 均位于 <code>result_items[].result_data</code></td>
    </tr>
    <tr>
      <td><code>evidence_spans</code></td>
      <td>list[EvidenceSpan]?</td>
      <td>no</td>
      <td>可选 provenance/debug 字段；不作为 effect estimate calculation 的必需输入</td>
    </tr>
    <tr>
      <td><code>candidate_results</code></td>
      <td>list[StudyResultItem]?</td>
      <td>no</td>
      <td>legacy alias of <code>result_items</code>；保留用于旧 benchmark/method 兼容</td>
    </tr>
    <tr>
      <td><code>study_result_note</code></td>
      <td>string?</td>
      <td>no</td>
      <td>给下游使用的 study-level result 区分说明；通常由 candidate 的 <code>study_local_note</code> 汇总或透传，尤其用于 ambiguous setting 下区分多个可能数值</td>
    </tr>
    <tr>
      <td><code>extraction_status_reason</code></td>
      <td>string?</td>
      <td>no</td>
      <td>解释 <code>extraction_status</code> 的 debug/status reason；不作为 downstream result semantics</td>
    </tr>
  </tbody>
</table>


`StudyResultComparison` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>experimental_arm</code></td>
      <td>string</td>
      <td>yes</td>
      <td>study 中对应 intervention 的实验组名称</td>
    </tr>
    <tr>
      <td><code>control_arm</code></td>
      <td>string</td>
      <td>yes</td>
      <td>study 中对应 comparator 的对照组名称</td>
    </tr>
  </tbody>
</table>


`StudyResultOutcome` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>outcome_concept</code></td>
      <td>string</td>
      <td>yes</td>
      <td>该 result row 对应的 review-level outcome concept；应与 <code>AnalysisSetting.outcome.outcome_concept</code> 对齐</td>
    </tr>
  </tbody>
</table>


`StudyResultSubgroup` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>factor</code></td>
      <td>string?</td>
      <td>no</td>
      <td>实际抽取或适用的 subgroup factor；overall setting 中为空</td>
    </tr>
    <tr>
      <td><code>level</code></td>
      <td>string?</td>
      <td>no</td>
      <td>实际抽取或适用的 subgroup level；overall setting 中为空</td>
    </tr>
  </tbody>
</table>


`StudyResultItem` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>item_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>method 在当前 article/task 内生成的 result item ID；可与 legacy <code>candidate_id</code> 相同</td>
    </tr>
    <tr>
      <td><code>candidate_id</code></td>
      <td>string</td>
      <td>no</td>
      <td>legacy candidate ID；不是 benchmark gold row ID</td>
    </tr>
    <tr>
      <td><code>match_status</code></td>
      <td>string</td>
      <td>yes</td>
      <td><code>matched</code> / <code>possible</code> / <code>rejected</code>；<code>matched</code> 表示语义明确匹配当前 setting，<code>possible</code> 表示语义兼容但 setting 粒度不足或仍需 resolution，<code>rejected</code> 表示明显不兼容</td>
    </tr>
    <tr>
      <td><code>analysis_disposition</code></td>
      <td>string</td>
      <td>yes</td>
      <td><code>ready_for_estimate</code> / <code>needs_resolution</code> / <code>candidate_only</code> / <code>exclude</code>；表示该 item 在下游分析流程中的处置方式</td>
    </tr>
    <tr>
      <td><code>include_in_estimate</code></td>
      <td>boolean?</td>
      <td>no</td>
      <td><code>true</code> 仅表示该 item 可直接进入后续 estimate calculation；<code>null</code> 表示需要 resolution 或仅保留候选；<code>false</code> 表示排除</td>
    </tr>
    <tr>
      <td><code>study_result_setting</code></td>
      <td>StudyResultSetting</td>
      <td>yes</td>
      <td>文章内实际 row/arm/timepoint/statistic descriptor，用于说明该候选对应的 study-level setting；candidate 的 method 内部粒度建议对齐到 article-local <code>row x experimental arm x control arm</code></td>
    </tr>
    <tr>
      <td><code>study_local_note</code></td>
      <td>string?</td>
      <td>no</td>
      <td>文章 / study 内部用于区分 candidate 的下游语义字段，等价于 data-row note / footnote / subgroup descriptor；例如 <code>6 months</code>、<code>BDI total</code>、<code>FAS population</code>。不是 debug reason</td>
    </tr>
    <tr>
      <td><code>study_local_result</code></td>
      <td>object?</td>
      <td>no</td>
      <td>文章内实际 result record 的结构化描述，包括 row label、outcome measure、timepoint、population/subgroup、arm labels、source table/section 等</td>
    </tr>
    <tr>
      <td><code>setting_alignment</code></td>
      <td>object?</td>
      <td>no</td>
      <td>该 article-local result record 与 workflow setting 的语义关系；包含 <code>status</code>、<code>reason_types</code> 和简短 rationale。语义上对应 <code>match_status</code></td>
    </tr>
    <tr>
      <td><code>data_type</code></td>
      <td>string</td>
      <td>yes</td>
      <td><code>Dichotomous</code> / <code>Continuous</code></td>
    </tr>
    <tr>
      <td><code>result_data</code></td>
      <td>DichotomousResultData / ContinuousResultData?</td>
      <td>conditional</td>
      <td>该候选对应的 primitive result data；不得包含 official row index、gold row ID 或 benchmark-only answer</td>
    </tr>
    <tr>
      <td><code>numeric_extraction</code></td>
      <td>object?</td>
      <td>no</td>
      <td>数值抽取/补全状态，包含 <code>status = complete | partial | unavailable</code>、missing fields、support materials、material mapping、missing-value recovery 和 calculator trace</td>
    </tr>
    <tr>
      <td><code>derivation</code></td>
      <td>StudyResultDerivation?</td>
      <td>no</td>
      <td>说明该 candidate 的 result data 是直接抽取、语义派生还是由 deterministic calculator 补全；LLM 不直接承担数值计算</td>
    </tr>
    <tr>
      <td><code>evidence_spans</code></td>
      <td>list[EvidenceSpan]?</td>
      <td>no</td>
      <td>候选的可追溯证据</td>
    </tr>
    <tr>
      <td><code>confidence</code></td>
      <td>string?</td>
      <td>no</td>
      <td>method 自评置信度，仅用于诊断</td>
    </tr>
    <tr>
      <td><code>note</code></td>
      <td>string?</td>
      <td>no</td>
      <td>legacy/display-only summary；新的下游语义字段使用 <code>study_local_note</code>，状态解释使用 <code>setting_alignment</code> 或 row-level <code>extraction_status_reason</code></td>
    </tr>
  </tbody>
</table>

Benchmark / evaluation note:

- benchmark gold 可以为 `StudyResultRow` 或 `study_result_candidate_sets` 附加 `review_label` 与 `audit_note`，用于标记 benchmark-side 审计结论，例如 source material 缺失、gold numeric values 不被当前 article inputs 直接支持等；这些字段不属于 method 必须输出的 workflow contract。
- Subtask 2 benchmark 除完整行匹配指标外，还可以额外报告不含分母字段的诊断指标，例如 `target_value_only_close_rate`、`candidate_value_only_recall`，以及仅针对 `*_total` 的 denominator diagnostics；这些指标用于区分 value extraction failure 与 review-level denominator mismatch。
- 连续型数据的 SE/CI 只能作为 deterministic calculator 的输入物料，不由 LLM 直接计算。method 应尽量区分 SE/CI 属于 arm-level group mean、arm-level change-score mean、between-group effect、adjusted model estimate 还是 unclear；只有语义 scope 与目标 arm-level field 兼容的统计量可用于推导 arm-level SD。
- 缺失字段恢复是 Subtask 2 method 内部可选能力：LLM 可以提出 `direct_semantic_derivation` 或 `arithmetic_calculation` operation，但算术必须由 calculator tool 执行，且 recovery 不应覆盖已经可信映射的直接值。

Method implementation note:

- 当前 method 的任务边界与方法约束见 [Meta-analysis Subtask 2：研究级结果数据抽取契约](contracts/meta_analysis/subtask2_study_results.md)，当前源码实现与待定项见 [Meta-analysis Subtask 2：当前实现说明](implementation/meta-analysis-subtask2.md)。历史 v6-v10 设计文档只作为 archive，不再作为当前 workflow contract 的解释来源。
- 当前只有一个公共 method：`method_source_local_candidate_extraction`，用于端到端 result item 抽取。candidate discovery 审计是该实现的内部运行/benchmark 诊断能力，不再作为第二个公共 method 暴露。历史实现位于本地 `archive/`，只用于人工审计或历史对比。
- 表格仍以 single raw table XML 作为读取单元交给 LLM；不得用 deterministic table parsing 或清洗替代表格理解。文本 source packing、source profiling、candidate discovery、material extraction 与 recovery 都是 method 内部实现细节，不改变本节的输入输出 contract。
- LLM skills 只负责语义判断和证据读取；工程代码负责 schema validation、trace assembly、retry/concurrency control、deterministic calculator 和 finalizer。
- 缺失字段恢复需要区分 `semantic_derivation` 与 `arithmetic_calculation`。前者表示根据文章语义把已有 material value 继承/复用于字段，不做算术；后者必须由 deterministic calculator 执行。
- 非算术型恢复只能作为 evidence-grounded semantic inference：LLM 可以说明为什么已有 material value 在当前 scope 下等价或可继承，但不能生成新数值；需要新数值时必须进入 calculator 或返回 evidence 不足。
- method 需要对所有 LLM skill 做 context budget 管理，避免把所有 sources、candidates、materials 和历史推理一次性拼入 prompt；超过预算时应记录 `context_budget_exceeded`，而不是静默截断导致误读。
- `possible + complete result_data` 仍必须输出为 `analysis_disposition = needs_resolution`、`include_in_estimate = null`；完整数值不代表 article-local identity 已唯一解决。


`StudyResultSetting` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>row_label</code></td>
      <td>string?</td>
      <td>no</td>
      <td>文章内 row label 或 outcome row label</td>
    </tr>
    <tr>
      <td><code>outcome_label</code></td>
      <td>string?</td>
      <td>no</td>
      <td>文章内 outcome label</td>
    </tr>
    <tr>
      <td><code>outcome_measure</code></td>
      <td>string?</td>
      <td>no</td>
      <td>文章内 scale/measure/definition label</td>
    </tr>
    <tr>
      <td><code>timepoint</code></td>
      <td>string?</td>
      <td>no</td>
      <td>文章内 timepoint 或 follow-up label</td>
    </tr>
    <tr>
      <td><code>statistic_type</code></td>
      <td>string?</td>
      <td>no</td>
      <td>例如 baseline、final_value、change_score、follow_up 或 article-specific statistic label</td>
    </tr>
    <tr>
      <td><code>population_or_subgroup</code></td>
      <td>string?</td>
      <td>no</td>
      <td>文章内 population/subgroup/stratum label</td>
    </tr>
    <tr>
      <td><code>experimental_arm_label</code></td>
      <td>string?</td>
      <td>no</td>
      <td>文章内 experimental arm label</td>
    </tr>
    <tr>
      <td><code>control_arm_label</code></td>
      <td>string?</td>
      <td>no</td>
      <td>文章内 control arm label</td>
    </tr>
    <tr>
      <td><code>table_local_notes</code></td>
      <td>string?</td>
      <td>no</td>
      <td>文章表格内用于区分 candidate 的局部说明，例如 dose、row footnote、table section 或其他非数值 descriptor</td>
    </tr>
  </tbody>
</table>


`DichotomousResultData` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>experimental_events</code></td>
      <td>number/string</td>
      <td>yes</td>
      <td>实验组事件数</td>
    </tr>
    <tr>
      <td><code>experimental_total</code></td>
      <td>number/string</td>
      <td>yes</td>
      <td>实验组总人数/样本量</td>
    </tr>
    <tr>
      <td><code>control_events</code></td>
      <td>number/string</td>
      <td>yes</td>
      <td>对照组事件数</td>
    </tr>
    <tr>
      <td><code>control_total</code></td>
      <td>number/string</td>
      <td>yes</td>
      <td>对照组总人数/样本量</td>
    </tr>
  </tbody>
</table>


`ContinuousResultData` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>experimental_mean</code></td>
      <td>number/string</td>
      <td>yes</td>
      <td>实验组均值</td>
    </tr>
    <tr>
      <td><code>experimental_sd</code></td>
      <td>number/string</td>
      <td>yes</td>
      <td>实验组标准差</td>
    </tr>
    <tr>
      <td><code>experimental_total</code></td>
      <td>number/string</td>
      <td>yes</td>
      <td>实验组总人数/样本量</td>
    </tr>
    <tr>
      <td><code>control_mean</code></td>
      <td>number/string</td>
      <td>yes</td>
      <td>对照组均值</td>
    </tr>
    <tr>
      <td><code>control_sd</code></td>
      <td>number/string</td>
      <td>yes</td>
      <td>对照组标准差</td>
    </tr>
    <tr>
      <td><code>control_total</code></td>
      <td>number/string</td>
      <td>yes</td>
      <td>对照组总人数/样本量</td>
    </tr>
  </tbody>
</table>


`EvidenceSpan` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>field</code></td>
      <td>string</td>
      <td>yes</td>
      <td>被支持的输出字段，例如 <code>result_data.experimental_total</code></td>
    </tr>
    <tr>
      <td><code>source_type</code></td>
      <td>string</td>
      <td>yes</td>
      <td><code>text</code> / <code>table</code> / <code>figure</code> / <code>supplement</code></td>
    </tr>
    <tr>
      <td><code>section</code></td>
      <td>string?</td>
      <td>no</td>
      <td>证据所在 section</td>
    </tr>
    <tr>
      <td><code>text</code></td>
      <td>string</td>
      <td>yes</td>
      <td>支持该字段的证据片段</td>
    </tr>
  </tbody>
</table>


字段约束：

- 当 `data_type = Dichotomous` 时，`result_data` 必须符合 `DichotomousResultData` schema，且四个字段必须同时存在。
- 当 `data_type = Continuous` 时，`result_data` 必须符合 `ContinuousResultData` schema，且六个字段必须同时存在。
- `outcome.outcome_concept` 必须与 `AnalysisSetting.outcome.outcome_concept` 对齐。
- `timepoint` 必须与 `AnalysisSetting.timepoint.label` 对齐；如果 setting 使用 `not_specified`，row 也应填 `not_specified`。
- `StudyResultRow` 不重复输出 `outcome_measure`；具体量表、定义或测量方式从 `AnalysisSetting.outcome.outcome_measure` 继承。
- 对 overall setting，`subgroup.factor` 和 `subgroup.level` 应为空。
- 对 subgroup-level setting，`subgroup.factor` 和 `subgroup.level` 应与 `AnalysisSetting.subgroup` 对齐。
- 每个 `StudyResultRow` 只表达一个 pairwise comparison：一个 experimental arm 和一个 control arm。
- `StudyResultComparison` 不是 meta-analysis 的 grouping key；meta-analysis grouping 由 `AnalysisSetting.setting_id` 决定。`StudyResultComparison` 记录 study-specific arm labels 与目标 `AnalysisComparison` 的映射，用于 provenance 和 compatibility checks。
- multi-arm shared-control 可在 `result_items[].numeric_extraction.analysis_postprocess` 或 related resolution metadata 中表达为需要 downstream analysis resolution；Subtask 2 不在抽取阶段执行 split/combine。cluster RCT、crossover RCT 或其他需要 unit-of-analysis adjustment 的数据暂不进入当前主路径。
- 如果任一 required result data 字段无法从证据中抽取，则 `extraction_status` 不应为 `extracted`。
- `experimental_events <= experimental_total`。
- `control_events <= control_total`。
- `experimental_sd` 和 `control_sd` 必须为非负数。
- `evidence_spans` 是可选 provenance/debug 字段，不作为 Subgroup Estimate Calculation 或 Overall Estimate Calculation 的必需输入。
- 不输出 non-event count；如后续计算需要，由本模块内部计算。
- 不把 SE、CI、IQR、range 直接写入 SD 字段；如需要转换，转换责任属于模块内部，但输出仍必须是 SD。

### 7.6 Subtask 3: Analysis Model Decision

Analysis Model Decision 负责在 study-level result data 已抽取后，为当前 analysis setting 确定真正进入合并计算的 studies，以及 effect measure、合并模型和统计方法。

该子任务不计算 pooled effect，不输出 CI、heterogeneity 数值或 subgroup difference test。它只输出后续 Subgroup Estimate Calculation 和 Overall Estimate Calculation 所需的方法配置与 evidence body 边界。

任务单位：

```text
one analysis setting
```

输入字段：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Source</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>setting_id</code></td>
      <td>string</td>
      <td>AnalysisSetting</td>
      <td>当前 analysis setting</td>
    </tr>
    <tr>
      <td><code>analysis_setting</code></td>
      <td>AnalysisSetting</td>
      <td>Analysis Setting Definition</td>
      <td>当前 setting 的 comparison、outcome、timepoint 和 data_type；不包含 effect measure</td>
    </tr>
    <tr>
      <td><code>study_result_rows</code></td>
      <td>list[StudyResultRow]</td>
      <td>Study-level Result Data Extraction</td>
      <td>当前 setting 下已抽取的 study-level result data</td>
    </tr>
  </tbody>
</table>


输出字段：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>analysis_methods</code></td>
      <td>list[AnalysisMethod]</td>
      <td>内部 method configuration/provenance；只供 Subgroup Estimate Calculation 和 Overall Estimate Calculation 使用，不进入 <code>MetaAnalysisResultPackage</code></td>
    </tr>
  </tbody>
</table>


`AnalysisMethod` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>method_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>当前 review 内稳定 method ID</td>
    </tr>
    <tr>
      <td><code>setting_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>对应 analysis setting</td>
    </tr>
    <tr>
      <td><code>method_status</code></td>
      <td>string</td>
      <td>yes</td>
      <td><code>ready</code> / <code>insufficient_data</code> / <code>incompatible_data</code> / <code>unsupported_data_type</code> / <code>ambiguous</code></td>
    </tr>
    <tr>
      <td><code>analysis_included_study_ids</code></td>
      <td>list[string]</td>
      <td>yes</td>
      <td>经过 result data 可用性过滤后，真正进入当前 setting effect estimate calculation 的 studies</td>
    </tr>
    <tr>
      <td><code>analysis_excluded_studies</code></td>
      <td>list[AnalysisExcludedStudy]?</td>
      <td>no</td>
      <td>属于当前 setting 但不能进入合并计算的 studies 及原因</td>
    </tr>
    <tr>
      <td><code>data_type</code></td>
      <td>string</td>
      <td>yes</td>
      <td><code>Dichotomous</code> / <code>Continuous</code></td>
    </tr>
    <tr>
      <td><code>effect_measure</code></td>
      <td>string</td>
      <td>yes</td>
      <td>当前 setting 采用的 effect measure；<code>Dichotomous</code> 可为 Risk Ratio / Odds Ratio / Risk Difference，<code>Continuous</code> 可为 Mean Difference / Std. Mean Difference</td>
    </tr>
    <tr>
      <td><code>analysis_model</code></td>
      <td>string</td>
      <td>yes</td>
      <td><code>fixed_effect</code> / <code>random_effects</code> 等合并模型</td>
    </tr>
    <tr>
      <td><code>statistical_method</code></td>
      <td>string</td>
      <td>yes</td>
      <td>统计方法，例如 Mantel-Haenszel / inverse variance</td>
    </tr>
    <tr>
      <td><code>ci_level</code></td>
      <td>string</td>
      <td>yes</td>
      <td>confidence interval level，例如 <code>95%</code></td>
    </tr>
    <tr>
      <td><code>heterogeneity_estimator</code></td>
      <td>string?</td>
      <td>conditional</td>
      <td>primary random-effects analysis 使用的 Tau² estimator；当 <code>analysis_model = random_effects</code> 时使用，例如 <code>REML</code> / <code>DerSimonian-Laird</code> / <code>Paule-Mandel</code>。同一个 <code>AnalysisMethod</code> 只选择一个 estimator</td>
    </tr>
    <tr>
      <td><code>zero_cell_handling</code></td>
      <td>ZeroCellHandling?</td>
      <td>conditional</td>
      <td>二分类数据存在 zero-cell 时的处理策略</td>
    </tr>
    <tr>
      <td><code>smd_method</code></td>
      <td>string?</td>
      <td>conditional</td>
      <td>当 <code>effect_measure = Std. Mean Difference</code> 时使用的 SMD 计算方法，例如 <code>Hedges_g</code></td>
    </tr>
    <tr>
      <td><code>decision_basis</code></td>
      <td>string?</td>
      <td>no</td>
      <td>模型和方法选择依据的简要说明</td>
    </tr>
  </tbody>
</table>


`AnalysisExcludedStudy` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>study_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>不能进入当前 setting 合并计算的 study</td>
    </tr>
    <tr>
      <td><code>row_id</code></td>
      <td>string?</td>
      <td>no</td>
      <td>对应的 <code>StudyResultRow.row_id</code>，如排除原因发生在具体 result row 层</td>
    </tr>
    <tr>
      <td><code>note</code></td>
      <td>string</td>
      <td>yes</td>
      <td><code>missing_required_result_data</code> / <code>incompatible_timepoint</code> / <code>incompatible_outcome_measure</code> / <code>incompatible_arm_definition</code> / <code>unsupported_data_shape</code> / <code>ambiguous_extraction</code></td>
    </tr>
    <tr>
      <td><code>detail</code></td>
      <td>string?</td>
      <td>no</td>
      <td>简短说明</td>
    </tr>
  </tbody>
</table>


`ZeroCellHandling` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>method</code></td>
      <td>string</td>
      <td>yes</td>
      <td>zero-cell 处理方法，例如 <code>continuity_correction</code> / <code>software_default</code> / <code>none</code></td>
    </tr>
    <tr>
      <td><code>correction_value</code></td>
      <td>number/string?</td>
      <td>no</td>
      <td>continuity correction 值，例如 <code>0.5</code></td>
    </tr>
    <tr>
      <td><code>double_zero_study_rule</code></td>
      <td>string?</td>
      <td>no</td>
      <td>double-zero studies 的处理规则，例如 <code>exclude_for_relative_effect</code> / <code>include_when_method_allows</code></td>
    </tr>
  </tbody>
</table>


说明：

- `analysis_model` 不由 `outcome + comparison` 单独决定，也不在 Analysis Setting Definition 阶段输出。
- `effect_measure` 不在 Analysis Setting Definition 阶段输出；它由本子任务基于 `analysis_setting.data_type`、`analysis_setting.outcome.outcome_measure` 和 `study_result_rows` 的实际可合并性决定。
- 对连续型数据，若 contributing studies 使用同一量表/单位，通常选择 Mean Difference；若同一 outcome concept 下使用不同量表，通常选择 Std. Mean Difference。
- `analysis_model` 基于 `analysis_setting`、已抽取的 `study_result_rows` 和 evidence body 的可合并性假设确定。
- `study_result_rows` 提供可用 study 数、样本量、事件数、均值/SD、zero events 和数据稀疏性等实际计算条件。
- 本模块当前不把 `analysis_model` 作为外部输入字段。
- `analysis_included_study_ids` 不是 Study Screening 的 included studies，而是当前 setting 下能够进入 effect estimate calculation 的 studies。
- `analysis_excluded_studies` 记录 study-level result data 已抽取但不能进入合并计算的原因，不替代 Study Screening 的 include/exclude 判断。
- `statistical_method` 和 `ci_level` 是 required；默认 CI level 为 `95%`。
- `heterogeneity_estimator` 是方法选择，不是 heterogeneity 结果；同一个 `AnalysisMethod` 只选择一个 primary estimator。
- `heterogeneity_estimator` 仅在 `analysis_model = random_effects` 时需要；默认可为 `REML`。如果 `analysis_model = fixed_effect`，可为空或 `not_applicable`。
- 如果后续需要 sensitivity analysis，应使用额外 `AnalysisMethod` 表达，不在 `heterogeneity_estimator` 中放多个 estimator。
- `zero_cell_handling` 仅在 `data_type = Dichotomous` 且存在 zero-cell 时需要。
- `smd_method` 仅在 `effect_measure = Std. Mean Difference` 时需要；默认可为 `Hedges_g`。
- `AnalysisMethod` 是内部 method provenance；`effect_measure`、`analysis_model`、`statistical_method`、`ci_level` 等必要字段会写入 `SubgroupEstimate` 或 `OverallEstimate`。
- 7.6 不输出 `effect_value`、`ci_lower`、`ci_upper`、heterogeneity 数值、study count、participant count 或 subgroup difference test 结果。

### 7.7 Subtask 4: Subgroup Analysis

Subgroup Analysis 包含两个内部任务：

1. `Subgroup Estimate Calculation`
2. `Subgroup Difference Test`

#### 7.7.1 Subgroup Estimate Calculation

Subgroup Estimate Calculation 基于 subgroup-level `AnalysisSetting`、`AnalysisMethod` 和 `study_result_rows`，计算一个 subgroup level 的 pooled effect estimate。

该子任务不重新决定 `effect_measure`、`analysis_model`、`statistical_method` 或 `ci_level`；这些字段来自 7.6 `AnalysisMethod`。

任务单位：

```text
one subgroup-level analysis setting
```

输入字段：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Source</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>setting_id</code></td>
      <td>string</td>
      <td>AnalysisSetting</td>
      <td>当前 subgroup-level analysis setting</td>
    </tr>
    <tr>
      <td><code>analysis_setting</code></td>
      <td>AnalysisSetting</td>
      <td>Analysis Setting Definition</td>
      <td>当前 subgroup-level setting；<code>subgroup.factor</code> 和 <code>subgroup.level</code> 均非空</td>
    </tr>
    <tr>
      <td><code>study_result_rows</code></td>
      <td>list[StudyResultRow]</td>
      <td>Study-level Result Data Extraction</td>
      <td>当前 subgroup-level setting 下的 study-level result data</td>
    </tr>
    <tr>
      <td><code>analysis_method</code></td>
      <td>AnalysisMethod</td>
      <td>Analysis Model Decision</td>
      <td>当前 setting 的 evidence body 边界、effect measure、合并模型和统计方法</td>
    </tr>
  </tbody>
</table>


进入 subgroup estimate calculation 的 row 必须满足：

- `row.setting_id` 与当前 setting 一致。
- `row.extraction_status = extracted`。
- `row.study_id` 在 `analysis_method.analysis_included_study_ids` 中。
- `row.data_type` 与 setting 的 `data_type` 一致。
- `row.subgroup` 与 setting 的 `subgroup` 一致。
- 进入 effect calculation 的 canonical primitive rows 来自 `row.result_items[]`；只有 `item.analysis_disposition = ready_for_estimate` 且 `item.result_data` 满足对应 data type required fields 的 items 可直接进入 estimate。
- `item.analysis_disposition = needs_resolution` 的 items 必须先经过 analysis resolution policy，例如 combine intervention arms、split shared control、select preferred timepoint 或 manual review policy。
- `analysis_method.method_status = ready`。
- 每个 included study 在当前 subgroup-level setting 下可贡献一个或多个 `StudyResultItem`；estimate calculation 使用 item-level effects，`study_count` 按 unique study ID 计数。

Data type handling:

- 当 `data_type = Dichotomous` 时，`result_data` 必须为 `DichotomousResultData`，`effect_measure` 必须为 Risk Ratio、Odds Ratio 或 Risk Difference；存在 zero-cell 时应用 `analysis_method.zero_cell_handling`。
- 当 `data_type = Continuous` 时，`result_data` 必须为 `ContinuousResultData`，`effect_measure` 必须为 Mean Difference 或 Std. Mean Difference；当 `effect_measure = Std. Mean Difference` 时应用 `analysis_method.smd_method`。

输出字段：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>subgroup_estimates</code></td>
      <td>list[SubgroupEstimate]</td>
      <td>subgroup-level effect estimates；进入 <code>MetaAnalysisResultPackage</code></td>
    </tr>
  </tbody>
</table>


`SubgroupEstimate` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>subgroup_estimate_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>subgroup estimate ID</td>
    </tr>
    <tr>
      <td><code>setting_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>对应 subgroup-level analysis setting</td>
    </tr>
    <tr>
      <td><code>setting_family_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>来源 <code>AnalysisSetting.setting_family_id</code></td>
    </tr>
    <tr>
      <td><code>method_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>来源 <code>AnalysisMethod.method_id</code></td>
    </tr>
    <tr>
      <td><code>candidate_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>来源 candidate ID</td>
    </tr>
    <tr>
      <td><code>subgroup_factor</code></td>
      <td>string</td>
      <td>yes</td>
      <td>来源 <code>AnalysisSetting.subgroup.factor</code></td>
    </tr>
    <tr>
      <td><code>subgroup_level</code></td>
      <td>string</td>
      <td>yes</td>
      <td>来源 <code>AnalysisSetting.subgroup.level</code></td>
    </tr>
    <tr>
      <td><code>included_study_ids</code></td>
      <td>list[string]</td>
      <td>yes</td>
      <td>进入该 subgroup estimate 的 studies</td>
    </tr>
    <tr>
      <td><code>study_count</code></td>
      <td>integer</td>
      <td>yes</td>
      <td>study 数量</td>
    </tr>
    <tr>
      <td><code>participant_count</code></td>
      <td>integer</td>
      <td>yes</td>
      <td>participant 总数</td>
    </tr>
    <tr>
      <td><code>data_type</code></td>
      <td>string</td>
      <td>yes</td>
      <td><code>Dichotomous</code> / <code>Continuous</code></td>
    </tr>
    <tr>
      <td><code>effect_measure</code></td>
      <td>string</td>
      <td>yes</td>
      <td>来源 <code>AnalysisMethod.effect_measure</code></td>
    </tr>
    <tr>
      <td><code>analysis_model</code></td>
      <td>string</td>
      <td>yes</td>
      <td>来自 <code>analysis_method.analysis_model</code></td>
    </tr>
    <tr>
      <td><code>statistical_method</code></td>
      <td>string</td>
      <td>yes</td>
      <td>来自 <code>analysis_method.statistical_method</code></td>
    </tr>
    <tr>
      <td><code>ci_level</code></td>
      <td>string</td>
      <td>yes</td>
      <td>来自 <code>analysis_method.ci_level</code></td>
    </tr>
    <tr>
      <td><code>effect_value</code></td>
      <td>number/string?</td>
      <td>conditional</td>
      <td>subgroup-level effect estimate；当 <code>estimation_status = computed</code> 时必填</td>
    </tr>
    <tr>
      <td><code>ci_lower</code></td>
      <td>number/string?</td>
      <td>conditional</td>
      <td>confidence interval lower bound；当 <code>estimation_status = computed</code> 时必填</td>
    </tr>
    <tr>
      <td><code>ci_upper</code></td>
      <td>number/string?</td>
      <td>conditional</td>
      <td>confidence interval upper bound；当 <code>estimation_status = computed</code> 时必填</td>
    </tr>
    <tr>
      <td><code>heterogeneity</code></td>
      <td>HeterogeneitySummary?</td>
      <td>conditional</td>
      <td>subgroup-level heterogeneity summary；当 <code>estimation_status = computed</code> 且 <code>study_count &gt;= 2</code> 时通常应输出；若统计量不适用、未计算或不可计算，可为空或部分为空</td>
    </tr>
    <tr>
      <td><code>estimation_status</code></td>
      <td>string</td>
      <td>yes</td>
      <td><code>computed</code> / <code>insufficient_data</code> / <code>not_applicable</code> / <code>failed</code></td>
    </tr>
    <tr>
      <td><code>estimation_notes</code></td>
      <td>string?</td>
      <td>no</td>
      <td>数据不足、计算失败或特殊方法处理说明</td>
    </tr>
  </tbody>
</table>


`HeterogeneitySummary` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>tau2</code></td>
      <td>number/string?</td>
      <td>no</td>
      <td>between-study variance；主要受 <code>AnalysisMethod.heterogeneity_estimator</code> 影响</td>
    </tr>
    <tr>
      <td><code>chi2</code></td>
      <td>number/string?</td>
      <td>no</td>
      <td>Chi² / Q heterogeneity statistic</td>
    </tr>
    <tr>
      <td><code>df</code></td>
      <td>number/string?</td>
      <td>no</td>
      <td>degrees of freedom</td>
    </tr>
    <tr>
      <td><code>p_value</code></td>
      <td>number/string?</td>
      <td>no</td>
      <td>heterogeneity test p value</td>
    </tr>
    <tr>
      <td><code>i2</code></td>
      <td>number/string?</td>
      <td>no</td>
      <td>I²</td>
    </tr>
  </tbody>
</table>


输出约束：

- 只有 `AnalysisSetting.subgroup` 非空的 setting 才生成 `SubgroupEstimate`。
- `AnalysisSetting.subgroup.factor` 和 `AnalysisSetting.subgroup.level` 必须均非空。
- 每个 subgroup-level `AnalysisSetting` 最多生成一个 `SubgroupEstimate`。
- `setting_family_id` 必须来自对应 `AnalysisSetting.setting_family_id`。
- `included_study_ids` 必须来自 `analysis_method.analysis_included_study_ids`，并且必须能在 `study_result_rows` 中找到对应 extracted rows。
- `study_count = len(included_study_ids)`。
- `participant_count` 为所有 included rows 的 `experimental_total + control_total` 之和。
- `method_id`、`effect_measure`、`analysis_model`、`statistical_method` 和 `ci_level` 来自 Analysis Model Decision 子任务。
- 当 `estimation_status = computed` 时，`effect_value`、`ci_lower` 和 `ci_upper` 必须存在。
- 当 `estimation_status = computed` 且 `study_count >= 2` 时，`heterogeneity` 通常应输出；若统计量不适用、未计算或不可计算，可为空或部分为空。
- `heterogeneity.tau2` 的计算受 `AnalysisMethod.heterogeneity_estimator` 影响；`chi2`、`df`、`p_value` 和 `i2` 是 heterogeneity summary 的其他结果指标，不是 estimator。
- 如果 `analysis_method.method_status != ready`，`estimation_status` 不能为 `computed`。
- 如果可用 study 数不足以计算 subgroup estimate，应输出 `estimation_status = insufficient_data`。
- 本模块不输出 GRADE certainty。

#### 7.7.2 Subgroup Difference Test

Subgroup Difference Test 基于同一 analysis setting family 下、同一 subgroup factor 的多个 sibling `SubgroupEstimate`，计算 subgroup levels 之间 effect difference 的统计检验。

该内部任务不重新计算 subgroup-level estimates，不重新抽取 study-level data；它只比较已经 computed 的 sibling `SubgroupEstimate`。

任务单位：

```text
one candidate x one comparison x one outcome x one timepoint x one data_type x one effect_measure x one subgroup factor
```

输入字段：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Source</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>candidate_id</code></td>
      <td>string</td>
      <td>AnalysisSetting</td>
      <td>同一 candidate 下的 subgroup estimates</td>
    </tr>
    <tr>
      <td><code>setting_family_id</code></td>
      <td>string</td>
      <td>AnalysisSetting / SubgroupEstimate</td>
      <td>同一 analysis setting family 下的 subgroup estimates</td>
    </tr>
    <tr>
      <td><code>comparison</code></td>
      <td>AnalysisComparison</td>
      <td>AnalysisSetting</td>
      <td>同一 comparison 下的 subgroup estimates</td>
    </tr>
    <tr>
      <td><code>outcome</code></td>
      <td>AnalysisOutcome</td>
      <td>AnalysisSetting</td>
      <td>同一 outcome 下的 subgroup estimates</td>
    </tr>
    <tr>
      <td><code>timepoint</code></td>
      <td>AnalysisTimepoint</td>
      <td>AnalysisSetting</td>
      <td>同一 timepoint 下的 subgroup estimates</td>
    </tr>
    <tr>
      <td><code>data_type</code></td>
      <td>string</td>
      <td>AnalysisSetting</td>
      <td><code>Dichotomous</code> / <code>Continuous</code></td>
    </tr>
    <tr>
      <td><code>effect_measure</code></td>
      <td>string</td>
      <td>AnalysisMethod / SubgroupEstimate</td>
      <td>effect measure</td>
    </tr>
    <tr>
      <td><code>subgroup_factor</code></td>
      <td>string</td>
      <td>AnalysisSetting.subgroup</td>
      <td>待比较的 subgroup factor</td>
    </tr>
    <tr>
      <td><code>subgroup_estimates</code></td>
      <td>list[SubgroupEstimate]</td>
      <td>Subgroup Estimate Calculation</td>
      <td>同一 factor 下两个或以上 sibling subgroup-level estimates</td>
    </tr>
  </tbody>
</table>


输出字段：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>subgroup_difference_tests</code></td>
      <td>list[SubgroupDifferenceTest]</td>
      <td>subgroup difference test results；进入 <code>MetaAnalysisResultPackage</code></td>
    </tr>
  </tbody>
</table>


`SubgroupDifferenceTest` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>subgroup_difference_test_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>subgroup difference test ID</td>
    </tr>
    <tr>
      <td><code>candidate_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>来源 candidate ID</td>
    </tr>
    <tr>
      <td><code>setting_family_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>同一 analysis setting family ID</td>
    </tr>
    <tr>
      <td><code>comparison</code></td>
      <td>AnalysisComparison</td>
      <td>yes</td>
      <td>comparison</td>
    </tr>
    <tr>
      <td><code>outcome</code></td>
      <td>AnalysisOutcome</td>
      <td>yes</td>
      <td>outcome</td>
    </tr>
    <tr>
      <td><code>timepoint</code></td>
      <td>AnalysisTimepoint</td>
      <td>yes</td>
      <td>timepoint</td>
    </tr>
    <tr>
      <td><code>data_type</code></td>
      <td>string</td>
      <td>yes</td>
      <td><code>Dichotomous</code> / <code>Continuous</code></td>
    </tr>
    <tr>
      <td><code>effect_measure</code></td>
      <td>string</td>
      <td>yes</td>
      <td>effect measure</td>
    </tr>
    <tr>
      <td><code>subgroup_factor</code></td>
      <td>string</td>
      <td>yes</td>
      <td>被比较的 subgroup factor</td>
    </tr>
    <tr>
      <td><code>level_estimate_ids</code></td>
      <td>list[string]</td>
      <td>yes</td>
      <td>参与检验的 <code>SubgroupEstimate.subgroup_estimate_id</code></td>
    </tr>
    <tr>
      <td><code>chi2</code></td>
      <td>number/string?</td>
      <td>conditional</td>
      <td>subgroup difference Chi²；当 <code>test_status = computed</code> 时必填</td>
    </tr>
    <tr>
      <td><code>df</code></td>
      <td>number/string?</td>
      <td>conditional</td>
      <td>subgroup difference df；当 <code>test_status = computed</code> 时必填</td>
    </tr>
    <tr>
      <td><code>p_value</code></td>
      <td>number/string?</td>
      <td>conditional</td>
      <td>subgroup difference p value；当 <code>test_status = computed</code> 时必填</td>
    </tr>
    <tr>
      <td><code>i2_between_subgroups</code></td>
      <td>number/string?</td>
      <td>conditional</td>
      <td>between-subgroup I²；可计算时输出，可为空或部分为空</td>
    </tr>
    <tr>
      <td><code>test_status</code></td>
      <td>string</td>
      <td>yes</td>
      <td><code>computed</code> / <code>insufficient_subgroups</code> / <code>not_applicable</code> / <code>failed</code></td>
    </tr>
    <tr>
      <td><code>test_notes</code></td>
      <td>string?</td>
      <td>no</td>
      <td>subgroup difference test 的特殊说明、数据不足或失败原因</td>
    </tr>
  </tbody>
</table>


输出约束：

- 只有同一 `setting_family_id`、candidate、comparison、outcome、timepoint、data_type、effect_measure 和 subgroup factor 下的 sibling `SubgroupEstimate` 可以参与比较。
- 只有 `estimation_status = computed` 的 `SubgroupEstimate` 可以进入 subgroup difference test。
- 至少两个 computed `SubgroupEstimate` 才能输出 `test_status = computed`。
- 当 `test_status = computed` 时，`chi2`、`df` 和 `p_value` 必须存在。
- `i2_between_subgroups` 是 between-subgroup I²；可计算时输出，未计算、不适用或不可计算时可为空。
- `SubgroupDifferenceTest` 不依赖 `OverallEstimate`，不重新抽取 study-level data，不计算 subgroup-level estimates，不替代 subgroup estimates 或 overall estimates。

### 7.8 Subtask 5: Overall Estimate Calculation

Overall Estimate Calculation 基于 overall `AnalysisSetting`、`AnalysisMethod` 和 `study_result_rows`，计算 analysis-level overall pooled effect estimate。

该子任务不重新决定 `effect_measure`、`analysis_model`、`statistical_method` 或 `ci_level`；这些字段来自 7.6 `AnalysisMethod`。

任务单位：

```text
one overall analysis setting
```

输入字段：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Source</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>setting_id</code></td>
      <td>string</td>
      <td>AnalysisSetting</td>
      <td>当前 overall analysis setting；<code>subgroup</code> 为空</td>
    </tr>
    <tr>
      <td><code>analysis_setting</code></td>
      <td>AnalysisSetting</td>
      <td>Analysis Setting Definition</td>
      <td>当前 overall setting；<code>subgroup.factor</code> 和 <code>subgroup.level</code> 均为空</td>
    </tr>
    <tr>
      <td><code>study_result_rows</code></td>
      <td>list[StudyResultRow]</td>
      <td>Study-level Result Data Extraction</td>
      <td>当前 overall setting 下的 study-level result data</td>
    </tr>
    <tr>
      <td><code>analysis_method</code></td>
      <td>AnalysisMethod</td>
      <td>Analysis Model Decision</td>
      <td>当前 setting 的 evidence body 边界、effect measure、合并模型和统计方法</td>
    </tr>
  </tbody>
</table>


进入 overall estimate calculation 的 row 必须满足：

- `row.setting_id` 与 `analysis_setting.setting_id` 一致。
- `row.extraction_status = extracted`。
- `row.study_id` 在 `analysis_method.analysis_included_study_ids` 中。
- `row.data_type` 与 `analysis_setting.data_type` 一致。
- `row.subgroup.factor` 和 `row.subgroup.level` 均为空。
- 进入 effect calculation 的 canonical primitive rows 来自 `row.result_items[]`；只有 `item.analysis_disposition = ready_for_estimate` 且 `item.result_data` 满足对应 data type required fields 的 items 可直接进入 estimate。
- `item.analysis_disposition = needs_resolution` 的 items 必须先经过 analysis resolution policy，例如 combine intervention arms、split shared control、select preferred timepoint 或 manual review policy。
- `analysis_method.method_status = ready`。
- 每个 included study 在当前 overall setting 下可贡献一个或多个 `StudyResultItem`；estimate calculation 使用 item-level effects，`study_count` 按 unique study ID 计数。

Data type handling:

- 当 `data_type = Dichotomous` 时，`result_data` 必须为 `DichotomousResultData`，`effect_measure` 必须为 Risk Ratio、Odds Ratio 或 Risk Difference；存在 zero-cell 时应用 `analysis_method.zero_cell_handling`。
- 当 `data_type = Continuous` 时，`result_data` 必须为 `ContinuousResultData`，`effect_measure` 必须为 Mean Difference 或 Std. Mean Difference；当 `effect_measure = Std. Mean Difference` 时应用 `analysis_method.smd_method`。

输出字段：


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>overall_estimates</code></td>
      <td>list[OverallEstimate]</td>
      <td>overall effect estimates；进入 <code>MetaAnalysisResultPackage</code></td>
    </tr>
  </tbody>
</table>


`OverallEstimate` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>overall_estimate_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>overall estimate ID</td>
    </tr>
    <tr>
      <td><code>setting_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>对应 overall analysis setting</td>
    </tr>
    <tr>
      <td><code>setting_family_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>来源 <code>AnalysisSetting.setting_family_id</code></td>
    </tr>
    <tr>
      <td><code>method_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>来源 <code>AnalysisMethod.method_id</code></td>
    </tr>
    <tr>
      <td><code>candidate_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>来源 candidate ID</td>
    </tr>
    <tr>
      <td><code>included_study_ids</code></td>
      <td>list[string]</td>
      <td>yes</td>
      <td>进入 overall estimate 的 studies</td>
    </tr>
    <tr>
      <td><code>study_count</code></td>
      <td>integer</td>
      <td>yes</td>
      <td>study 数量</td>
    </tr>
    <tr>
      <td><code>participant_count</code></td>
      <td>integer</td>
      <td>yes</td>
      <td>participant 总数</td>
    </tr>
    <tr>
      <td><code>data_type</code></td>
      <td>string</td>
      <td>yes</td>
      <td><code>Dichotomous</code> / <code>Continuous</code></td>
    </tr>
    <tr>
      <td><code>effect_measure</code></td>
      <td>string</td>
      <td>yes</td>
      <td>来源 <code>AnalysisMethod.effect_measure</code></td>
    </tr>
    <tr>
      <td><code>analysis_model</code></td>
      <td>string</td>
      <td>yes</td>
      <td>来自 <code>analysis_method.analysis_model</code></td>
    </tr>
    <tr>
      <td><code>statistical_method</code></td>
      <td>string</td>
      <td>yes</td>
      <td>来自 <code>analysis_method.statistical_method</code></td>
    </tr>
    <tr>
      <td><code>ci_level</code></td>
      <td>string</td>
      <td>yes</td>
      <td>来自 <code>analysis_method.ci_level</code></td>
    </tr>
    <tr>
      <td><code>effect_value</code></td>
      <td>number/string?</td>
      <td>conditional</td>
      <td>overall effect estimate；当 <code>estimation_status = computed</code> 时必填</td>
    </tr>
    <tr>
      <td><code>ci_lower</code></td>
      <td>number/string?</td>
      <td>conditional</td>
      <td>confidence interval lower bound；当 <code>estimation_status = computed</code> 时必填</td>
    </tr>
    <tr>
      <td><code>ci_upper</code></td>
      <td>number/string?</td>
      <td>conditional</td>
      <td>confidence interval upper bound；当 <code>estimation_status = computed</code> 时必填</td>
    </tr>
    <tr>
      <td><code>prediction_interval</code></td>
      <td>PredictionInterval?</td>
      <td>conditional</td>
      <td>overall-level prediction interval；主要适用于 random-effects overall estimate；未计算、不适用或数据不足时为空</td>
    </tr>
    <tr>
      <td><code>heterogeneity</code></td>
      <td>HeterogeneitySummary?</td>
      <td>conditional</td>
      <td>overall heterogeneity summary；当 <code>estimation_status = computed</code> 且 <code>study_count &gt;= 2</code> 时通常应输出；若统计量不适用、未计算或不可计算，可为空或部分为空</td>
    </tr>
    <tr>
      <td><code>estimation_status</code></td>
      <td>string</td>
      <td>yes</td>
      <td><code>computed</code> / <code>insufficient_data</code> / <code>not_applicable</code> / <code>failed</code></td>
    </tr>
    <tr>
      <td><code>estimation_notes</code></td>
      <td>string?</td>
      <td>no</td>
      <td>数据不足、计算失败或特殊方法处理说明</td>
    </tr>
  </tbody>
</table>


`PredictionInterval` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>lower</code></td>
      <td>number/string</td>
      <td>yes</td>
      <td>prediction interval lower bound</td>
    </tr>
    <tr>
      <td><code>upper</code></td>
      <td>number/string</td>
      <td>yes</td>
      <td>prediction interval upper bound</td>
    </tr>
  </tbody>
</table>


`HeterogeneitySummary` follows the schema defined in Subgroup Estimate Calculation.

输出约束：

- 只有 `AnalysisSetting.subgroup` 为空的 setting 才生成 `OverallEstimate`。
- `AnalysisSetting.subgroup.factor` 和 `AnalysisSetting.subgroup.level` 必须均为空。
- 每个 overall `AnalysisSetting` 最多生成一个 `OverallEstimate`。
- `setting_family_id` 必须来自对应 `AnalysisSetting.setting_family_id`。
- `included_study_ids` 必须来自 `analysis_method.analysis_included_study_ids`，并且必须能在 `study_result_rows` 中找到对应 extracted rows。
- `study_count = len(included_study_ids)`。
- `participant_count` 为所有 included rows 的 `experimental_total + control_total` 之和。
- `method_id`、`effect_measure`、`analysis_model`、`statistical_method` 和 `ci_level` 来自 Analysis Model Decision 子任务。
- 当 `estimation_status = computed` 时，`effect_value`、`ci_lower` 和 `ci_upper` 必须存在。
- `prediction_interval` 是 optional/conditional 结果字段；主要适用于 `analysis_model = random_effects` 的 overall estimate，可在未计算、不适用或数据不足时为空。
- 当 `estimation_status = computed` 且 `study_count >= 2` 时，`heterogeneity` 通常应输出；若统计量不适用、未计算或不可计算，可为空或部分为空。
- 如果 `analysis_method.method_status != ready`，`estimation_status` 不能为 `computed`。
- 如果可用 study 数不足以计算 overall estimate，应输出 `estimation_status = insufficient_data`。
- 本模块不输出 GRADE certainty。


## 8. Module 7: Four-domain GRADE Assessment

### 8.1 Task Definition

Module task unit:

```text
one review / one clinical question
```

Assessment unit:

```text
one analysis setting / one evidence body
```

Four-domain GRADE Assessment 负责基于当前 review/question context 和上游 workflow 产物，对每个 selected SoF row 对应的 evidence body 生成四个 GRADE downgrade domain judgements。

当前可复现 GRADE benchmark 版本为 `grade_v4`。该版本仍以 Module 6 的 `MetaAnalysisResultPackage` 作为正式上游输入；benchmark 构建时如需复用 Meta Analysis 的 row universe 和 setting cleaning，必须通过 GRADE 私有 workflow root 生成，不直接读取或改写 Meta Analysis 主构建中间产物。旧 `grade_v3` 及其衍生数据仅作为本地历史归档保留，不属于当前 benchmark 数据集。

当前模块覆盖四个 GRADE downgrade domains：

- `risk_of_bias`
- `inconsistency`
- `indirectness`
- `imprecision`

该模块与官方 GRADE / Cochrane 的基本粒度保持一致：GRADE 判断作用于某个 outcome/setting 对应的 body of evidence，而不是单篇 study，也不是整个 review 的单一判断。当前 workflow 只处理 RCT evidence，因此每个 evidence body 的初始 certainty 可视为 high；本模块只输出四个 downgrade domain 的 judgement，不输出 publication bias，不输出 final five-domain overall certainty。当前 v1 输出对象为 SoF row，但每个 SoF row 必须严格 1:1 对应一个 selected `AnalysisSetting / evidence body`，不做 multi-setting row merge。

当前 workflow 中，Four-domain GRADE Assessment 仅作用于已形成 meta-analysis effect estimate 的 analysis setting / evidence body；未形成 effect estimate 的 setting 不进入当前版本的正式 GRADE judgement 输出范围。SoF row 是最终输出包装对象，evidence body 的内部构造仍基于 selected `AnalysisSetting` 和 matched effect estimate。

四个 domain 是并行任务。它们共享相同的 review/question context、analysis setting 和 evidence body，但每个 domain 消费的上游字段不同。

### 8.2 Input

Module-level input:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Source</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>review_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>workflow</td>
      <td>current review/question ID</td>
    </tr>
    <tr>
      <td><code>question_text</code></td>
      <td>string</td>
      <td>yes</td>
      <td>Module 1: Q2PICO / workflow</td>
      <td>current clinical question</td>
    </tr>
    <tr>
      <td><code>question_pico</code></td>
      <td>QuestionPICO</td>
      <td>yes</td>
      <td>Module 1: Q2PICO</td>
      <td>review/question-level target PICO；内部字段为 <code>P/I/C/O</code></td>
    </tr>
    <tr>
      <td><code>screening_criteria</code></td>
      <td>ScreeningCriteria?</td>
      <td>no</td>
      <td>Module 3: Study Screening</td>
      <td>当前问题的纳入/排除标准；indirectness 的辅助上下文，不作为必需输入</td>
    </tr>
    <tr>
      <td><code>study_characteristics</code></td>
      <td>list[StudyPIOCharacteristics]</td>
      <td>yes</td>
      <td>Module 4: Study-level PIO Characteristics Extraction</td>
      <td>included studies 的 study-level PIO characteristics；按 evidence body 的 <code>included_study_ids</code> 过滤后使用</td>
    </tr>
    <tr>
      <td><code>risk_of_bias</code></td>
      <td>list[RiskOfBiasAssessment]</td>
      <td>yes</td>
      <td>Module 5: Risk of Bias Assessment</td>
      <td>included RCT studies 的 study-level RoB judgements；按 evidence body 的 <code>included_study_ids</code> 过滤后使用</td>
    </tr>
    <tr>
      <td><code>meta_analysis_result</code></td>
      <td>MetaAnalysisResultPackage</td>
      <td>yes</td>
      <td>Module 6: Meta Analysis</td>
      <td>analysis settings、study result rows、subgroup estimates、overall estimates 和 subgroup difference tests</td>
    </tr>
  </tbody>
</table>


`meta_analysis_result` required fields:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>analysis_settings</code></td>
      <td>yes</td>
      <td>GRADE assessment 的 setting-level join unit</td>
    </tr>
    <tr>
      <td><code>overall_estimates</code></td>
      <td>yes</td>
      <td>overall settings 对应的 effect estimates</td>
    </tr>
    <tr>
      <td><code>subgroup_estimates</code></td>
      <td>yes</td>
      <td>subgroup-level settings 对应的 effect estimates；没有 subgroup analysis 时可为空 list</td>
    </tr>
    <tr>
      <td><code>subgroup_difference_tests</code></td>
      <td>yes</td>
      <td>同一 subgroup factor 下 sibling subgroup estimates 的差异检验；没有 subgroup analysis 或不可计算时可为空 list</td>
    </tr>
    <tr>
      <td><code>study_result_rows</code></td>
      <td>yes</td>
      <td>study-level result data；当前主要供 imprecision 判断事件数、样本量和数据稀疏性</td>
    </tr>
  </tbody>
</table>


Evidence body construction:

当前版本中，evidence body 的构造依赖 Module 6 已输出的 `OverallEstimate` 或 `SubgroupEstimate`。

1. 遍历 `meta_analysis_result.analysis_settings`，每个 `AnalysisSetting` 生成一个内部 evidence-body judgement 单元，并在当前 v1 中输出为一个严格 1:1 对应的 `SoFRowGRADEAssessment`。
2. 如果 `AnalysisSetting.subgroup.factor` 和 `AnalysisSetting.subgroup.level` 均为空，则匹配同一 `setting_id` 的 `OverallEstimate`。
3. 如果 `AnalysisSetting.subgroup` 非空，则匹配同一 `setting_id` 的 `SubgroupEstimate`。
4. 使用 matched estimate 的 `included_study_ids` 作为当前 evidence body 的 contributing studies。
5. 用 `included_study_ids` 过滤 `risk_of_bias` 和 `study_characteristics`；imprecision 需要时也用 `setting_id` 和 `included_study_ids` 过滤 `study_result_rows`。
6. 对同一 evidence body 并行生成四个 domain judgements。

Input constraints:

- `analysis_settings[*].setting_id` 是 Module 7 的主 join key。
- `effect_estimate` 不是独立上游输入字段，而是由 Module 7 从 `overall_estimates` 或 `subgroup_estimates` 中匹配得到。
- 如果某个 `AnalysisSetting` 找不到 matching estimate，则该 setting 默认不进入当前版本的正式 GRADE judgement 输出；如需保留记录，可输出非正式占位 assessment，并标记为 `not_evaluable`。
- Domain assessment 是 evidence-body level 判断，不是 single-study level 判断。
- 本模块不重新计算 meta-analysis，不重新判断 study screening，不重新抽取 RoB 或 study characteristics。
- 当前 v1 中，最终输出 SoF row 与 selected `AnalysisSetting / evidence body` 严格 1:1，对外不引入 table-level row assembly 或 multi-setting merge 规则。

### 8.3 Output

Module-level output `grade_result` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>review_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>review/question ID</td>
    </tr>
    <tr>
      <td><code>question_text</code></td>
      <td>string</td>
      <td>yes</td>
      <td>current clinical question</td>
    </tr>
    <tr>
      <td><code>sof_rows</code></td>
      <td>list[SoFRowGRADEAssessment]</td>
      <td>yes</td>
      <td>one GRADE assessment row per selected evidence body in current v1</td>
    </tr>
  </tbody>
</table>


`SoFRowGRADEAssessment` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>sof_row_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>stable SoF row identifier; current v1 may be derived deterministically from the selected <code>setting_id</code></td>
    </tr>
    <tr>
      <td><code>row_label</code></td>
      <td>string?</td>
      <td>no</td>
      <td>display-oriented row label for the current SoF row; may default to the selected setting outcome label in v1</td>
    </tr>
    <tr>
      <td><code>setting_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>selected Meta Analysis setting backing this SoF row</td>
    </tr>
    <tr>
      <td><code>setting_family_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>来源 <code>AnalysisSetting.setting_family_id</code></td>
    </tr>
    <tr>
      <td><code>candidate_id</code></td>
      <td>string</td>
      <td>yes</td>
      <td>来源 <code>AnalysisSetting.candidate_id</code></td>
    </tr>
    <tr>
      <td><code>comparison</code></td>
      <td>AnalysisComparison</td>
      <td>yes</td>
      <td>setting-level comparison</td>
    </tr>
    <tr>
      <td><code>outcome</code></td>
      <td>AnalysisOutcome</td>
      <td>yes</td>
      <td>setting-level outcome</td>
    </tr>
    <tr>
      <td><code>timepoint</code></td>
      <td>AnalysisTimepoint</td>
      <td>yes</td>
      <td>setting-level timepoint</td>
    </tr>
    <tr>
      <td><code>subgroup</code></td>
      <td>AnalysisSubgroup</td>
      <td>yes</td>
      <td>setting-level subgroup；overall evidence body 中 factor/level 为空</td>
    </tr>
    <tr>
      <td><code>effect_estimate_ref</code></td>
      <td>EffectEstimateRef</td>
      <td>yes</td>
      <td>当前 evidence body 对应的 <code>OverallEstimate</code> 或 <code>SubgroupEstimate</code> 引用</td>
    </tr>
    <tr>
      <td><code>included_study_ids</code></td>
      <td>list[string]</td>
      <td>yes</td>
      <td>studies contributing to this evidence body；来源 matched estimate 的 <code>included_study_ids</code></td>
    </tr>
    <tr>
      <td><code>domain_judgements</code></td>
      <td>DomainJudgements</td>
      <td>yes</td>
      <td>四个 GRADE downgrade domain judgements</td>
    </tr>
  </tbody>
</table>


`DomainJudgements` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>risk_of_bias</code></td>
      <td>GRADEDomainJudgement</td>
      <td>yes</td>
      <td>risk-of-bias downgrade judgement</td>
    </tr>
    <tr>
      <td><code>inconsistency</code></td>
      <td>GRADEDomainJudgement</td>
      <td>yes</td>
      <td>inconsistency downgrade judgement</td>
    </tr>
    <tr>
      <td><code>indirectness</code></td>
      <td>GRADEDomainJudgement</td>
      <td>yes</td>
      <td>indirectness downgrade judgement</td>
    </tr>
    <tr>
      <td><code>imprecision</code></td>
      <td>GRADEDomainJudgement</td>
      <td>yes</td>
      <td>imprecision downgrade judgement</td>
    </tr>
  </tbody>
</table>


`EffectEstimateRef` schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>estimate_type</code></td>
      <td>string</td>
      <td>yes</td>
      <td><code>overall</code> / <code>subgroup</code></td>
    </tr>
    <tr>
      <td><code>estimate_id</code></td>
      <td>string?</td>
      <td>conditional</td>
      <td><code>overall_estimate_id</code> 或 <code>subgroup_estimate_id</code>；找不到 matching estimate 时为空</td>
    </tr>
    <tr>
      <td><code>estimation_status</code></td>
      <td>string?</td>
      <td>no</td>
      <td>matching estimate 的 estimation status</td>
    </tr>
  </tbody>
</table>


`GRADEDomainJudgement` common schema:


<table>
  <thead>
    <tr>
      <th>Field</th>
      <th>Type</th>
      <th>Required</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>domain</code></td>
      <td>string</td>
      <td>yes</td>
      <td><code>risk_of_bias</code> / <code>inconsistency</code> / <code>indirectness</code> / <code>imprecision</code></td>
    </tr>
    <tr>
      <td><code>downgraded</code></td>
      <td>string</td>
      <td>yes</td>
      <td><code>yes</code> / <code>no</code> / <code>unclear</code></td>
    </tr>
    <tr>
      <td><code>severity</code></td>
      <td>string</td>
      <td>yes</td>
      <td><code>not_serious</code> / <code>serious</code> / <code>very_serious</code> / <code>unclear</code></td>
    </tr>
    <tr>
      <td><code>levels</code></td>
      <td>integer/string</td>
      <td>yes</td>
      <td><code>0</code> / <code>1</code> / <code>2</code> / <code>unclear</code></td>
    </tr>
    <tr>
      <td><code>level_evaluable</code></td>
      <td>boolean</td>
      <td>yes</td>
      <td>whether a concrete downgrade level can be judged from available upstream fields</td>
    </tr>
    <tr>
      <td><code>rationale</code></td>
      <td>string</td>
      <td>yes</td>
      <td>concise reason for the domain judgement</td>
    </tr>
    <tr>
      <td><code>source_spans</code></td>
      <td>list[string]?</td>
      <td>no</td>
      <td>supporting source spans if available</td>
    </tr>
  </tbody>
</table>


Output constraints:

- `sof_rows` 应覆盖每个当前版本可正式评估的 selected `AnalysisSetting`。
- `domain_judgements` 必须包含且只包含当前四个 domains。
- `severity = not_serious` 对应 `levels = 0` 且 `downgraded = no`。
- `severity = serious` 对应 `levels = 1` 且 `downgraded = yes`。
- `severity = very_serious` 对应 `levels = 2` 且 `downgraded = yes`。
- `severity = unclear` 时，`levels` 可为 `unclear`，`downgraded` 可为 `unclear`。
- 本模块不输出 publication bias judgement，也不输出 final overall certainty label。
- 当前 v1 中，一个 `sof_row_id` 只能对应一个 selected `setting_id`；本模块不在 row 层合并多个 settings。

### 8.4 Parallel Domain Tasks

For each `SoFRowGRADEAssessment`, the four GRADE domain judgements are generated in parallel.

Domain task definitions:


<table>
  <thead>
    <tr>
      <th>Domain</th>
      <th>Task Definition</th>
      <th>Output Field</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>risk_of_bias</code></td>
      <td>Judge whether the evidence body should be downgraded because contributing RCTs have important risk-of-bias concerns that may affect the setting-level evidence.</td>
      <td><code>domain_judgements.risk_of_bias</code></td>
    </tr>
    <tr>
      <td><code>inconsistency</code></td>
      <td>Judge whether the evidence body should be downgraded because study results are inconsistent and the inconsistency is not adequately explained.</td>
      <td><code>domain_judgements.inconsistency</code></td>
    </tr>
    <tr>
      <td><code>indirectness</code></td>
      <td>Judge whether the evidence body should be downgraded because the included studies, comparison, outcome, subgroup, or timepoint do not directly answer the target question.</td>
      <td><code>domain_judgements.indirectness</code></td>
    </tr>
    <tr>
      <td><code>imprecision</code></td>
      <td>Judge whether the evidence body should be downgraded because the effect estimate is too uncertain for the current setting-level decision.</td>
      <td><code>domain_judgements.imprecision</code></td>
    </tr>
  </tbody>
</table>


#### 8.4.1 Risk of Bias Domain

Input fields:


<table>
  <thead>
    <tr>
      <th>Input Object</th>
      <th>Required Fields / Filter</th>
      <th>Source</th>
      <th>Purpose</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>analysis_setting</code></td>
      <td>setting definition</td>
      <td>Module 6</td>
      <td>Defines the setting and outcome being judged.</td>
    </tr>
    <tr>
      <td><code>included_study_ids</code></td>
      <td>from matched estimate</td>
      <td>Module 6</td>
      <td>Defines contributing studies for the evidence body.</td>
    </tr>
    <tr>
      <td><code>risk_of_bias</code></td>
      <td>items filtered by <code>included_study_ids</code></td>
      <td>Module 5</td>
      <td>Main evidence for this domain.</td>
    </tr>
  </tbody>
</table>


Output field:

```text
domain_judgements.risk_of_bias: GRADEDomainJudgement
```

#### 8.4.2 Inconsistency Domain

Input fields:


<table>
  <thead>
    <tr>
      <th>Input Object</th>
      <th>Required Fields / Filter</th>
      <th>Source</th>
      <th>Purpose</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>analysis_setting</code></td>
      <td>setting definition</td>
      <td>Module 6</td>
      <td>Defines whether the judgement is overall or subgroup-level.</td>
    </tr>
    <tr>
      <td><code>effect_estimate</code></td>
      <td><code>effect_value</code>, <code>ci_lower</code>, <code>ci_upper</code>, <code>heterogeneity</code>, <code>analysis_model</code>, <code>statistical_method</code></td>
      <td>Module 6</td>
      <td>Main quantitative evidence for inconsistency.</td>
    </tr>
    <tr>
      <td><code>subgroup_difference_tests</code></td>
      <td>matching <code>setting_family_id</code>, timepoint, data type, effect measure, and subgroup factor when applicable</td>
      <td>Module 6</td>
      <td>Helps judge whether subgroup structure explains inconsistency.</td>
    </tr>
  </tbody>
</table>


Output field:

```text
domain_judgements.inconsistency: GRADEDomainJudgement
```

#### 8.4.3 Indirectness Domain

Input fields:


<table>
  <thead>
    <tr>
      <th>Input Object</th>
      <th>Required Fields / Filter</th>
      <th>Source</th>
      <th>Purpose</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>question_pico</code></td>
      <td><code>P/I/C/O</code></td>
      <td>Module 1</td>
      <td>Defines the target clinical question.</td>
    </tr>
    <tr>
      <td><code>analysis_setting</code></td>
      <td><code>population_scope</code>, comparison, outcome, timepoint, subgroup</td>
      <td>Module 6</td>
      <td>Defines the setting being judged for directness.</td>
    </tr>
    <tr>
      <td><code>included_study_ids</code></td>
      <td>from matched estimate</td>
      <td>Module 6</td>
      <td>Defines the studies contributing to the judged evidence body.</td>
    </tr>
    <tr>
      <td><code>study_characteristics</code></td>
      <td>items filtered by <code>included_study_ids</code></td>
      <td>Module 4</td>
      <td>Main study-level evidence for population/intervention/comparator/outcome/timepoint directness.</td>
    </tr>
    <tr>
      <td><code>screening_criteria</code></td>
      <td>optional context</td>
      <td>Module 3</td>
      <td>Auxiliary eligibility context when needed.</td>
    </tr>
  </tbody>
</table>


Output field:

```text
domain_judgements.indirectness: GRADEDomainJudgement
```

#### 8.4.4 Imprecision Domain

Input fields:


<table>
  <thead>
    <tr>
      <th>Input Object</th>
      <th>Required Fields / Filter</th>
      <th>Source</th>
      <th>Purpose</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>analysis_setting</code></td>
      <td>setting definition, data type, outcome, direction of benefit when available</td>
      <td>Module 6</td>
      <td>Defines what estimate is being judged and how to interpret direction.</td>
    </tr>
    <tr>
      <td><code>effect_estimate</code></td>
      <td><code>effect_value</code>, <code>ci_lower</code>, <code>ci_upper</code>, <code>effect_measure</code>, <code>ci_level</code>, <code>study_count</code>, <code>participant_count</code>, <code>prediction_interval</code> when available</td>
      <td>Module 6</td>
      <td>Main quantitative evidence for imprecision.</td>
    </tr>
    <tr>
      <td><code>study_result_rows</code></td>
      <td>rows filtered by <code>setting_id</code> and <code>included_study_ids</code></td>
      <td>Module 6</td>
      <td>Provides event counts, sample details, and raw result data needed for imprecision checks.</td>
    </tr>
  </tbody>
</table>


Output field:

```text
domain_judgements.imprecision: GRADEDomainJudgement
```
