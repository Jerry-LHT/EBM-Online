"""Load deterministic tool callables from a bound repository Skill."""

from __future__ import annotations

from functools import lru_cache
import importlib.util
from pathlib import Path
from typing import Any, Callable, cast


SkillTool = Callable[[dict[str, Any]], dict[str, Any]]


def load_skill_tool(
    skill_path: Path,
    script_path: str,
    callable_name: str,
) -> SkillTool:
    """Load a callable while keeping physical Skill paths in Infrastructure."""
    resolved_skill = skill_path.expanduser().resolve()
    resolved_script = (resolved_skill / script_path).resolve()
    if not resolved_script.is_relative_to(resolved_skill):
        raise ValueError("Skill tool path must remain inside the Skill")
    return _load_skill_tool(str(resolved_script), callable_name)


@lru_cache(maxsize=None)
def _load_skill_tool(script_path: str, callable_name: str) -> SkillTool:
    path = Path(script_path)
    if not path.is_file():
        raise ValueError(f"Skill tool does not exist: {path}")
    module_name = f"_ebm_v2_skill_tool_{abs(hash((script_path, callable_name)))}"
    specification = importlib.util.spec_from_file_location(module_name, path)
    if specification is None or specification.loader is None:
        raise ValueError(f"Skill tool cannot be loaded: {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    value = getattr(module, callable_name, None)
    if not callable(value):
        raise ValueError(
            f"Skill tool callable {callable_name!r} does not exist: {path}"
        )
    return cast(SkillTool, value)
