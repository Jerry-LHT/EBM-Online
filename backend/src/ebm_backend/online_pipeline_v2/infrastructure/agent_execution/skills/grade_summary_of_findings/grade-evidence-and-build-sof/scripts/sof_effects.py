#!/usr/bin/env python3
"""Calculate supported intervention risks from a baseline risk and effect."""

import argparse
import json


def treated_risk(measure: str, baseline: float, effect: float) -> float:
    if not 0 <= baseline <= 1:
        raise ValueError("baseline risk must be between zero and one")
    if measure == "RR":
        value = baseline * effect
    elif measure == "OR":
        value = effect * baseline / (1 - baseline + effect * baseline)
    elif measure == "RD":
        value = baseline + effect
    elif measure == "HR":
        value = 1 - (1 - baseline) ** effect
    else:
        raise ValueError("supported measures are RR, OR, RD, and HR")
    if not 0 <= value <= 1:
        raise ValueError("derived risk falls outside zero to one")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--measure", choices=("RR", "OR", "RD", "HR"), required=True)
    parser.add_argument("--baseline-risk", type=float, required=True)
    parser.add_argument("--estimate", type=float, required=True)
    parser.add_argument("--lower", type=float)
    parser.add_argument("--upper", type=float)
    parser.add_argument("--display-scale", type=float, default=1.0)
    args = parser.parse_args()
    if (args.lower is None) != (args.upper is None):
        raise ValueError("both confidence limits are required together")
    if args.display_scale <= 0:
        raise ValueError("display scale must be positive")
    intervention_risk = treated_risk(
        args.measure, args.baseline_risk, args.estimate
    )
    result = {
        "measure": args.measure,
        "baseline_risk": args.baseline_risk,
        "effect_estimate": args.estimate,
        "display_scale": args.display_scale,
        "comparator_effect": args.baseline_risk * args.display_scale,
        "intervention_effect": intervention_risk * args.display_scale,
        "absolute_difference": (
            intervention_risk - args.baseline_risk
        ) * args.display_scale,
        "calculation": "deterministic",
    }
    if args.lower is not None:
        risks = sorted(
            (
                treated_risk(args.measure, args.baseline_risk, args.lower),
                treated_risk(args.measure, args.baseline_risk, args.upper),
            )
        )
        result["confidence_interval_lower"] = risks[0] * args.display_scale
        result["confidence_interval_upper"] = risks[1] * args.display_scale
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
