# Strategy Construction

## Build concepts

Start from the Review PICO and eligibility criteria. In a general
bibliographic database, ordinarily consider:

1. condition or population;
2. intervention;
3. eligible study design, when a validated source-specific filter is
   appropriate.

Do not automatically search comparator or outcome concepts. They are often
poorly represented in titles, abstracts, and indexing and can reduce
sensitivity. Use a different structure only when the topic and source require
it, and record the rationale.

## Expand each concept

Consider:

- official controlled-vocabulary headings and appropriate explosion;
- preferred names, synonyms, abbreviations, former names, and spelling
  variants;
- brand, generic, device, procedure, and class names where relevant;
- truncation, wildcards, proximity, phrases, and field restrictions supported
  by the actual platform.

Combine alternatives within a concept with `OR`, then combine concept sets
with `AND`. Use validated design filters where appropriate. Do not add
language, publication-status, date, or human restrictions unless the Protocol
requires and justifies them.

Apply source-specific filters only when supported by the Protocol and the
current official or primary authority consulted for that source.

## Translate by source and platform

Never paste Ovid syntax into PubMed or treat MEDLINE interfaces as
interchangeable. Re-check:

- controlled vocabulary and explode syntax;
- title, abstract, keyword, publication-type, and registry fields;
- adjacency and phrase behavior;
- truncation limits;
- Boolean precedence;
- date and language syntax;
- validated design filters.

Preserve the final query or procedure actually executed. Do not silently
rewrite the Protocol strategy itself.

## Check the strategy

Before execution, check alignment with the Protocol and eligibility criteria,
Boolean and proximity logic, subject headings, text words, spelling, fields,
syntax, filters, limits, and executable formatting. Treat literal formatting
artifacts, unsupported syntax, and an unresolved choice of platform as
problems to resolve before execution. Do not claim that unverified Protocol
text was executed. This is executor self-checking, not independent human peer
review or a PRESS peer review.

Search development may be iterative. Inspect syntax messages, translations,
counts, and sampled source observations. Revise the strategy when those
observations expose a material retrieval problem, without changing the
Protocol scope or eligibility criteria. Report a material departure from the
planned strategy in `issues`; minor source-required syntax normalization need
not be represented as a Protocol amendment. Use professional judgement to stop
when the strategy is coherent, executable, aligned with scope, and no inspected
observation exposes a material unresolved defect. Do not use a fixed iteration
count, hit-count target, or deterministic quality score.
