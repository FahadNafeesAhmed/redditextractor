"""Collect public, attributable discussion evidence from multiple source APIs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from pain_research.http import ApiClient
from pain_research.pipeline import DEFAULT_LOCAL_AI_TARGETS, collect_all, load_targets, write_collection


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface."""
    parser = argparse.ArgumentParser(description="Collect public discussion evidence for pain-point research.")
    parser.add_argument("--target-file", type=Path, help="JSON list of explicit targets; overrides the local-AI defaults.")
    parser.add_argument("--source", action="append", choices=["github", "discourse", "stackexchange", "hackernews"], help="Only run one or more source types.")
    parser.add_argument("--limit-per-target", type=int, default=50, help="Maximum threads, issues, questions, or comments per target.")
    parser.add_argument("--comments-per-thread", type=int, default=5, help="Maximum GitHub or Discourse replies per thread.")
    parser.add_argument("--min-request-interval", type=float, default=1.0, help="Minimum seconds between calls to the same host.")
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    parser.add_argument("--dry-run", action="store_true", help="Print the selected targets without contacting any provider.")
    return parser


def main() -> int:
    """Run collection and return a conventional process exit code."""
    args = build_parser().parse_args()
    if args.limit_per_target < 1 or args.comments_per_thread < 0 or args.min_request_interval < 0:
        raise SystemExit("Collection limits must be non-negative, with limit-per-target at least 1.")
    targets = load_targets(args.target_file) if args.target_file else DEFAULT_LOCAL_AI_TARGETS
    if args.source:
        targets = tuple(target for target in targets if target.source in set(args.source))
    if not targets:
        raise SystemExit("No targets selected.")
    if args.dry_run:
        print(json.dumps([{"source": item.source, "name": item.name, "config": item.config} for item in targets], indent=2))
        return 0
    client = ApiClient(min_interval=args.min_request_interval)
    items, failures = collect_all(
        targets,
        client=client,
        limit_per_target=args.limit_per_target,
        comments_per_thread=args.comments_per_thread,
        github_token=os.getenv("GITHUB_TOKEN"),
    )
    path = write_collection(args.output_dir, targets, items, failures)
    print(f"Collected {len(items)} attributable discussion units.")
    print(f"Failed targets: {len(failures)}")
    print(f"Audit file: {path}")
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
