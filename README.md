# Recurring Reddit Pain Point Miner

This local research tool finds recurring developer workflow problems in public Reddit RSS discussions. A post or comment is treated as evidence, never as a validated market problem by itself.

## Evidence before conclusions

The validated workflow has two separate stages:

1. **Evidence extraction** reviews each post and comment for an explicit, first-hand complaint, impact, and stated workaround. Invalid model output is excluded; it never falls back to keyword matching.
2. **Cluster validation** groups related evidence and promotes a cluster only after it reaches independent recurrence thresholds.

By default, validation requires:

- 3 evidence units
- 3 independent authors
- 2 distinct Reddit threads

This prevents a single vivid post, or multiple comments under the same post, from becoming a supposedly validated opportunity. Only validated clusters receive a product hypothesis. Everything else is reported as an emerging lead.

## Requirements

- Python 3.10 or later
- A local OpenAI-compatible llama-server endpoint
- Python packages: requests and feedparser

~~~powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install requests feedparser
~~~

Start your local model server:

~~~powershell
.\llama-bin\llama-server.exe -m "path\to\model.gguf" -ngl 99 --port 8080
~~~

## Run the validated pipeline

~~~powershell
python validated_pain_point_miner.py --subreddit LocalLLaMA --limit 50 --comments 5
~~~

Use stricter recurrence thresholds for broader research:

~~~powershell
python validated_pain_point_miner.py --subreddit LocalLLaMA --limit 100 --comments 5 --min-evidence 4 --min-authors 4 --min-threads 3
~~~

## Output

Generated files are written to reports:

- reddit_pain_evidence_live.json shows collection status without premature validation.
- validated_pain_clusters_r_<subreddit>_<timestamp>.json contains the audit trail, evidence, policy, and clusters.
- validated_opportunities_r_<subreddit>_<timestamp>.md distinguishes validated clusters from unvalidated leads.

Generated reports and local virtual environments are ignored by Git.

## Multi-source public API collection

`multi_source_scraper.py` collects attributable public discussion units from GitHub Issues, Discourse forums, Stack Exchange, and Hacker News. It uses provider APIs and public JSON endpoints with per-host pacing and retry/backoff; it does not scrape private communities or label collected content as a pain point.

~~~powershell
python multi_source_scraper.py --dry-run
python multi_source_scraper.py --limit-per-target 50 --comments-per-thread 5
~~~

The collector writes a versioned `multi_source_collection_<timestamp>.json` audit file to `reports`. Its normalized `source_id`, `thread_id`, `author`, URL, timestamps, text, and source metadata are the input contract for the overnight validation runner. See [the architecture document](MULTI_SOURCE_ARCHITECTURE.md) for adapter contracts, safeguards, and custom target configuration.

## Durable overnight research

`overnight_pain_research.py` adds checkpoints, cross-run deduplication, a single-run lock, automatic local-LLM validation, and a final report with `validated`, `emerging`, and `insufficient_evidence` states.

~~~powershell
python overnight_pain_research.py --cycles 2 --interval-minutes 120 --limit-per-target 20 --comments-per-thread 3
~~~

Progress is stored under `reports/overnight_state`. Each collected and analyzed item is appended and flushed immediately. If the computer or network interrupts the process, run the same command again to resume without double-counting unchanged records.

### AI-agent and integration research lane

`agent_integration_targets.json` is an included, broad target set for researching reliability problems in AI agents and the systems around them. It currently spans 22 public sources: 16 GitHub projects plus Stack Overflow and Hacker News searches. The set covers agent frameworks, MCP and tool integrations, workflow automation, memory, observability, and browser agents.

Run it in a separate state directory so its evidence cannot be mixed with the local-AI-infrastructure lane:

~~~powershell
python overnight_pain_research.py --target-file agent_integration_targets.json --cycles 1 --limit-per-target 50 --comments-per-thread 3 --min-request-interval 2 --state-dir reports\agent_integration_state --output-dir reports --wait-for-server 600
~~~

Do not run a second copy while `reports\agent_integration_state\run.lock` exists. A completed run writes Markdown and JSON reports in `reports` and labels each cluster as `validated`, `emerging`, or `insufficient_evidence`. A `validated` result still means only that the collected public evidence met the recurrence policy; it is not proof of a viable business.
