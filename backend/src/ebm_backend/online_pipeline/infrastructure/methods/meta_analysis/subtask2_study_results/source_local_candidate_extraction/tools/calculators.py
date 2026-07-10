"""Deterministic calculators for targeted extraction."""

from __future__ import annotations

import ast
import math
import re
from typing import Any


def execute_calculation_plans(*, plans: list[dict[str, Any]], materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(material.get("material_id") or ""): material for material in materials}
    results: list[dict[str, Any]] = []
    for index, plan in enumerate(plans, start=1):
        if not isinstance(plan, dict):
            continue
        calculator = str(plan.get("calculator") or "").strip()
        target_field = str(plan.get("target_field") or "").strip()
        arguments = plan.get("arguments") if isinstance(plan.get("arguments"), dict) else {}
        material_inputs = {
            name: by_id.get(str(material_id or ""))
            for name, material_id in arguments.items()
            if str(material_id or "")
        }
        result = _execute_one(calculator=calculator, material_inputs=material_inputs, plan=plan)
        if result.get("status") == "calculated":
            validation = _validate_target_value(target_field=target_field, value=result.get("value"))
            if validation:
                result = _blocked(validation)
        results.append(
            {
                "plan_index": index,
                "target_field": target_field,
                "calculator": calculator,
                "arguments": arguments,
                "status": result["status"],
                "value": result.get("value"),
                "warnings": result.get("warnings") or [],
                "trace": {
                    "formula": result.get("formula"),
                    "input_values": {
                        name: _material_numeric_value(material)
                        for name, material in material_inputs.items()
                        if material is not None
                    },
                    "input_material_ids": {
                        name: material.get("material_id")
                        for name, material in material_inputs.items()
                        if material is not None
                    },
                    "rationale": plan.get("rationale"),
                },
            }
        )
    return results


def _execute_one(
    *,
    calculator: str,
    material_inputs: dict[str, dict[str, Any] | None],
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if calculator == "derive_events_from_percent_total":
        total = _material_numeric_value(material_inputs.get("total"))
        percent = _material_numeric_value(material_inputs.get("percent"))
        if total is None or percent is None:
            return _blocked("missing_total_or_percent")
        return _ok(_round_count(total * percent / 100.0), "events = round(total * percent / 100)")
    if calculator == "derive_total_from_events_percent":
        events = _material_numeric_value(material_inputs.get("events"))
        percent = _material_numeric_value(material_inputs.get("percent"))
        if events is None or percent in {None, 0}:
            return _blocked("missing_events_or_percent")
        return _ok(_round_count(events * 100.0 / percent), "total = round(events * 100 / percent)")
    if calculator == "derive_events_from_total_non_events":
        total = _material_numeric_value(material_inputs.get("total"))
        non_events = _material_numeric_value(material_inputs.get("non_events"))
        if total is None or non_events is None:
            return _blocked("missing_total_or_non_events")
        return _ok(_round_count(total - non_events), "events = total - non_events")
    if calculator == "derive_total_from_events_non_events":
        events = _material_numeric_value(material_inputs.get("events"))
        non_events = _material_numeric_value(material_inputs.get("non_events"))
        if events is None or non_events is None:
            return _blocked("missing_events_or_non_events")
        return _ok(_round_count(events + non_events), "total = events + non_events")
    if calculator == "derive_sd_from_se_n":
        se = _material_numeric_value(material_inputs.get("se"))
        n = _material_numeric_value(material_inputs.get("n"))
        if se is None or n is None or n <= 0:
            return _blocked("missing_se_or_n")
        return _ok(se * math.sqrt(n), "sd = se * sqrt(n)")
    if calculator == "derive_sd_from_ci_n":
        lower = _material_numeric_value(material_inputs.get("ci_lower"))
        upper = _material_numeric_value(material_inputs.get("ci_upper"))
        n = _material_numeric_value(material_inputs.get("n"))
        if lower is None or upper is None or n is None or n <= 0:
            return _blocked("missing_ci_or_n")
        return _ok(math.sqrt(n) * abs(upper - lower) / 3.92, "sd = sqrt(n) * abs(ci_upper - ci_lower) / 3.92")
    if calculator == "derive_se_from_ci":
        lower = _material_numeric_value(material_inputs.get("ci_lower"))
        upper = _material_numeric_value(material_inputs.get("ci_upper"))
        if lower is None or upper is None:
            return _blocked("missing_ci")
        return _ok(abs(upper - lower) / 3.92, "se = abs(ci_upper - ci_lower) / 3.92")
    if calculator == "generic_expression":
        return _execute_generic_expression(material_inputs=material_inputs, plan=plan or {})
    return _blocked(f"unsupported_calculator:{calculator or 'missing'}")


def _execute_generic_expression(
    *,
    material_inputs: dict[str, dict[str, Any] | None],
    plan: dict[str, Any],
) -> dict[str, Any]:
    confidence = str(plan.get("confidence") or "").strip().lower()
    if confidence != "high":
        return _blocked("generic_expression_requires_high_confidence")
    assumptions = plan.get("assumptions") or []
    if assumptions:
        return _blocked("generic_expression_requires_no_unchecked_assumptions")
    expression = str(plan.get("expression") or plan.get("generic_expression") or "").strip()
    if not expression:
        return _blocked("missing_generic_expression")
    if len(expression) > 300:
        return _blocked("generic_expression_too_long")
    values: dict[str, float] = {}
    for name, material in material_inputs.items():
        value = _material_numeric_value(material)
        if value is None:
            return _blocked(f"missing_numeric_variable:{name}")
        values[name] = value
    try:
        result = _safe_eval_expression(expression=expression, variables=values)
    except ValueError as exc:
        return _blocked(f"invalid_generic_expression:{exc}")
    return _ok(result, expression)


def _safe_eval_expression(*, expression: str, variables: dict[str, float]) -> float:
    tree = ast.parse(expression, mode="eval")
    allowed_functions = {
        "abs": abs,
        "sqrt": math.sqrt,
        "pow": pow,
        "round": round,
        "min": min,
        "max": max,
    }

    def evaluate(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise ValueError(f"unknown_variable:{node.id}")
            return float(variables[node.id])
        if isinstance(node, ast.UnaryOp):
            operand = evaluate(node.operand)
            if isinstance(node.op, ast.USub):
                return -operand
            if isinstance(node.op, ast.UAdd):
                return operand
        if isinstance(node, ast.BinOp):
            left = evaluate(node.left)
            right = evaluate(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                if right == 0:
                    raise ValueError("division_by_zero")
                return left / right
            if isinstance(node.op, ast.Pow):
                return left**right
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = allowed_functions.get(node.func.id)
            if fn is None:
                raise ValueError(f"unsupported_function:{node.func.id}")
            if node.keywords:
                raise ValueError("keyword_arguments_not_allowed")
            return float(fn(*[evaluate(arg) for arg in node.args]))
        raise ValueError(f"unsupported_expression_node:{type(node).__name__}")

    value = evaluate(tree)
    if not math.isfinite(value):
        raise ValueError("non_finite_result")
    return value


def _ok(value: float | int, formula: str) -> dict[str, Any]:
    if isinstance(value, float) and not math.isfinite(value):
        return _blocked("non_finite_result")
    return {"status": "calculated", "value": value, "formula": formula, "warnings": []}


def _validate_target_value(*, target_field: str, value: Any) -> str | None:
    number = _to_number(value)
    if number is None:
        return "non_numeric_result"
    if target_field.endswith("_events") or target_field.endswith("_total"):
        if number < 0:
            return "negative_count_result"
        rounded = _round_count(number)
        if abs(number - rounded) > 0.05:
            return "non_integer_count_result"
    if target_field.endswith("_sd") and number < 0:
        return "negative_sd_result"
    return None


def _blocked(reason: str) -> dict[str, Any]:
    return {"status": "blocked", "value": None, "formula": None, "warnings": [reason]}


def _round_count(value: float) -> int:
    return int(math.floor(value + 0.5))


def _material_numeric_value(material: dict[str, Any] | None) -> float | None:
    if not material:
        return None
    value = material.get("value")
    number = _to_number(value)
    if number is not None:
        return number
    return _to_number(material.get("value_text"))


def _to_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        if math.isfinite(float(value)):
            return float(value)
        return None
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None
