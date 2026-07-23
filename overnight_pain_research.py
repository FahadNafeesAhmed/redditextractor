"""Run durable, rate-limited multi-source collection and recurrence validation."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from pain_research.http import ApiClient
from pain_research.overnight import AlreadyRunningError, DurableStore, analyze_pending, build_report, collect_cycles
from pain_research.pipeline import DEFAULT_LOCAL_AI_TARGETS, load_targets


def parser() -> argparse.ArgumentParser:
    """Build the overnight runner CLI."""
    result = argparse.ArgumentParser(description="Durable multi-source pain research with automatic validation.")
    result.add_argument("--target-file", type=Path, help="Explicit JSON target list; overrides the local-AI defaults.")
    result.add_argument("--source", action="append", choices=["github", "discourse", "stackexchange", "hackernews"])
    result.add_argument("--limit-per-target", type=int, default=20)
    result.add_argument("--comments-per-thread", type=int, default=3)
    result.add_argument("--cycles", type=int, default=1, help="Collection cycles before final validation.")
    result.add_argument("--interval-minutes", type=float, default=120.0, help="Wait between collection cycles.")
    result.add_argument("--min-request-interval", type=float, default=1.5)
    result.add_argument("--state-dir", type=Path, default=Path("reports") / "overnight_state")
    result.add_argument("--output-dir", type=Path, default=Path("reports"))
    result.add_argument("--server-url", default="http://127.0.0.1:8080/v1/chat/completions")
    result.add_argument("--timeout", type=int, default=90)
    result.add_argument("--wait-for-server", type=int, default=600)
    result.add_argument("--skip-server-health-check", action="store_true")
    result.add_argument("--min-evidence", type=int, default=3)
    result.add_argument("--min-authors", type=int, default=3)
    result.add_argument("--min-threads", type=int, default=2)
    result.add_argument("--max-groups-per-merge", type=int, default=30)
    return result


def main(argv: list[str] | None = None) -> int:
    """Collect durably, analyze pending items, and write one final report."""
    args = parser().parse_args(argv)
    positive_values = (args.limit_per_target, args.cycles, args.timeout, args.wait_for_server, args.min_evidence, args.min_authors, args.min_threads, args.max_groups_per_merge)
    if min(positive_values) < 1 or args.comments_per_thread < 0 or args.interval_minutes < 0 or args.min_request_interval < 0:
        raise SystemExit("Invalid collection, validation, or scheduling value.")
    targets = load_targets(args.target_file) if args.target_file else DEFAULT_LOCAL_AI_TARGETS
    if args.source:
        targets = tuple(target for target in targets if target.source in set(args.source))
    if not targets:
        raise SystemExit("No targets selected.")
    store = DurableStore(args.state_dir)
    try:
        store.acquire_lock()
    except AlreadyRunningError as error:
        print(f"Already running: {error}", file=sys.stderr)
        return 3
    try:
        client = ApiClient(min_interval=args.min_request_interval)
        failures, new_items = collect_cycles(
            store,
            targets,
            client=client,
            limit_per_target=args.limit_per_target,
            comments_per_thread=args.comments_per_thread,
            cycles=args.cycles,
            interval_seconds=args.interval_minutes * 60,
            github_token=os.getenv("GITHUB_TOKEN"),
        )
        records, summary = analyze_pending(
            store,
            server_url=args.server_url,
            timeout=args.timeout,
            wait_for_server_seconds=args.wait_for_server,
            skip_server_health_check=args.skip_server_health_check,
        )
        policy = {"min_evidence": args.min_evidence, "min_authors": args.min_authors, "min_threads": args.min_threads}
        json_path, markdown_path, payload = build_report(
            store,
            records,
            summary,
            server_url=args.server_url,
            timeout=args.timeout,
            policy=policy,
            batch_size=args.max_groups_per_merge,
            output_dir=args.output_dir,
        )
        store.checkpoint("complete", new_items=new_items, failed_targets=failures, report=str(json_path))
        print(f"New source units: {new_items}")
        print(f"Failed targets: {len(failures)}")
        print(f"Validated clusters: {payload['summary']['validated_clusters']}")
        print(f"JSON report: {json_path}")
        print(f"Markdown report: {markdown_path}")
        return 0 if not failures else 2
    finally:
        store.release_lock()


if __name__ == "__main__":
    raise SystemExit(main())
