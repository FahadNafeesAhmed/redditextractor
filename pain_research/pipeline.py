"""Orchestration, defaults, and auditable output for multi-source collection."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pain_research.adapters import adapter_for
from pain_research.http import ApiClient
from pain_research.models import EvidenceItem, Target


DEFAULT_LOCAL_AI_TARGETS = (
    Target("github", "llama.cpp issues", {"repository": "ggml-org/llama.cpp"}),
    Target("github", "Ollama issues", {"repository": "ollama/ollama"}),
    Target("github", "vLLM issues", {"repository": "vllm-project/vllm"}),
    Target("github", "ROCm issues", {"repository": "ROCm/ROCm"}),
    Target("discourse", "Hugging Face Forums", {"base_url": "https://discuss.huggingface.co"}),
    Target("discourse", "NVIDIA Developer Forums", {"base_url": "https://forums.developer.nvidia.com"}),
    Target("stackexchange", "Stack Overflow LLM", {"site": "stackoverflow", "tag": "large-language-model"}),
    Target("hackernews", "Hacker News local LLM", {"query": "local LLM"}),
)


def utc_now() -> str:
    """Return the collection timestamp in UTC."""
    return datetime.now(timezone.utc).isoformat()


def load_targets(path: Path) -> tuple[Target, ...]:
    """Load explicit targets from a small JSON configuration file."""
    raw_targets = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_targets, list):
        raise ValueError("Target file must be a JSON list.")
    result = []
    for entry in raw_targets:
        if not isinstance(entry, dict) or not {"source", "name", "config"} <= entry.keys():
            raise ValueError("Every target needs source, name, and config fields.")
        result.append(Target(str(entry["source"]), str(entry["name"]), dict(entry["config"])))
    return tuple(result)


def collect_all(
    targets: tuple[Target, ...],
    *,
    client: ApiClient,
    limit_per_target: int,
    comments_per_thread: int,
    github_token: str | None = None,
) -> tuple[list[EvidenceItem], list[dict[str, str]]]:
    """Collect every explicitly selected target, retaining per-target failures."""
    collected: list[EvidenceItem] = []
    failures: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for target in targets:
        try:
            adapter = adapter_for(target.source, client, github_token)
            for item in adapter.collect(target, limit_per_target, comments_per_thread):
                key = (item.source, item.source_id)
                if key not in seen:
                    collected.append(item)
                    seen.add(key)
        except Exception as error:
            failures.append({"source": target.source, "target": target.name, "error": str(error)})
    return collected, failures


def write_collection(
    output_dir: Path,
    targets: tuple[Target, ...],
    items: list[EvidenceItem],
    failures: list[dict[str, str]],
) -> Path:
    """Write a complete audit payload without overwriting prior collections."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"multi_source_collection_{stamp}.json"
    counts: dict[str, int] = {}
    for item in items:
        counts[item.source] = counts.get(item.source, 0) + 1
    payload: dict[str, Any] = {
        "schema_version": 1,
        "collected_at": utc_now(),
        "targets": [{"source": target.source, "name": target.name, "config": target.config} for target in targets],
        "summary": {"items": len(items), "items_by_source": counts, "failed_targets": len(failures)},
        "failures": failures,
        "items": [item.as_dict() for item in items],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
