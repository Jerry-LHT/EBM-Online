"""Shared task context for targeted extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExtractionContext:
    instance_id: str
    analysis_setting: dict[str, Any]
    target: dict[str, Any]
    study_id: str
    article: dict[str, Any]
    required_fields: list[str]

    @property
    def setting_id(self) -> str:
        return str(self.analysis_setting.get("setting_id") or self.target.get("setting_id") or "")

    @property
    def data_type(self) -> str:
        return str(self.analysis_setting.get("data_type") or self.target.get("data_type") or "")

    @property
    def extraction_hint(self) -> str | None:
        value = self.target.get("extraction_hint")
        text = " ".join(str(value).split()) if value else ""
        return text or None


def required_fields(data_type: Any) -> list[str]:
    if str(data_type).strip().lower() == "dichotomous":
        return ["experimental_events", "experimental_total", "control_events", "control_total"]
    return [
        "experimental_mean",
        "experimental_sd",
        "experimental_total",
        "control_mean",
        "control_sd",
        "control_total",
    ]


def study_result_tasks(instance: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = instance.get("study_result_tasks")
    if isinstance(tasks, list) and tasks:
        return [task for task in tasks if isinstance(task, dict)]
    targets = instance.get("study_result_targets")
    if isinstance(targets, list) and targets:
        return [target for target in targets if isinstance(target, dict)]
    setting = instance.get("analysis_setting") or {}
    setting_id = str(setting.get("setting_id") or instance.get("instance_id") or "setting")
    return [
        {
            "extraction_task_id": f"task::{setting_id}::{study_id}",
            "target_id": f"target::{setting_id}::{study_id}",
            "setting_id": setting_id,
            "study_id": str(study_id),
            "article_id": None,
        }
        for study_id in (instance.get("included_studies") or [])
    ]
