# Multi-Source Pain Research Architecture

## Goal

Collect public, attributable discussion units from several provider APIs without deciding that any one item is a pain point. Collection stays separate from LLM evidence extraction and recurrence validation.

## Data flow

~~~text
Explicit target configuration
        |
        v
Source adapter (GitHub / Discourse / Stack Exchange / Hacker News)
        |
        v
Rate-limited public API client
        |
        v
Normalized EvidenceItem records + provenance
        |
        v
Versioned JSON audit file
        |
        v
Durable evidence extraction and recurrence validation
~~~

## Components

| Component | Responsibility |
| --- | --- |
| `pain_research/models.py` | Defines `Target` and source-neutral `EvidenceItem` records. Every item retains author, URL, thread ID, timestamps, and source metadata. |
| `pain_research/http.py` | Applies a per-host request interval, honors `Retry-After`, retries temporary API failures, and never hides a final failure. |
| `pain_research/adapters.py` | Contains provider-specific parsing only. Adapters emit posts/comments as independent evidence units while retaining a shared thread identity. |
| `pain_research/pipeline.py` | Selects targets, deduplicates records, isolates target failures, and writes a timestamped audit payload. |
| `multi_source_scraper.py` | One-shot command-line boundary. It reads configuration, optionally uses `GITHUB_TOKEN`, and prints the audit path. |
| `overnight_pain_research.py` | Durable runner that checkpoints collection and analysis, then writes a recurrence-validation report. |

## Source contracts

| Source | API | Unit emitted | Thread identity |
| --- | --- | --- | --- |
| GitHub | REST Issues API | Issue and issue comment | Repository + issue number |
| Discourse | Public JSON endpoints | Topic post and reply | Forum URL + topic ID |
| Stack Exchange | Public API | Question | Site + question ID |
| Hacker News | Algolia public API | Comment | Story ID |

## Safety and research rules

- Public APIs only. No login bypasses, private communities, or bulk HTML scraping.
- Targets are explicit and stored in the output manifest.
- Raw content is kept with URL and author so every claim can be audited.
- A source failure is recorded in `failures`; it never silently turns into an empty result.
- The collector does not generate product ideas or label content as a pain point.
- `GITHUB_TOKEN` is optional and read from the environment only; it is never written into reports.

## Usage

~~~powershell
python multi_source_scraper.py --dry-run
python multi_source_scraper.py --limit-per-target 50 --comments-per-thread 5
python multi_source_scraper.py --source github --source discourse --limit-per-target 100
~~~

Use a target file to replace defaults:

~~~json
[
  {"source": "github", "name": "my project", "config": {"repository": "owner/repository"}},
  {"source": "hackernews", "name": "HN topic", "config": {"query": "GPU inference"}}
]
~~~

~~~powershell
python multi_source_scraper.py --target-file targets.json
~~~

## Deliberate next step

`overnight_pain_research.py` now provides the durable handoff without coupling provider APIs to the validator. It writes append-only collected and analyzed item stores, then calls the existing strict local-LLM evidence extractor only for new source-content fingerprints.

## Overnight operation

~~~text
per-source API collection
  -> append one normalized item and fsync it
  -> update atomic checkpoint.json
  -> on restart, replay safely and skip prior fingerprints
  -> analyze only never-seen item versions
  -> cluster all durable evidence
  -> write validated / emerging / insufficient-evidence report
~~~

The runner acquires `reports/overnight_state/run.lock`; a second process exits safely rather than duplicating collection or analysis. Do not delete that lock while a run is active. Each source item is fingerprinted from its source ID, update time, title, and body, so unchanged records are deduplicated across nights while changed issues can be reevaluated.

~~~powershell
python overnight_pain_research.py --cycles 2 --interval-minutes 120 --limit-per-target 20 --comments-per-thread 3
~~~

The resulting report separates `validated`, `emerging`, and `insufficient_evidence` clusters. A report can be resumed after interruption by running the same command again; persisted items and analyses will not be duplicated.

## Research lanes

Keep technically different markets in different durable state directories. The included configurations are:

| Lane | Target configuration | State directory | Buyer/problem focus |
| --- | --- | --- | --- |
| Local AI infrastructure | `overnight_targets.json` | `reports/overnight_state` | Inference, GPU, VRAM, serving, and developer toolchains. |
| AI agents and integrations | `agent_integration_targets.json` | `reports/agent_integration_state` | 22 public sources covering agent reliability, MCP/tools, orchestration, state/memory, integrations, and observability. |

~~~powershell
python overnight_pain_research.py --target-file agent_integration_targets.json --state-dir reports\agent_integration_state --limit-per-target 50 --comments-per-thread 3 --min-request-interval 2
~~~
