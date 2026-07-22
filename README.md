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
