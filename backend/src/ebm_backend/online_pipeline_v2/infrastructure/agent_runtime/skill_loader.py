"""Validate and stage Agent Skills without modifying user installations."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil

import yaml

from .contracts import AgentProvider
from .errors import AgentSkillError


_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_MAX_SKILL_FILE_BYTES = 8 * 1024 * 1024
_MAX_SKILL_TOTAL_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SkillPackage:
    name: str
    description: str
    source_path: Path
    sha256: str


@dataclass(frozen=True, slots=True)
class StagedSkills:
    packages: tuple[SkillPackage, ...]
    claude_plugin_path: Path | None = None

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(package.name for package in self.packages)


def load_skill(path: str | Path) -> SkillPackage:
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise AgentSkillError(f"Skill directory does not exist: {root}")
    skill_file = root / "SKILL.md"
    if not skill_file.is_file():
        raise AgentSkillError(f"Skill is missing SKILL.md: {root}")
    if root.name.startswith(".") or not _SKILL_NAME_PATTERN.fullmatch(root.name):
        raise AgentSkillError(f"Skill directory name is invalid: {root.name!r}")
    _validate_tree(root)
    try:
        text = skill_file.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise AgentSkillError(f"SKILL.md must be UTF-8: {skill_file}") from exc
    metadata = _frontmatter(text, skill_file)
    name = str(metadata.get("name") or "").strip()
    description = str(metadata.get("description") or "").strip()
    if name != root.name:
        raise AgentSkillError(
            f"Skill frontmatter name {name!r} must match directory {root.name!r}"
        )
    if not description:
        raise AgentSkillError(
            f"Skill frontmatter description must not be blank: {skill_file}"
        )
    return SkillPackage(
        name=name,
        description=description,
        source_path=root,
        sha256=_tree_digest(root),
    )


def stage_skills(
    paths: tuple[Path, ...],
    *,
    workspace: Path,
    provider: AgentProvider,
) -> StagedSkills:
    packages = tuple(load_skill(path) for path in paths)
    names = tuple(package.name for package in packages)
    if len(set(names)) != len(names):
        raise AgentSkillError("Skill names must be unique within one run")

    if provider is AgentProvider.OPENAI:
        skill_root = workspace / ".agents" / "skills"
        skill_root.mkdir(parents=True, exist_ok=True)
        for package in packages:
            _copy_skill(package, skill_root / package.name)
        return StagedSkills(packages=packages)

    plugin_root = workspace / ".runtime" / "claude-skills"
    skill_root = plugin_root / "skills"
    manifest_root = plugin_root / ".claude-plugin"
    skill_root.mkdir(parents=True, exist_ok=True)
    manifest_root.mkdir(parents=True, exist_ok=True)
    for package in packages:
        _copy_skill(package, skill_root / package.name)
    manifest = {
        "name": "ebm-online-pipeline-v2-runtime-skills",
        "version": "0.0.0",
        "description": "Per-run staged Agent Skills for Online Pipeline v2",
    }
    (manifest_root / "plugin.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return StagedSkills(
        packages=packages,
        claude_plugin_path=plugin_root,
    )


def _copy_skill(package: SkillPackage, destination: Path) -> None:
    try:
        shutil.copytree(
            package.source_path,
            destination,
            ignore=_ignored_generated_entries,
        )
    except OSError as exc:
        raise AgentSkillError(f"Failed to stage Skill {package.name}: {exc}") from exc


def _frontmatter(text: str, skill_file: Path) -> dict[str, object]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise AgentSkillError(
            f"SKILL.md must start with YAML frontmatter: {skill_file}"
        )
    try:
        closing = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        )
    except StopIteration as exc:
        raise AgentSkillError(
            f"SKILL.md frontmatter is not closed: {skill_file}"
        ) from exc
    try:
        parsed = yaml.safe_load("\n".join(lines[1:closing]))
    except yaml.YAMLError as exc:
        raise AgentSkillError(
            f"SKILL.md frontmatter is invalid YAML: {skill_file}"
        ) from exc
    if not isinstance(parsed, dict):
        raise AgentSkillError(f"SKILL.md frontmatter must be a mapping: {skill_file}")
    return parsed


def _validate_tree(root: Path) -> None:
    total_bytes = 0
    for path in root.rglob("*"):
        if _is_generated_cache(path, root):
            continue
        if path.is_symlink():
            raise AgentSkillError(f"Skill must not contain symlinks: {path}")
        if not path.is_file():
            continue
        size = path.stat().st_size
        if size > _MAX_SKILL_FILE_BYTES:
            raise AgentSkillError(f"Skill file is too large: {path}")
        total_bytes += size
        if total_bytes > _MAX_SKILL_TOTAL_BYTES:
            raise AgentSkillError(f"Skill directory is too large: {root}")


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(
        (
            item
            for item in root.rglob("*")
            if item.is_file() and not _is_generated_cache(item, root)
        ),
        key=lambda item: item.relative_to(root).as_posix(),
    ):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _is_generated_cache(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}


def _ignored_generated_entries(directory: str, names: list[str]) -> set[str]:
    root = Path(directory)
    return {
        name
        for name in names
        if name == "__pycache__" or (root / name).suffix in {".pyc", ".pyo"}
    }
