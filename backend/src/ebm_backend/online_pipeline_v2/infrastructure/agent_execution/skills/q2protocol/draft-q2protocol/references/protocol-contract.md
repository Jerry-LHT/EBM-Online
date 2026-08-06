# Q2Protocol Scientific Contract

## Output Meaning

The output is a draft scientific and methodological Protocol for a Cochrane
intervention review. It is not editorial approval, registration, publication,
or evidence that any review activity has occurred.

Use the caller-supplied `protocol_version` as the draft's document version. It
is not a methodology selector.

## Required Structure

The fixed fields below are the stable clinical and methodological semantics.
Template headings and order belong to `document`; standard-specific concepts
that do not fit this core belong to typed `data_definitions` or `extensions`.
Do not change the meaning of a fixed field to imitate a template heading.

### Background

Explain:

- the condition or problem and who is affected;
- the intervention and relevant comparator context;
- how the intervention might work;
- the evidence gap and why the review is needed.

### Review Question, PICO, And Objectives

Define a single overall Review PICO and one or more objectives. Outcomes in the
Review PICO describe the scope of the review; the detailed outcome plan defines
priority, measurement, and timing.

### Eligibility

Define operational inclusion and exclusion rules for:

- study designs and design features;
- participants, diagnosis, age, setting, and relevant baseline restrictions;
- interventions, delivery, dose, duration, intensity, and co-interventions;
- comparators;
- setting, language, publication status, and date restrictions.

Do not make outcome reporting an inclusion condition unless explicitly
justified.

### Outcomes

Classify outcomes only as primary or secondary. Include at least one primary
outcome and, when relevant, both benefits and harms. For every outcome define:

- the construct and operational definition;
- acceptable measures or instruments;
- time points or time windows;
- rules for selecting or grouping multiple measures and time points.

### Search

Plan topic-appropriate sources. Ordinarily include CENTRAL and MEDLINE, Embase
when accessible, relevant trial registries, and justified supplementary
methods. State and justify language, date, publication-status, and format
limits.

Source-specific strategies are optional at Protocol drafting time. When one is
included, label its source and platform and treat it as a planned baseline,
not as the final executable query. Evidence Search develops, verifies,
executes, and preserves the final strategy for every applicable source.

For non-structured sources, provide an executable procedure rather than a
placeholder.

### Selection And Data Collection

Predefine title/abstract screening and full-report assessment. Describe how
eligibility decisions and disagreements will be handled. This task is an
automated Agent execution and must not claim that it provides independent
human review.

The unit of inclusion is a Study, not a paper. Plan to identify and collate
multiple Reports of the same Study, preserve report roles and provenance, and
avoid double counting.

Define piloted extraction or checking, data items, missing-information handling,
and collection of source-reported result forms without prematurely reducing
them to one analysis representation.

### Risk Of Bias

Use the caller-constrained risk-of-bias tool when supplied. Otherwise select an
official tool appropriate to the eligible study designs and intended
assessment level. Predefine independent assessment, disagreement resolution,
the selected tool's domains, support for judgements, and how judgements will
inform synthesis and interpretation.

Also predefine assessment of reporting bias or bias due to missing results.

### Analysis, Synthesis, And Certainty

Choose effect measures by anticipated result form. Address unit-of-analysis
issues, missing data, clinical/methodological/statistical heterogeneity, and
reporting bias.

Define each Synthesis PICO separately from the Review PICO. Each must state the
population, intervention, comparator, outcomes, time frames, study designs, and
grouping rules that determine which results may be synthesized together.

Predefine criteria for meta-analysis, model and variance choices where
defensible, non-meta synthesis, justified subgroup analyses, and sensitivity
analyses. Do not assume pairwise meta-analysis is always possible.

Use the caller-constrained certainty approach when supplied. Otherwise select
and justify an appropriate official certainty framework. Plan Summary of
Findings tables for the important comparisons and outcomes when required by
that framework.

## Excluded Content

Do not add equity, consumer involvement, authorship, funding, declarations,
acknowledgements, registration, publication, editorial approval, or AI
disclosure sections.

## Extensible Data

Use `data_definitions` when a Protocol defines a concept that downstream
selection, collection, analysis, or reporting must reference, such as an
intervention variant, outcome construct, timepoint, covariate, Synthesis PICO,
or planned analysis. Each definition and parent link must have a stable ID.

Use `extensions` only for applicable standard-specific semantics that are not
represented by the fixed core. Select the typed value kind, populate exactly
its corresponding value field, identify its namespace and scope, and link only
authorities present in `methodology_profile.authorities`. An extension adds
meaning; it must not override or contradict a fixed field.
