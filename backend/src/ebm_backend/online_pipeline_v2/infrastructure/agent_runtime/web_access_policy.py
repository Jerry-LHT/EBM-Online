"""Hidden blacklist policy and deterministic audit for Agent web access."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
from urllib.parse import unquote, urlsplit, urlunsplit


_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_POLICY_FIELDS = frozenset(
    {"enabled", "blocked_urls", "blocked_domains", "blocked_identifiers"}
)


@dataclass(frozen=True, slots=True)
class WebAccessPolicy:
    """Runtime-side targets that an Agent must not search, access, or cite."""

    enabled: bool = True
    blocked_urls: tuple[str, ...] = ()
    blocked_domains: tuple[str, ...] = ()
    blocked_identifiers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        urls = tuple(
            _canonical_url(value)
            for value in self.blocked_urls
            if value.strip()
        )
        domains = tuple(
            _normalize_domain(value)
            for value in self.blocked_domains
            if value.strip()
        )
        identifiers = tuple(
            value.strip().casefold()
            for value in self.blocked_identifiers
            if value.strip()
        )
        if len(set(urls)) != len(urls):
            raise ValueError("blocked_urls must not contain duplicates")
        if len(set(domains)) != len(domains):
            raise ValueError("blocked_domains must not contain duplicates")
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("blocked_identifiers must not contain duplicates")
        object.__setattr__(self, "blocked_urls", urls)
        object.__setattr__(self, "blocked_domains", domains)
        object.__setattr__(self, "blocked_identifiers", identifiers)


@dataclass(frozen=True, slots=True)
class WebPolicyViolation:
    source: str
    match_type: str
    rule_digest: str
    observed_digest: str


@dataclass(frozen=True, slots=True)
class WebAccessAudit:
    enabled: bool
    potential_contamination: bool
    inspected_value_count: int
    violations: tuple[WebPolicyViolation, ...]


def load_web_access_policy(
    path: str | Path | None = None,
) -> WebAccessPolicy:
    """Load a hidden runtime policy without staging it for the Agent."""
    raw_path = path or os.getenv("AGENT_WEB_POLICY_PATH")
    if raw_path is None:
        return WebAccessPolicy()
    resolved = Path(raw_path).expanduser()
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Missing Agent web policy: {resolved}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Agent web policy is not valid JSON: {resolved}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError("Agent web policy must be a JSON object")
    unknown = sorted(set(payload).difference(_POLICY_FIELDS))
    if unknown:
        raise ValueError(
            "Agent web policy contains unsupported fields: "
            f"{', '.join(unknown)}"
        )
    enabled = payload.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("Agent web policy enabled must be a boolean")
    return WebAccessPolicy(
        enabled=enabled,
        blocked_urls=_string_list(payload, "blocked_urls"),
        blocked_domains=_string_list(payload, "blocked_domains"),
        blocked_identifiers=_string_list(payload, "blocked_identifiers"),
    )


def audit_web_access(
    policy: WebAccessPolicy,
    *,
    events: Iterable[tuple[str, Mapping[str, Any]]],
    output: Mapping[str, Any],
    stderr: str = "",
) -> WebAccessAudit:
    """Inspect provider events and final output without exposing hidden rules."""
    if not policy.enabled:
        return WebAccessAudit(
            enabled=False,
            potential_contamination=False,
            inspected_value_count=0,
            violations=(),
        )

    inspected = 0
    violations: list[WebPolicyViolation] = []
    seen: set[tuple[str, str, str, str]] = set()
    sources: list[tuple[str, Any]] = [
        (f"event:{event_type}", payload)
        for event_type, payload in events
    ]
    sources.append(("final_output", output))
    if stderr:
        sources.append(("stderr", stderr))

    for source, value in sources:
        for text in _string_values(value):
            inspected += 1
            decoded = unquote(text)
            _inspect_identifiers(
                decoded,
                source=source,
                policy=policy,
                violations=violations,
                seen=seen,
            )
            _inspect_urls(
                decoded,
                source=source,
                policy=policy,
                violations=violations,
                seen=seen,
            )

    return WebAccessAudit(
        enabled=True,
        potential_contamination=bool(violations),
        inspected_value_count=inspected,
        violations=tuple(violations),
    )


def _inspect_identifiers(
    text: str,
    *,
    source: str,
    policy: WebAccessPolicy,
    violations: list[WebPolicyViolation],
    seen: set[tuple[str, str, str, str]],
) -> None:
    normalized = text.casefold()
    for identifier in policy.blocked_identifiers:
        if identifier in normalized:
            _record(
                source=source,
                match_type="blocked_identifier",
                rule=identifier,
                observed=text,
                violations=violations,
                seen=seen,
            )


def _inspect_urls(
    text: str,
    *,
    source: str,
    policy: WebAccessPolicy,
    violations: list[WebPolicyViolation],
    seen: set[tuple[str, str, str, str]],
) -> None:
    for match in _URL_PATTERN.finditer(text):
        observed = match.group(0).rstrip(".,;:!?)]}")
        try:
            canonical = _canonical_url(observed)
        except ValueError:
            continue
        host = urlsplit(canonical).hostname or ""
        for blocked_url in policy.blocked_urls:
            if canonical == blocked_url:
                _record(
                    source=source,
                    match_type="blocked_url",
                    rule=blocked_url,
                    observed=canonical,
                    violations=violations,
                    seen=seen,
                )
        for blocked_domain in policy.blocked_domains:
            if host == blocked_domain or host.endswith(f".{blocked_domain}"):
                _record(
                    source=source,
                    match_type="blocked_domain",
                    rule=blocked_domain,
                    observed=canonical,
                    violations=violations,
                    seen=seen,
                )


def _record(
    *,
    source: str,
    match_type: str,
    rule: str,
    observed: str,
    violations: list[WebPolicyViolation],
    seen: set[tuple[str, str, str, str]],
) -> None:
    key = (source, match_type, _digest(rule), _digest(observed))
    if key in seen:
        return
    seen.add(key)
    violations.append(
        WebPolicyViolation(
            source=source,
            match_type=match_type,
            rule_digest=key[2],
            observed_digest=key[3],
        )
    )


def _string_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _string_values(key)
            yield from _string_values(item)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _string_values(item)


def _canonical_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"blocked URL must be absolute HTTP(S): {value!r}")
    scheme = parsed.scheme.casefold()
    host = parsed.hostname.casefold().rstrip(".")
    port = parsed.port
    if port is not None and not (
        (scheme == "http" and port == 80)
        or (scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    path = unquote(parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, host, path, "", ""))


def _normalize_domain(value: str) -> str:
    candidate = value.strip().casefold().rstrip(".")
    if "://" in candidate:
        parsed = urlsplit(candidate)
        candidate = (parsed.hostname or "").casefold().rstrip(".")
    if not candidate or "/" in candidate or " " in candidate:
        raise ValueError(f"blocked domain is invalid: {value!r}")
    return candidate


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _string_list(payload: Mapping[str, Any], field_name: str) -> tuple[str, ...]:
    value = payload.get(field_name, [])
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise ValueError(f"Agent web policy {field_name} must be a string array")
    return tuple(value)
