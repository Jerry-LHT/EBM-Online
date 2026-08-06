#!/usr/bin/env python3
"""Safe deterministic decimal expression calculator for Study Data Collection."""

from __future__ import annotations

import argparse
import ast
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
import json
import math
from pathlib import Path
import tempfile
from typing import Any, Callable

from scipy.stats import norm, t


class CalculationError(ValueError):
    pass


def calculate(specification: dict[str, Any]) -> dict[str, Any]:
    expression = str(specification.get("expression", "")).strip()
    if not expression:
        raise CalculationError("expression must not be blank")
    raw_inputs = specification.get("inputs")
    if not isinstance(raw_inputs, dict) or not raw_inputs:
        raise CalculationError("inputs must be a non-empty object")
    precision = specification.get("precision", 34)
    if type(precision) is not int or not 16 <= precision <= 80:
        raise CalculationError("precision must be an integer between 16 and 80")
    inputs = {str(name): _decimal(value, str(name)) for name, value in raw_inputs.items()}
    if any(not name.isidentifier() or name.startswith("_") for name in inputs):
        raise CalculationError("input names must be public identifiers")
    with localcontext() as context:
        context.prec = precision
        value = _Evaluator(inputs, precision).evaluate(expression)
        if not value.is_finite():
            raise CalculationError("calculation result must be finite")
        exact = _canonical_decimal(value)
    numeric: int | float
    if value == value.to_integral_value():
        numeric = int(value)
    else:
        numeric = float(value)
        if not math.isfinite(numeric):
            raise CalculationError("calculation result cannot be represented numerically")
    canonical_inputs = {name: _canonical_decimal(value) for name, value in inputs.items()}
    canonical_request = {
        "expression": expression,
        "inputs": canonical_inputs,
        "precision": precision,
    }
    outputs = {"value": numeric, "exact": exact}
    return {
        **canonical_request,
        "outputs": outputs,
        "input_digest": _digest(canonical_request),
        "output_digest": _digest(outputs),
    }


class _Evaluator:
    def __init__(self, inputs: dict[str, Decimal], precision: int) -> None:
        self.inputs = inputs
        self.precision = precision
        self.nodes = 0

    def evaluate(self, expression: str) -> Decimal:
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise CalculationError("expression is invalid") from exc
        return self._visit(tree.body)

    def _visit(self, node: ast.AST) -> Decimal:
        self.nodes += 1
        if self.nodes > 256:
            raise CalculationError("expression is too complex")
        if isinstance(node, ast.Name):
            if node.id not in self.inputs:
                raise CalculationError(f"unknown input: {node.id}")
            return self.inputs[node.id]
        if isinstance(node, ast.Constant):
            if type(node.value) not in {int, float}:
                raise CalculationError("only numeric constants are allowed")
            return _decimal(str(node.value), "constant")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = self._visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp):
            left = self._visit(node.left)
            right = self._visit(node.right)
            operations: dict[type[ast.operator], Callable[[Decimal, Decimal], Decimal]] = {
                ast.Add: lambda a, b: a + b,
                ast.Sub: lambda a, b: a - b,
                ast.Mult: lambda a, b: a * b,
                ast.Div: lambda a, b: a / b,
                ast.Pow: lambda a, b: a.__pow__(b),
                ast.Mod: lambda a, b: a % b,
            }
            operation = operations.get(type(node.op))
            if operation is None:
                raise CalculationError("operator is not allowed")
            try:
                return operation(left, right)
            except (ArithmeticError, InvalidOperation) as exc:
                raise CalculationError("numeric operation failed") from exc
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.keywords:
                raise CalculationError("keyword arguments are not allowed")
            values = [self._visit(argument) for argument in node.args]
            return self._call(node.func.id, values)
        raise CalculationError("expression contains an unsupported construct")

    def _call(self, name: str, values: list[Decimal]) -> Decimal:
        if name in {"sqrt", "ln", "exp", "abs"}:
            if len(values) != 1:
                raise CalculationError(f"{name} requires one argument")
            value = values[0]
            try:
                return {
                    "sqrt": lambda: value.sqrt(),
                    "ln": lambda: value.ln(),
                    "exp": lambda: value.exp(),
                    "abs": lambda: abs(value),
                }[name]()
            except (ArithmeticError, InvalidOperation) as exc:
                raise CalculationError(f"{name} failed") from exc
        if name in {"min", "max"}:
            if not values:
                raise CalculationError(f"{name} requires arguments")
            return min(values) if name == "min" else max(values)
        if name == "normal_ppf":
            if len(values) != 1:
                raise CalculationError("normal_ppf requires one probability")
            result = float(norm.ppf(float(values[0])))
            return _decimal(result, name)
        if name == "t_ppf":
            if len(values) != 2:
                raise CalculationError("t_ppf requires probability and degrees of freedom")
            result = float(t.ppf(float(values[0]), float(values[1])))
            return _decimal(result, name)
        raise CalculationError(f"function is not allowed: {name}")


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool):
        raise CalculationError(f"{name} must be numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CalculationError(f"{name} must be numeric") from exc
    if not parsed.is_finite():
        raise CalculationError(f"{name} must be finite")
    return parsed


def _canonical_decimal(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def _digest(value: object) -> str:
    content = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"sha256:{sha256(content).hexdigest()}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    specification = json.loads(arguments.input.read_text(encoding="utf-8"))
    if not isinstance(specification, dict):
        raise CalculationError("input must be a JSON object")
    result = calculate(specification)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=arguments.output.parent,
        prefix=f".{arguments.output.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(arguments.output)


if __name__ == "__main__":
    main()
