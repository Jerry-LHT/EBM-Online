"""Prompt loading for the local LLM inconsistency method."""
from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


@lru_cache(maxsize=None)
def prompt_text(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8").rstrip("\n")
