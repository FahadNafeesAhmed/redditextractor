"""Durable orchestration for unattended, evidence-based public-source research."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Any, Callable, Mapping

import requests

import validated_pain_point_miner as miner
from pain_research.adapters import adapter_for
from pain_research.http import ApiClient
from pain_research.models import EvidenceItem, Target


class AlreadyRunningError(RuntimeError):
    """The durable state directory is already owned by another process."""


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def fingerprint_item(item: EvidenceItem | Mapping[str, Any]) -> str:
    """Return a content-version fingerprint for cross-run deduplication."""
    value = item.as_dict() if isinstance(item, EvidenceItem) else dict(item)
    stable = {
        "source": value.get("source"),
        "source_id": value.get("source_id"),
        "updated_at": value.get("updated_at"),
        "title": value.get("title"),
        "text": value.get("text"),
    }
    encoded = json.dumps(stable, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class DurableStore:
    """Append-only state files with an atomic human-readable checkpoint."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.raw_path = state_dir / "collected_items.jsonl"
        self.analysis_path = state_dir / "analyzed_items.jsonl"
        self.checkpoint_path = state_dir / "checkpoint.json"
        self.lock_path = state_dir / "run.lock"
        self._raw_cache: dict[str, dict[str, Any]] | None = None
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def acquire_lock(self) -> None:
        """Acquire an exclusive run lock without deleting a possibly live lock."""
        try:
            descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            raise AlreadyRunningError(f"Another run owns {self.lock_path}. Review it before deleting the lock.") from error
        with os.fdopen(descriptor, "w", encoding="utf-8") as lock_file:
            json.dump({"pid": os.getpid(), "started_at": utc_now()}, lock_file)

    def release_lock(self) -> None:
        """Release only the lock created by this completed process."""
        self.lock_path.unlink(missing_ok=True)

    def append_raw(self, item: EvidenceItem) -> bool:
        """Persist an item once and return whether it was new."""
        fingerprint = fingerprint_item(item)
        items = self.raw_items()
        if fingerprint in items:
            return False
        raw_item = item.as_dict()
        self._append(self.raw_path, {"fingerprint": fingerprint, "collected_at": utc_now(), "item": raw_item})
        items[fingerprint] = raw_item
        return True

    def append_analysis(self, fingerprint: str, record: Mapping[str, Any]) -> None:
        """Persist an LLM analysis record before moving to the next item."""
        self._append(self.analysis_path, {"fingerprint": fingerprint, "analyzed_at": utc_now(), "record": dict(record)})

    def raw_items(self) -> dict[str, dict[str, Any]]:
        """Return the latest stored item for every source-content fingerprint."""
        if self._raw_cache is None:
            self._raw_cache = {entry["fingerprint"]: entry["item"] for entry in self._read(self.raw_path)}
        return self._raw_cache

    def analyses(self) -> dict[str, dict[str, Any]]:
        """Return the latest evidence record for every analyzed fingerprint."""
        return {entry["fingerprint"]: entry["record"] for entry in self._read(self.analysis_path)}

    def checkpoint(self, status: str, **details: Any) -> None:
        """Atomically publish progress for users and restarts to inspect."""
        payload = {"schema_version": 1, "updated_at": utc_now(), "status": status, **details}
        temporary_path = self.checkpoint_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary_path.replace(self.checkpoint_path)

    @staticmethod
    def _read(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        result = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                result.append(value)
        return result

    @staticmethod
    def _append(path: Path, payload: Mapping[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(payload, ensure_ascii=False) + "\n")
            output.flush()
            os.fsync(output.fileno())


def collect_cycles(
    store: DurableStore,
    targets: tuple[Target, ...],
    *,
    client: ApiClient,
    limit_per_target: int,
    comments_per_thread: int,
    cycles: int,
    interval_seconds: float,
    github_token: str | None = None,
    sleep_fn: Callable[[float], None] = sleep,
) -> tuple[list[dict[str, str]], int]:
    """Collect scheduled cycles, checkpointing every item and target transition."""
    failures: list[dict[str, str]] = []
    new_items = 0
    for cycle in range(1, cycles + 1):
        for target in targets:
            target_new = 0
            store.checkpoint("collecting", cycle=cycle, cycles=cycles, target=target.name, new_items=new_items)
            try:
                adapter = adapter_for(target.source, client, github_token)
                for item in adapter.collect(target, limit_per_target, comments_per_thread):
                    if store.append_raw(item):
                        new_items += 1
                        target_new += 1
                    store.checkpoint(
                        "collecting",
                        cycle=cycle,
                        cycles=cycles,
                        target=target.name,
                        target_new_items=target_new,
                        new_items=new_items,
                    )
            except Exception as error:
                failures.append({"cycle": str(cycle), "source": target.source, "target": target.name, "error": str(error)})
            store.checkpoint("target_complete", cycle=cycle, cycles=cycles, target=target.name, new_items=new_items)
        if cycle < cycles:
            store.checkpoint("waiting_for_next_cycle", cycle=cycle, cycles=cycles, new_items=new_items, wait_seconds=interval_seconds)
            sleep_fn(interval_seconds)
    return failures, new_items


def analyze_pending(
    store: DurableStore,
    *,
    server_url: str,
    timeout: int,
    wait_for_server_seconds: int,
    skip_server_health_check: bool,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Analyze only unseen source-content versions and retain prior analyses."""
    raw_items = store.raw_items()
    analyzed = store.analyses()
    session = requests.Session()
    if not skip_server_health_check:
        miner.wait_for_server(session, server_url, timeout, wait_for_server_seconds)
    pending = [(fingerprint, item) for fingerprint, item in raw_items.items() if fingerprint not in analyzed]
    for index, (fingerprint, item) in enumerate(pending, 1):
        analysis = miner.extract_evidence(
            session,
            server_url,
            f"Source: {item['source']}\nTitle: {item['title']}\nDiscussion: {item['text'][:3500]}",
            timeout,
        )
        record = miner.evidence_record(
            f"{item['source']}:{item['source_type']}",
            str(item["source_id"]),
            f"{item['source']}:{item['thread_id']}",
            str(item["title"]),
            str(item["author"]),
            str(item["url"]),
            str(item["text"]),
            analysis,
        )
        store.append_analysis(fingerprint, record)
        store.checkpoint("analyzing", total_items=len(raw_items), pending_items=len(pending), analyzed_this_run=index)
    records = list(store.analyses().values())
    summary = Counter(record["analysis"]["status"] for record in records)
    return records, {
        "total_analyzed": len(records),
        "evidence_units": summary["evidence"],
        "no_evidence": summary["no_evidence"],
        "invalid_responses": summary["invalid_response"],
        "newly_analyzed": len(pending),
    }


def merge_in_batches(
    session: requests.Session,
    server_url: str,
    groups: Mapping[str, list[dict[str, Any]]],
    *,
    timeout: int,
    batch_size: int,
) -> tuple[list[dict[str, Any]], str]:
    """Bound clustering prompts while preserving every candidate key."""
    keys = sorted(groups)
    if len(keys) <= batch_size:
        return miner.merge_clusters(session, server_url, groups, timeout)
    merged: list[dict[str, Any]] = []
    modes = []
    for start in range(0, len(keys), batch_size):
        batch = {key: groups[key] for key in keys[start : start + batch_size]}
        batch_merges, mode = miner.merge_clusters(session, server_url, batch, timeout)
        merged.extend(batch_merges)
        modes.append(mode)
    return merged, "batched_" + ("model_merged" if all(mode == "model_merged" for mode in modes) else "exact_fallback")


def classify_cluster(cluster: Mapping[str, Any]) -> str:
    """Use a user-facing confidence state without weakening validation policy."""
    if cluster["status"] == "validated":
        return "validated"
    support = cluster["support"]
    if support["evidence_units"] >= 2 and support["independent_authors"] >= 2 and support["distinct_threads"] >= 2:
        return "emerging"
    return "insufficient_evidence"


def build_report(
    store: DurableStore,
    records: list[dict[str, Any]],
    summary: dict[str, int],
    *,
    server_url: str,
    timeout: int,
    policy: dict[str, int],
    batch_size: int,
    output_dir: Path,
) -> tuple[Path, Path, dict[str, Any]]:
    """Cluster all persisted evidence and produce JSON plus readable Markdown."""
    session = requests.Session()
    evidence = [record for record in records if record["analysis"]["status"] == "evidence"]
    groups = miner.precluster(evidence)
    merges, clustering_mode = merge_in_batches(session, server_url, groups, timeout=timeout, batch_size=batch_size)
    clusters = miner.build_clusters(evidence, merges, **policy)
    for cluster in clusters:
        cluster["research_status"] = classify_cluster(cluster)
        if cluster["research_status"] == "validated":
            cluster["opportunity"] = miner.product_hypothesis(session, server_url, cluster, timeout)
    source_counts = Counter(record["source_type"].split(":", 1)[0] for record in records)
    status_counts = Counter(cluster["research_status"] for cluster in clusters)
    final_summary = {
        **summary,
        "candidate_clusters": len(clusters),
        "validated_clusters": status_counts["validated"],
        "emerging_clusters": status_counts["emerging"],
        "insufficient_evidence_clusters": status_counts["insufficient_evidence"],
        "records_by_source": dict(source_counts),
    }
    payload = {
        "schema_version": 1,
        "status": "complete",
        "completed_at": utc_now(),
        "validation_policy": policy,
        "clustering_mode": clustering_mode,
        "summary": final_summary,
        "clusters": clusters,
        "evidence_units": evidence,
        "checkpoint": str(store.checkpoint_path),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"overnight_multi_source_report_{stamp}.json"
    markdown_path = output_dir / f"overnight_multi_source_report_{stamp}.md"
    miner.write_json(json_path, payload)
    lines = [
        "# Overnight Multi-Source Pain Research Report",
        "",
        f"- **Completed at (UTC):** {payload['completed_at']}",
        f"- **Discussions analyzed:** {final_summary['total_analyzed']}",
        f"- **Evidence units:** {final_summary['evidence_units']}",
        f"- **Invalid model responses excluded:** {final_summary['invalid_responses']}",
        f"- **Validated:** {final_summary['validated_clusters']}",
        f"- **Emerging:** {final_summary['emerging_clusters']}",
        f"- **Insufficient evidence:** {final_summary['insufficient_evidence_clusters']}",
        f"- **Clustering mode:** {clustering_mode}",
        "",
        "## Validation policy",
        "",
        f"A validated cluster requires {policy['min_evidence']} evidence units from {policy['min_authors']} independent authors across {policy['min_threads']} threads.",
        "",
    ]
    for status, heading in (("validated", "Validated findings"), ("emerging", "Emerging leads"), ("insufficient_evidence", "Insufficient evidence")):
        matching = [cluster for cluster in clusters if cluster["research_status"] == status]
        lines.extend([f"## {heading}", ""])
        if not matching:
            lines.extend(["None.", ""])
            continue
        for cluster in matching[:30]:
            support = cluster["support"]
            lines.extend(
                [
                    f"### {cluster['cluster_key'].replace('_', ' ').title()}",
                    f"- **Support:** {support['evidence_units']} evidence units, {support['independent_authors']} authors, {support['distinct_threads']} threads",
                    f"- **Representative evidence:** {miner.markdown(cluster['evidence'][0]['analysis']['complaint'])}",
                    f"- **Source:** {cluster['evidence'][0]['url']}",
                    "",
                ]
            )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, markdown_path, payload
