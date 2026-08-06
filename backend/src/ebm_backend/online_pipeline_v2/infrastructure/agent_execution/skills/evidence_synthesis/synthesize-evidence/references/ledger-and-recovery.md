# Document, quality gates, and recovery

Maintain `evidence-synthesis-document.v3` as the single resumable and final
professional document. Use `scripts/synthesis_work.py` to initialize, upsert an
Analysis, validate, and set status. Always pass the staged immutable binding to
status and validation commands; never validate a binding against a value read
back from the same document.

Each Analysis has a Protocol relationship and definition, compatibility
assessment, typed source-linked representations, included and excluded Study
contributions, scoped Risk-of-Bias references, limitations, and exactly one
disposition: meta-analysis, a named other synthesis method, justified
no-pooling, or no evidence.

Before completion verify:

- every identifiable Protocol-planned synthesis has an inspectable disposition,
  and each interpretation or post-hoc change is identified and justified;
- actual Study characteristics were considered before combining results;
- every representation value has a stable Study/Result/representation/value
  identity without losing the source observation or calculation;
- populations, interventions, comparators, outcomes, time points, designs,
  units, dependencies, and multiple arms were handled consistently and no
  participant was double-counted;
- settings follow the Protocol and consulted authority rather than observed
  effect direction or significance;
- every arithmetic or statistical value traces to one successful deterministic
  calculation with matching engine identity, inputs, outputs, digests, and
  projections;
- Risk of Bias is used at its supplied scope and never changes statistical
  weights;
- heterogeneity, planned subgroup and sensitivity analyses, reporting biases,
  robustness, unavailable evidence, and limitations are addressed where
  applicable;
- the document passes its checked JSON Schema and semantic validation, and all
  CSV bytes exactly project it.

Run `scripts/synthesis_finalize.py` to validate the document and write the
three stable CSV projections. Submit `outputs/synthesis/document.json`; do not
create a separate report or scientific sidecar.

For an `incomplete` or `blocked` result, the whole current document becomes the
atomic checkpoint. Resume only with the same immutable binding. A process crash
preserves the previous checkpoint. Completed artifacts are immutable;
corrections require successor work.
