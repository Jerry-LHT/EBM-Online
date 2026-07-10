"""CLI for freezing and building the Meta Analysis benchmark raw data."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from benchmark.online_pipeline.meta_analysis.builder import (
    DEFAULT_SEED,
    MODULE,
    SOURCE,
    build_dataset,
    build_raw,
    freeze_raw_snapshot,
)
from benchmark.online_pipeline.shared.building import RAW_DATA_DIR
from benchmark.online_pipeline.shared.analysis_settings.builder import build_grade_required_settings


DEFAULT_RAW_ROOT = RAW_DATA_DIR / MODULE
DEFAULT_DATASET_NAME = SOURCE


def _format_dataset_result(result: dict[str, object]) -> str:
    return str(result.get("dataset_dir") or result.get("dataset_dirs"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Meta Analysis raw data and benchmark datasets.")
    parser.add_argument("command", choices=("freeze-source", "build-shared-settings", "build-raw", "build-dataset", "all", "report"))
    parser.add_argument("--raw-root", default=str(DEFAULT_RAW_ROOT))
    parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument("--sample-size", type=int, default=None)
    parser.add_argument("--allow-deterministic-fallback", action="store_true")
    parser.add_argument("--shared-settings-root", default=None)
    parser.add_argument("--llm-config", default=None)
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--reviews", nargs="*", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-setting-failures", type=int, default=50)
    args = parser.parse_args()

    raw_root = Path(args.raw_root)
    if args.command == "freeze-source":
        result = freeze_raw_snapshot(raw_root=raw_root)
        print(raw_root / "source_manifest.json")
    elif args.command == "build-shared-settings":
        if not args.shared_settings_root:
            raise ValueError("--shared-settings-root is required for build-shared-settings")
        build_grade_required_settings(
            output_root=Path(args.shared_settings_root),
            meta_raw_root=raw_root,
            llm_config=args.llm_config,
            use_llm=args.use_llm,
            workers=args.workers,
            resume=args.resume,
            reviews=args.reviews,
            limit=args.limit,
            max_failures=args.max_setting_failures,
        )
        print(Path(args.shared_settings_root) / "cleaning_report.json")
    elif args.command == "build-raw":
        result = build_raw(
            raw_root=raw_root,
            allow_deterministic_fallback=args.allow_deterministic_fallback,
            shared_settings_root=args.shared_settings_root,
        )
        print(raw_root / "intermediate" / "raw_quality_report.json")
    elif args.command == "build-dataset":
        result = build_dataset(
            source=SOURCE,
            dataset_name=args.dataset_name,
            sample_size=args.sample_size,
            seed=args.seed,
            source_url=str(raw_root),
            allow_deterministic_fallback=args.allow_deterministic_fallback,
            shared_settings_root=args.shared_settings_root,
        )
        print(_format_dataset_result(result))
    elif args.command == "all":
        freeze_raw_snapshot(raw_root=raw_root)
        if args.shared_settings_root:
            build_grade_required_settings(
                output_root=Path(args.shared_settings_root),
                meta_raw_root=raw_root,
                llm_config=args.llm_config,
                use_llm=args.use_llm,
                workers=args.workers,
                resume=args.resume,
                reviews=args.reviews,
                limit=args.limit,
                max_failures=args.max_setting_failures,
            )
        build_raw(
            raw_root=raw_root,
            allow_deterministic_fallback=args.allow_deterministic_fallback,
            shared_settings_root=args.shared_settings_root,
        )
        result = build_dataset(
            source=SOURCE,
            dataset_name=args.dataset_name,
            sample_size=args.sample_size,
            seed=args.seed,
            source_url=str(raw_root),
            allow_deterministic_fallback=args.allow_deterministic_fallback,
            shared_settings_root=args.shared_settings_root,
        )
        print(_format_dataset_result(result))
    else:
        report_path = raw_root / "intermediate" / "raw_quality_report.json"
        if not report_path.exists():
            build_raw(
                raw_root=raw_root,
                allow_deterministic_fallback=args.allow_deterministic_fallback,
                shared_settings_root=args.shared_settings_root,
            )
        print(report_path)


if __name__ == "__main__":
    main()
