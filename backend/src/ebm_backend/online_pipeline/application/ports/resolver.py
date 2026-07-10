"""Resolver port for concrete workflow methods."""

from __future__ import annotations

from typing import Protocol


class MethodResolverPort(Protocol):
    def resolve(self, *, module_name: str, method_name: str):
        ...
