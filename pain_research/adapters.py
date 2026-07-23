"""Adapters for public APIs; each emits the shared evidence schema."""

from __future__ import annotations

import html
import re
from collections.abc import Iterable
from typing import Any, Protocol

from pain_research.http import ApiClient
from pain_research.models import EvidenceItem, Target


def clean_text(value: Any) -> str:
    """Convert provider HTML into compact plain text without executing it."""
    value = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def clean_author(value: Any) -> str:
    """Keep attribution while normalizing absent or deleted accounts."""
    result = str(value or "").strip()
    return result if result and result.lower() not in {"[deleted]", "unknown", "none"} else "Unknown"


class Adapter(Protocol):
    """A public API adapter that emits discussion units."""

    def collect(self, target: Target, limit: int, comments_per_thread: int) -> Iterable[EvidenceItem]:
        """Collect no more than the configured source units."""


class GitHubAdapter:
    """Collect public GitHub issues and their most recent comments."""

    def __init__(self, client: ApiClient, token: str | None = None) -> None:
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}

    def collect(self, target: Target, limit: int, comments_per_thread: int) -> Iterable[EvidenceItem]:
        repository = str(target.config["repository"])
        collected = 0
        page = 1
        while collected < limit:
            payload = self.client.get_json(
                f"https://api.github.com/repos/{repository}/issues",
                params={"state": target.config.get("state", "open"), "sort": "updated", "direction": "desc", "per_page": 100, "page": page},
                headers=self.headers,
            )
            if not payload:
                return
            for issue in payload:
                if "pull_request" in issue:
                    continue
                issue_id = f"github:{repository}:issue:{issue['number']}"
                labels = [label["name"] for label in issue.get("labels", []) if isinstance(label, dict) and label.get("name")]
                yield EvidenceItem(
                    source="github",
                    source_id=issue_id,
                    thread_id=issue_id,
                    source_type="issue",
                    title=str(issue.get("title", "")),
                    author=clean_author(issue.get("user", {}).get("login")),
                    url=str(issue.get("html_url", "")),
                    text=clean_text(issue.get("body")),
                    created_at=issue.get("created_at"),
                    updated_at=issue.get("updated_at"),
                    metadata={"repository": repository, "state": issue.get("state"), "labels": labels, "comments": issue.get("comments", 0)},
                )
                collected += 1
                if comments_per_thread and issue.get("comments"):
                    for comment in self._comments(issue, issue_id, comments_per_thread):
                        yield comment
                if collected >= limit:
                    return
            if len(payload) < 100:
                return
            page += 1

    def _comments(self, issue: dict[str, Any], thread_id: str, limit: int) -> Iterable[EvidenceItem]:
        payload = self.client.get_json(issue["comments_url"], params={"per_page": min(limit, 100), "page": 1}, headers=self.headers)
        for comment in payload[:limit]:
            yield EvidenceItem(
                source="github",
                source_id=f"{thread_id}:comment:{comment['id']}",
                thread_id=thread_id,
                source_type="issue_comment",
                title=f"Comment on: {issue.get('title', '')}",
                author=clean_author(comment.get("user", {}).get("login")),
                url=str(comment.get("html_url", issue.get("html_url", ""))),
                text=clean_text(comment.get("body")),
                created_at=comment.get("created_at"),
                updated_at=comment.get("updated_at"),
                metadata={"repository": thread_id.split(":issue:")[0].removeprefix("github:")},
            )


class DiscourseAdapter:
    """Collect threads and replies from public Discourse-compatible forums."""

    def __init__(self, client: ApiClient) -> None:
        self.client = client

    def collect(self, target: Target, limit: int, comments_per_thread: int) -> Iterable[EvidenceItem]:
        base_url = str(target.config["base_url"]).rstrip("/")
        yielded_threads = 0
        page = 0
        while yielded_threads < limit:
            listing = self.client.get_json(f"{base_url}/latest.json", params={"page": page})
            topics = listing.get("topic_list", {}).get("topics", [])
            if not topics:
                return
            for topic in topics:
                topic_id = topic["id"]
                detail = self.client.get_json(f"{base_url}/t/{topic_id}.json")
                posts = detail.get("post_stream", {}).get("posts", [])
                if not posts:
                    continue
                thread_id = f"discourse:{base_url}:{topic_id}"
                topic_url = f"{base_url}/t/{topic.get('slug', topic_id)}/{topic_id}"
                for post in posts[: max(1, comments_per_thread + 1)]:
                    is_first = post.get("post_number") == 1
                    yield EvidenceItem(
                        source="discourse",
                        source_id=f"{thread_id}:post:{post['id']}",
                        thread_id=thread_id,
                        source_type="forum_post" if is_first else "forum_reply",
                        title=str(topic.get("title", "")) if is_first else f"Reply on: {topic.get('title', '')}",
                        author=clean_author(post.get("username")),
                        url=f"{topic_url}/{post.get('post_number', 1)}",
                        text=clean_text(post.get("cooked")),
                        created_at=post.get("created_at"),
                        updated_at=post.get("updated_at"),
                        metadata={"forum": target.name, "topic_id": topic_id, "reply_count": topic.get("reply_count", 0)},
                    )
                yielded_threads += 1
                if yielded_threads >= limit:
                    return
            page += 1


class StackExchangeAdapter:
    """Collect public questions from the Stack Exchange API."""

    def __init__(self, client: ApiClient) -> None:
        self.client = client

    def collect(self, target: Target, limit: int, comments_per_thread: int) -> Iterable[EvidenceItem]:
        del comments_per_thread
        site = str(target.config.get("site", "stackoverflow"))
        tag = str(target.config["tag"])
        yielded = 0
        page = 1
        while yielded < limit:
            payload = self.client.get_json(
                "https://api.stackexchange.com/2.3/questions",
                params={"site": site, "tagged": tag, "sort": "activity", "order": "desc", "pagesize": min(limit - yielded, 100), "page": page, "filter": "withbody"},
            )
            for question in payload.get("items", []):
                question_id = question["question_id"]
                yield EvidenceItem(
                    source="stackexchange",
                    source_id=f"stackexchange:{site}:question:{question_id}",
                    thread_id=f"stackexchange:{site}:question:{question_id}",
                    source_type="question",
                    title=str(question.get("title", "")),
                    author=clean_author(question.get("owner", {}).get("display_name")),
                    url=str(question.get("link", "")),
                    text=clean_text(question.get("body")),
                    created_at=str(question.get("creation_date", "")) or None,
                    updated_at=str(question.get("last_activity_date", "")) or None,
                    metadata={"site": site, "tag": tag, "score": question.get("score", 0), "answer_count": question.get("answer_count", 0), "is_answered": question.get("is_answered", False)},
                )
                yielded += 1
                if yielded >= limit:
                    return
            if not payload.get("has_more"):
                return
            if payload.get("backoff"):
                self.client.sleep(float(payload["backoff"]))
            page += 1


class HackerNewsAdapter:
    """Collect public Hacker News comments through the Algolia API."""

    def __init__(self, client: ApiClient) -> None:
        self.client = client

    def collect(self, target: Target, limit: int, comments_per_thread: int) -> Iterable[EvidenceItem]:
        del comments_per_thread
        query = str(target.config["query"])
        payload = self.client.get_json(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={"query": query, "tags": "comment", "hitsPerPage": min(limit, 100)},
        )
        for hit in payload.get("hits", [])[:limit]:
            story_id = hit.get("story_id") or hit.get("objectID")
            thread_id = f"hackernews:story:{story_id}"
            yield EvidenceItem(
                source="hackernews",
                source_id=f"hackernews:comment:{hit['objectID']}",
                thread_id=thread_id,
                source_type="comment",
                title=str(hit.get("story_title") or "Hacker News discussion"),
                author=clean_author(hit.get("author")),
                url=str(hit.get("story_url") or f"https://news.ycombinator.com/item?id={story_id}"),
                text=clean_text(hit.get("comment_text")),
                created_at=hit.get("created_at"),
                metadata={"query": query, "story_id": story_id, "points": hit.get("points")},
            )


def adapter_for(source: str, client: ApiClient, github_token: str | None = None) -> Adapter:
    """Return the adapter for a configured public source."""
    adapters: dict[str, Adapter] = {
        "github": GitHubAdapter(client, github_token),
        "discourse": DiscourseAdapter(client),
        "stackexchange": StackExchangeAdapter(client),
        "hackernews": HackerNewsAdapter(client),
    }
    try:
        return adapters[source]
    except KeyError as error:
        raise ValueError(f"Unsupported source: {source}") from error
