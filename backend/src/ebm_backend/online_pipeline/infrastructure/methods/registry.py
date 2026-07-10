"""Method registry for online pipeline module implementations."""

from __future__ import annotations

from importlib import import_module
from typing import Any


_MODULE_PACKAGE = {
    "q2pico": "q2pico",
    "search_retrieval": "search_retrieval",
    "search_retrieval_mesh_mapping": "search_retrieval.mesh_mapping",
    "search_retrieval_textword_expansion": "search_retrieval.textword_expansion",
    "study_screening": "study_screening",
    "study_pio": "study_pio",
    "study_pio_extraction": "study_pio",
    "risk_of_bias": "risk_of_bias",
    "meta_analysis": "meta_analysis",
    "grade": "grade",
    "grade_assessment": "grade",
}

_PLACEHOLDER_MODULES = {
}


def get_module_method(module_name: str, method_name: str) -> Any:
    """Load and instantiate a method implementation for one workflow module."""
    if not method_name:
        raise ValueError("method_name is required")

    if module_name in _PLACEHOLDER_MODULES:
        raise NotImplementedError(_PLACEHOLDER_MODULES[module_name])

    package_name = _MODULE_PACKAGE.get(module_name)
    if package_name is None:
        valid = ", ".join(sorted(_MODULE_PACKAGE))
        raise ValueError(f"Unknown online pipeline module '{module_name}'. Valid modules: {valid}")

    if package_name == "grade":
        return _build_grade_method(method_name)
    if package_name == "meta_analysis":
        return _build_meta_analysis_method(method_name)
    if package_name == "q2pico":
        return _build_q2pico_method(method_name)
    if package_name == "study_screening":
        return _build_study_screening_method(method_name)

    module_path = f"ebm_backend.online_pipeline.infrastructure.methods.{package_name}.{method_name}.method"
    try:
        module = import_module(module_path)
    except ModuleNotFoundError as exc:
        raise ValueError(f"Unknown method '{method_name}' for module '{module_name}'") from exc

    if hasattr(module, "build_method"):
        return module.build_method()
    raise ValueError(f"Method module '{module_path}' must define build_method()")


def _build_q2pico_method(method_name: str) -> Any:
    if method_name != "default":
        raise ValueError(f"Unknown method '{method_name}' for module 'q2pico'")
    module_path = "ebm_backend.online_pipeline.infrastructure.methods.q2pico.method"
    try:
        module = import_module(module_path)
    except ModuleNotFoundError as exc:
        raise ValueError("Unknown Q2PICO module coordinator") from exc
    if hasattr(module, "build_method"):
        return module.build_method()
    raise ValueError(f"Method module '{module_path}' must define build_method()")


def _build_study_screening_method(method_name: str) -> Any:
    if method_name != "default":
        raise ValueError(f"Unknown method '{method_name}' for module 'study_screening'")
    module_path = "ebm_backend.online_pipeline.infrastructure.methods.study_screening.method"
    try:
        module = import_module(module_path)
    except ModuleNotFoundError as exc:
        raise ValueError("Unknown Study Screening module coordinator") from exc
    if hasattr(module, "build_method"):
        return module.build_method()
    raise ValueError(f"Method module '{module_path}' must define build_method()")

def _build_grade_method(method_name: str) -> Any:
    module_path = "ebm_backend.online_pipeline.infrastructure.methods.grade.method"
    try:
        module = import_module(module_path)
    except ModuleNotFoundError as exc:
        raise ValueError("Unknown GRADE module coordinator") from exc
    if hasattr(module, "build_method"):
        return module.build_method(method_name)
    raise ValueError(f"Method module '{module_path}' must define build_method()")


def _build_meta_analysis_method(method_name: str) -> Any:
    module_path = "ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.method"
    try:
        module = import_module(module_path)
    except ModuleNotFoundError as exc:
        raise ValueError("Unknown Meta Analysis module coordinator") from exc
    if hasattr(module, "build_method"):
        return module.build_method(method_name)
    raise ValueError(f"Method module '{module_path}' must define build_method()")
