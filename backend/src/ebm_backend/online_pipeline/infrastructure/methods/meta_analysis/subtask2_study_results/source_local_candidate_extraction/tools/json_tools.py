"""JSON formatting helpers for prompt payloads."""

from __future__ import annotations

import json
from typing import Any


def prompt_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
