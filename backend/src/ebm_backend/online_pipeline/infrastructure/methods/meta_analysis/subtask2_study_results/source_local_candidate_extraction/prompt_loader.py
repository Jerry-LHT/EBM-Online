"""Prompt template loader for targeted extraction."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


PROMPT_DIR = (Path(__file__).resolve().parent / "prompt_templates").resolve()


@lru_cache(maxsize=64)
def load_prompt(name: str) -> str:
    path = (PROMPT_DIR / name).resolve()
    if PROMPT_DIR not in path.parents:
        raise ValueError(f"Prompt template path escapes prompt directory: {name}")
    return path.read_text(encoding="utf-8")


def render_prompt(name: str, *, input_json: str) -> str:
    return load_prompt(name).replace("{{input_json}}", input_json)
