# Calculation capabilities and method decisions

Do not treat this calculator inventory as methodology or as a reason to select
a method. Select the method from the Protocol, the actual evidence structure,
and current directly applicable official or primary authority. Record that
decision before computation.

`scripts/meta_compute.py` currently provides validated calculations for:

- dichotomous risk ratio, odds ratio, and risk difference with fixed or random
  inverse-variance methods, fixed Mantel-Haenszel methods, and fixed Peto odds
  ratio;
- continuous mean difference and standardized mean difference with fixed or
  random inverse-variance methods;
- generic inverse-variance difference or log-ratio inputs supplied as an
  estimate with standard error or variance;
- O-E and V log odds-ratio or log-hazard-ratio inputs with fixed effect;
- Wald or HKSJ inference, optional prediction intervals, heterogeneity
  estimates and tests, subgroups, subgroup-difference tests, and supported
  tau-squared intervals.

The input contract validates counts, sample sizes, finite values, uncertainty,
and supported combinations. The successful result is
`meta-compute-output.v2` and includes `engine_id` and `engine_version`. Preserve
the complete request and response in one calculation trace and project every
used upstream scalar into that request.

The command returns a structured `meta-compute-error.v1` diagnostic for a
calculation error. Inspect its code and message, correct a genuine input or
method-encoding mistake, and retry. Do not alter valid source data merely to
make the tool accept it. When the required Protocol-consistent numerical method
is outside these capabilities, do not use model arithmetic or silently choose a
supported method. Record the limitation and safe next action as `incomplete`.

Non-statistical dispositions remain valid without the numerical stack. A tool
limitation alone is not a professional justification for no-pooling or for an
alternative synthesis method.
