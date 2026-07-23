from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pain_research.models import EvidenceItem
from pain_research.overnight import AlreadyRunningError, DurableStore, classify_cluster, fingerprint_item


class OvernightResearchTests(unittest.TestCase):
    def test_fingerprint_changes_when_source_content_changes(self):
        initial = EvidenceItem("github", "issue:1", "issue:1", "issue", "OOM", "alice", "https://example.test/1", "first text", updated_at="2026-01-01")
        changed = EvidenceItem("github", "issue:1", "issue:1", "issue", "OOM", "alice", "https://example.test/1", "new text", updated_at="2026-01-02")

        self.assertNotEqual(fingerprint_item(initial), fingerprint_item(changed))

    def test_store_deduplicates_and_persists_before_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary)
            item = EvidenceItem("github", "issue:1", "issue:1", "issue", "OOM", "alice", "https://example.test/1", "first text")
            store = DurableStore(state_dir)

            self.assertTrue(store.append_raw(item))
            self.assertFalse(store.append_raw(item))
            restarted_store = DurableStore(state_dir)
            self.assertEqual(len(restarted_store.raw_items()), 1)

    def test_lock_refuses_a_duplicate_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = DurableStore(Path(temporary))
            second = DurableStore(Path(temporary))
            first.acquire_lock()
            try:
                with self.assertRaises(AlreadyRunningError):
                    second.acquire_lock()
            finally:
                first.release_lock()

    def test_user_facing_cluster_states_do_not_weaken_validation(self):
        def cluster(status, evidence, authors, threads):
            return {"status": status, "support": {"evidence_units": evidence, "independent_authors": authors, "distinct_threads": threads}}

        self.assertEqual(classify_cluster(cluster("validated", 3, 3, 2)), "validated")
        self.assertEqual(classify_cluster(cluster("emerging_lead", 2, 2, 2)), "emerging")
        self.assertEqual(classify_cluster(cluster("emerging_lead", 4, 1, 4)), "insufficient_evidence")


if __name__ == "__main__":
    unittest.main()
