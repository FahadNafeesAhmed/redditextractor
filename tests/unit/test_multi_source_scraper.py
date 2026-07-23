from __future__ import annotations

import unittest

from pain_research.adapters import DiscourseAdapter, GitHubAdapter, HackerNewsAdapter, StackExchangeAdapter
from pain_research.models import Target
from pain_research.pipeline import collect_all


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.sleep_calls = []

    def get_json(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses[url]
        return response.pop(0) if isinstance(response, list) else response

    def sleep(self, seconds):
        self.sleep_calls.append(seconds)


class MultiSourceCollectorTests(unittest.TestCase):
    def test_github_excludes_pull_requests_and_keeps_comment_thread_identity(self):
        issues_url = "https://api.github.com/repos/acme/tool/issues"
        comments_url = "https://api.github.com/repos/acme/tool/issues/7/comments"
        client = FakeClient(
            {
                issues_url: [[
                    {"number": 8, "pull_request": {}, "title": "A pull request"},
                    {
                        "number": 7,
                        "title": "GPU memory leak",
                        "body": "Leaks after long jobs",
                        "user": {"login": "alice"},
                        "html_url": "https://github.com/acme/tool/issues/7",
                        "comments": 1,
                        "comments_url": comments_url,
                        "state": "open",
                        "labels": [{"name": "bug"}],
                    },
                ]],
                comments_url: [[{"id": 99, "body": "Same on AMD", "user": {"login": "bob"}, "html_url": "https://github.com/acme/tool/issues/7#issuecomment-99"}]],
            }
        )

        items = list(GitHubAdapter(client).collect(Target("github", "tool", {"repository": "acme/tool"}), 10, 2))

        self.assertEqual([item.source_type for item in items], ["issue", "issue_comment"])
        self.assertEqual(items[0].thread_id, items[1].thread_id)
        self.assertEqual(items[0].metadata["labels"], ["bug"])

    def test_discourse_turns_a_thread_and_reply_into_independent_units(self):
        base = "https://forum.example"
        client = FakeClient(
            {
                f"{base}/latest.json": [{"topic_list": {"topics": [{"id": 5, "slug": "gpu", "title": "GPU setup", "reply_count": 1}]}}],
                f"{base}/t/5.json": [{"post_stream": {"posts": [
                    {"id": 10, "post_number": 1, "username": "alice", "cooked": "<p>Setup <b>fails</b></p>"},
                    {"id": 11, "post_number": 2, "username": "bob", "cooked": "<p>Same issue</p>"},
                ]}}],
            }
        )

        items = list(DiscourseAdapter(client).collect(Target("discourse", "forum", {"base_url": base}), 1, 1))

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].thread_id, items[1].thread_id)
        self.assertEqual(items[0].text, "Setup fails")
        self.assertEqual(items[1].author, "bob")

    def test_stackexchange_and_hackernews_preserve_attribution(self):
        stack_client = FakeClient(
            {
                "https://api.stackexchange.com/2.3/questions": [{"items": [{"question_id": 3, "title": "OOM error", "body": "<p>How fix?</p>", "owner": {"display_name": "alice"}, "link": "https://stackoverflow.com/q/3", "score": 2, "answer_count": 1, "is_answered": False}], "has_more": False}],
            }
        )
        hn_client = FakeClient(
            {
                "https://hn.algolia.com/api/v1/search_by_date": [{"hits": [{"objectID": "2", "story_id": "1", "story_title": "Local LLM", "comment_text": "<p>Too slow</p>", "author": "bob", "created_at": "2026-01-01"}]}],
            }
        )

        stack = list(StackExchangeAdapter(stack_client).collect(Target("stackexchange", "stack", {"site": "stackoverflow", "tag": "python"}), 1, 0))
        hn = list(HackerNewsAdapter(hn_client).collect(Target("hackernews", "hn", {"query": "local LLM"}), 1, 0))

        self.assertEqual(stack[0].author, "alice")
        self.assertEqual(stack[0].text, "How fix?")
        self.assertEqual(hn[0].thread_id, "hackernews:story:1")
        self.assertEqual(hn[0].text, "Too slow")

    def test_orchestrator_retains_a_failed_target_without_losing_successes(self):
        class FailingClient(FakeClient):
            def get_json(self, url, **kwargs):
                if "bad" in url:
                    raise RuntimeError("service unavailable")
                return super().get_json(url, **kwargs)

        client = FailingClient(
            {
                "https://hn.algolia.com/api/v1/search_by_date": [{"hits": [{"objectID": "2", "story_id": "1", "comment_text": "pain", "author": "alice"}]}],
            }
        )
        targets = (
            Target("hackernews", "good", {"query": "local LLM"}),
            Target("discourse", "bad", {"base_url": "https://bad.example"}),
        )

        items, failures = collect_all(targets, client=client, limit_per_target=1, comments_per_thread=0)

        self.assertEqual(len(items), 1)
        self.assertEqual(failures[0]["target"], "bad")


if __name__ == "__main__":
    unittest.main()
