# Calculation And Quality

Choose calculations from the Protocol, the reported data, and current
applicable statistical authority. The calculator supplies numeric execution;
it does not decide outcome meaning, direction, denominator, estimand,
population, or formula applicability.

Call `scripts/data_calculator.py` with an arithmetic expression, named decimal
inputs, and precision. Expressions may use arithmetic and the documented safe
numeric functions. Do not ask the model to supply an authoritative calculated
number without a calculator trace.

Every named input in the document must have an exact origin naming a numeric
source observation or an earlier calculation and its `output_name`. Constants
may appear in the expression. Bind representation values through stable
`value_id`, `observation_id`, and `calculation_id` relationships; do not encode
scientific provenance as a JSON path. Preserve the unrounded `exact` output. A
projection to an
integer RevMan field is valid only when the calculated value is integral.

Before finalization, check:

- every Selection-linked Report was attempted and no unlinked Report was used;
- each Study has source-supported Characteristics and Results state;
- arms, outcomes, time points, populations, and analysis populations were not
  silently merged;
- every RevMan numeric value has a unique `value_id` and one observed or
  calculated origin;
- every calculation can be replayed from its recorded inputs;
- result-specific denominators and events are plausible against the source;
- transformed magnitude, direction, and qualitative interpretation agree with
  the Report, allowing only documented legitimate differences.

These are professional self-checks. Backend validation checks structure,
references, arithmetic replay, and artifact integrity; it does not make the
clinical decisions above.
