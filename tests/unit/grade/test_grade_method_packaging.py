from __future__ import annotations

from pathlib import Path


def test_grade_concrete_methods_do_not_import_other_methods() -> None:
    grade_root = (
        Path(__file__).parents[3]
        / "backend/src/ebm_backend/online_pipeline/infrastructure/methods/grade"
    )
    for domain_root in path_directories(grade_root):
        method_roots = [path for path in path_directories(domain_root) if path.name.startswith("method_")]
        for method_root in method_roots:
            source = "\n".join(path.read_text(encoding="utf-8") for path in method_root.rglob("*.py"))
            for other_method_root in method_roots:
                if other_method_root != method_root:
                    forbidden = f".{domain_root.name}.{other_method_root.name}."
                    assert forbidden not in source


def test_grade_root_and_domain_roots_do_not_contain_shared_python_helpers() -> None:
    grade_root = (
        Path(__file__).parents[3]
        / "backend/src/ebm_backend/online_pipeline/infrastructure/methods/grade"
    )
    assert {path.name for path in grade_root.glob("*.py")} == {"__init__.py", "factory.py"}
    for domain_root in path_directories(grade_root):
        assert {path.name for path in domain_root.glob("*.py")} == {"__init__.py"}


def path_directories(root: Path) -> list[Path]:
    return sorted(path for path in root.iterdir() if path.is_dir() and path.name != "__pycache__")
