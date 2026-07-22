from __future__ import annotations

import unittest

import validated_pain_point_miner as miner


def evidence(author: str, thread_id: str, key: str = "multi_gpu_utilization") -> dict:
    return {
        "source_type": "post",
        "source_id": f"{thread_id}-{author}",
        "thread_id": thread_id,
        "title": "GPU utilization issue",
        "author": author,
        "url": "https://example.test/post",
        "text": "A repeated GPU issue.",
        "analysis": {
            "status": "evidence",
            "has_explicit_pain": True,
            "pain_key": key,
            "category": "GPU Inference",
            "complaint": "Two GPUs remain underutilized during inference.",
            "impact": "Inference throughput is lower than expected.",
            "workaround": "None stated.",
            "evidence_strength": "strong",
        },
    }


class ValidatedPainPointMinerTests(unittest.TestCase):
    def test_malformed_json_is_excluded_not_keyword_classified(self):
        result = miner.parse_evidence({"has_explicit_pain": True, "complaint": "The GPU is slow"})

        self.assertEqual(result["status"], "invalid_response")
        self.assertFalse(result["has_explicit_pain"])

    def test_false_response_is_not_evidence(self):
        self.assertEqual(miner.parse_evidence({"has_explicit_pain": False})["status"], "no_evidence")

    def test_recurrence_across_authors_and_threads_validates(self):
        items = [evidence("alice", "thread-1"), evidence("bob", "thread-1"), evidence("carol", "thread-2")]
        clusters = miner.build_clusters(
            items,
            [{"cluster_key": "multi_gpu_utilization", "candidate_keys": ["multi_gpu_utilization"]}],
            min_evidence=3,
            min_authors=3,
            min_threads=2,
        )

        self.assertEqual(clusters[0]["status"], "validated")
        self.assertEqual(clusters[0]["support"]["independent_authors"], 3)
        self.assertEqual(clusters[0]["support"]["distinct_threads"], 2)

    def test_many_comments_in_one_thread_remain_an_emerging_lead(self):
        items = [evidence("alice", "thread-1"), evidence("bob", "thread-1"), evidence("carol", "thread-1")]
        clusters = miner.build_clusters(
            items,
            [{"cluster_key": "multi_gpu_utilization", "candidate_keys": ["multi_gpu_utilization"]}],
            min_evidence=3,
            min_authors=3,
            min_threads=2,
        )

        self.assertEqual(clusters[0]["status"], "emerging_lead")
        self.assertEqual(clusters[0]["support"]["distinct_threads"], 1)

    def test_omitted_candidate_key_is_preserved_as_its_own_cluster(self):
        parsed = miner.parse_merges(
            {
                "merges": [
                    {
                        "cluster_key": "gpu_inference_utilization",
                        "candidate_keys": ["multi_gpu_utilization"],
                    }
                ]
            },
            {"multi_gpu_utilization", "vram_batch_tuning"},
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(
            {tuple(item["candidate_keys"]) for item in parsed},
            {("multi_gpu_utilization",), ("vram_batch_tuning",)},
        )


if __name__ == "__main__":
    unittest.main()
