"""Inspect and remove local Agent Runtime Debug Bundles.

Examples:
    python -m ebm_backend.online_pipeline_v2.infrastructure.agent_runtime.debug list
    python -m ebm_backend.online_pipeline_v2.infrastructure.agent_runtime.debug show RUN_ID
    python -m ebm_backend.online_pipeline_v2.infrastructure.agent_runtime.debug path RUN_ID
    python -m ebm_backend.online_pipeline_v2.infrastructure.agent_runtime.debug clean
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .debug_store import DebugBundleStore, default_debug_root
from .web_access_policy import WebAccessPolicy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect Agent debug bundles")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(
            os.getenv("AGENT_DEBUG_ROOT", str(default_debug_root()))
        ).expanduser(),
        help="debug bundle root (default: AGENT_DEBUG_ROOT or system temp)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list retained runs")
    show = commands.add_parser("show", help="show a run manifest")
    show.add_argument("run_id")
    path = commands.add_parser("path", help="print a run bundle path")
    path.add_argument("run_id")
    commands.add_parser("clean", help="remove all retained bundles")
    args = parser.parse_args(argv)

    store = DebugBundleStore(root=args.root, policy=WebAccessPolicy())
    if args.command == "list":
        for item in store.list():
            print(
                f"{item.get('run_id', '?')}\t"
                f"{item.get('status', '?')}\t"
                f"{item.get('bundle_path', '?')}"
            )
        return 0
    if args.command == "show":
        bundle = store.path(args.run_id)
        manifest = bundle / "manifest.json"
        print(manifest.read_text(encoding="utf-8"), end="")
        return 0
    if args.command == "path":
        print(store.path(args.run_id))
        return 0
    removed = store.clean()
    print(f"removed {removed} debug bundle(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
