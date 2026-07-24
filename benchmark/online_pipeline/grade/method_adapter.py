"""Benchmark-side selection for explicit GRADE domain adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class GradeDomainBenchmarkMethod:
    domain: str
    method: Any

    @property
    def domain_methods(self) -> dict[str, Any]:
        return {self.domain: self.method}

    def run_instance(self, *, instance: dict[str, Any]) -> dict[str, Any]:
        judgement = self.method.run(
            domain_evidence=_dict_value(instance.get("domain_evidence")),
            evidence_body=_dict_value(instance.get("evidence_body")),
        )
        return {
            "instance_id": instance.get("instance_id"),
            "sof_row_id": instance.get("sof_row_id"),
            "review_id": instance.get("review_id"),
            "domain": self.domain,
            "judgement": judgement,
        }

    def run_batch_instances(self, *, method_instances: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not hasattr(self.method, "run_batch_instances"):
            raise TypeError(f"GRADE {self.domain} method does not support batch execution")
        return self.method.run_batch_instances(method_instances=method_instances)


def load_grade_domain_benchmark_method(domain: str, method_spec: str) -> GradeDomainBenchmarkMethod:
    method_name = _domain_method_name(domain=domain, method_spec=method_spec)
    builder = _builders().get(domain, {}).get(method_name)
    if builder is None:
        raise ValueError(f"Unknown GRADE benchmark method '{method_name}' for domain '{domain}'")
    return GradeDomainBenchmarkMethod(domain=domain, method=builder())


def load_grade_benchmark_method(method_spec: str) -> GradeDomainBenchmarkMethod:
    """Load only fully qualified ``grade.<domain>.<method>`` specifications."""
    parts = method_spec.split(".")
    if len(parts) != 3 or parts[0] != "grade":
        raise ValueError(
            "A domain is required; use grade.<domain>.<method> or the domain benchmark loader"
        )
    return load_grade_domain_benchmark_method(parts[1], parts[2])


def _builders() -> dict[str, dict[str, Callable[[], Any]]]:
    from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_deterministic.method import (
        build_method as build_imprecision_deterministic,
    )
    from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_llm_web.method import (
        build_method as build_imprecision_llm_web,
    )
    from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_deterministic.method import (
        build_method as build_inconsistency_deterministic,
    )
    from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_local_llm_profile.method import (
        build_method as build_inconsistency_local_llm_profile,
    )
    from ebm_backend.online_pipeline.infrastructure.methods.grade.risk_of_bias.method_deterministic.method import (
        build_method as build_risk_of_bias_deterministic,
    )
    from ebm_backend.online_pipeline.infrastructure.methods.grade.risk_of_bias.method_llm.method import (
        build_method as build_risk_of_bias_llm,
    )

    return {
        "risk_of_bias": {
            "method_llm": build_risk_of_bias_llm,
            "method_deterministic": build_risk_of_bias_deterministic,
            "method_test": build_risk_of_bias_deterministic,
        },
        "inconsistency": {
            "method_local_llm_profile": build_inconsistency_local_llm_profile,
            "method_deterministic": build_inconsistency_deterministic,
            "method_test": build_inconsistency_deterministic,
        },
        "imprecision": {
            "method_llm_web": build_imprecision_llm_web,
            "method_deterministic": build_imprecision_deterministic,
            "method_test": build_imprecision_deterministic,
        },
    }


def _domain_method_name(*, domain: str, method_spec: str) -> str:
    prefix = f"grade.{domain}."
    if method_spec.startswith(prefix):
        return method_spec.removeprefix(prefix)
    short_prefix = f"{domain}."
    if method_spec.startswith(short_prefix):
        return method_spec.removeprefix(short_prefix)
    return method_spec


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
