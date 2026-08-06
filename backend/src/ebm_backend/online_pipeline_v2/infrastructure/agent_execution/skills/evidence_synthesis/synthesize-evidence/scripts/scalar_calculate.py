#!/usr/bin/env python3
"""Safe deterministic Decimal calculator for synthesis transformations."""

from __future__ import annotations

import argparse
import ast
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from typing import Any, Callable


ENGINE_ID = "ebm-decimal-expression"
ENGINE_VERSION = "scalar-calculate.v1"


class ScalarCalculationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def calculate(specification: dict[str, Any]) -> dict[str, Any]:
    expression = str(specification.get("expression", "")).strip()
    if not expression:
        raise ScalarCalculationError("missing_expression", "expression is required")
    raw_inputs = specification.get("inputs")
    if not isinstance(raw_inputs, dict) or not raw_inputs:
        raise ScalarCalculationError(
            "invalid_inputs",
            "inputs must be a non-empty object",
        )
    precision = specification.get("precision", 34)
    if type(precision) is not int or not 16 <= precision <= 80:
        raise ScalarCalculationError(
            "invalid_precision",
            "precision must be an integer from 16 through 80",
        )
    inputs = {
        str(name): _decimal(value, str(name)) for name, value in raw_inputs.items()
    }
    if any(not name.isidentifier() or name.startswith("_") for name in inputs):
        raise ScalarCalculationError(
            "invalid_input_name",
            "input names must be public identifiers",
        )
    with localcontext() as context:
        context.prec = precision
        value = _Evaluator(inputs).evaluate(expression)
        if not value.is_finite():
            raise ScalarCalculationError("non_finite_result", "result must be finite")
        exact = _canonical_decimal(value)
    canonical_input = {
        "expression": expression,
        "inputs": {name: _canonical_decimal(value) for name, value in inputs.items()},
        "precision": precision,
    }
    output_value = {"value": exact}
    return {
        "schema_version": "scalar-calculate-output.v1",
        "engine_id": ENGINE_ID,
        "engine_version": ENGINE_VERSION,
        **canonical_input,
        "outputs": output_value,
        "input_digest": _digest(canonical_input),
        "output_digest": _digest(output_value),
    }


class _Evaluator:
    def __init__(self, inputs: dict[str, Decimal]) -> None:
        self.inputs = inputs
        self.nodes = 0

    def evaluate(self, expression: str) -> Decimal:
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise ScalarCalculationError(
                "invalid_expression", "expression is invalid"
            ) from exc
        return self._visit(tree.body)

    def _visit(self, node: ast.AST) -> Decimal:
        self.nodes += 1
        if self.nodes > 256:
            raise ScalarCalculationError(
                "expression_too_complex", "expression is too complex"
            )
        if isinstance(node, ast.Name):
            if node.id not in self.inputs:
                raise ScalarCalculationError(
                    "unknown_input", f"unknown input: {node.id}"
                )
            return self.inputs[node.id]
        if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
            return _decimal(node.value, "constant")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = self._visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp):
            left = self._visit(node.left)
            right = self._visit(node.right)
            operations: dict[
                type[ast.operator], Callable[[Decimal, Decimal], Decimal]
            ] = {
                ast.Add: lambda a, b: a + b,
                ast.Sub: lambda a, b: a - b,
                ast.Mult: lambda a, b: a * b,
                ast.Div: lambda a, b: a / b,
                ast.Pow: lambda a, b: a.__pow__(b),
                ast.Mod: lambda a, b: a % b,
            }
            operation = operations.get(type(node.op))
            if operation is None:
                raise ScalarCalculationError(
                    "unsupported_operator", "operator is not allowed"
                )
            try:
                return operation(left, right)
            except (ArithmeticError, InvalidOperation) as exc:
                raise ScalarCalculationError(
                    "numeric_operation_failed", "numeric operation failed"
                ) from exc
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.keywords:
                raise ScalarCalculationError(
                    "invalid_call", "keyword arguments are not allowed"
                )
            values = [self._visit(argument) for argument in node.args]
            return self._call(node.func.id, values)
        raise ScalarCalculationError(
            "unsupported_expression",
            "expression contains an unsupported construct",
        )

    def _call(self, name: str, values: list[Decimal]) -> Decimal:
        if name in {"sqrt", "ln", "exp", "abs"}:
            if len(values) != 1:
                raise ScalarCalculationError(
                    "invalid_arguments", f"{name} requires one argument"
                )
            value = values[0]
            try:
                return {
                    "sqrt": value.sqrt,
                    "ln": value.ln,
                    "exp": value.exp,
                    "abs": lambda: abs(value),
                }[name]()
            except (ArithmeticError, InvalidOperation) as exc:
                raise ScalarCalculationError(
                    "numeric_operation_failed", f"{name} failed"
                ) from exc
        if name in {"min", "max"} and values:
            return min(values) if name == "min" else max(values)
        raise ScalarCalculationError(
            "unsupported_function", f"function is not allowed: {name}"
        )


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ScalarCalculationError("invalid_numeric_input", f"{name} must be numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ScalarCalculationError(
            "invalid_numeric_input", f"{name} must be numeric"
        ) from exc
    if not parsed.is_finite():
        raise ScalarCalculationError("invalid_numeric_input", f"{name} must be finite")
    return parsed


def _canonical_decimal(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _digest(value: object) -> str:
    content = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{sha256(content).hexdigest()}"


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        value = json.loads(arguments.input.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ScalarCalculationError("invalid_input", "input must be a JSON object")
        result = calculate(value)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result = {
            "schema_version": "scalar-calculate-error.v1",
            "status": "error",
            "engine_id": ENGINE_ID,
            "engine_version": ENGINE_VERSION,
            "error": {"code": "invalid_input_document", "message": str(exc)},
        }
        _write(arguments.output, result)
        raise SystemExit(2) from None
    except ScalarCalculationError as exc:
        result = {
            "schema_version": "scalar-calculate-error.v1",
            "status": "error",
            "engine_id": ENGINE_ID,
            "engine_version": ENGINE_VERSION,
            "error": {"code": exc.code, "message": str(exc)},
        }
        _write(arguments.output, result)
        raise SystemExit(2) from None
    _write(arguments.output, result)


if __name__ == "__main__":
    main()
