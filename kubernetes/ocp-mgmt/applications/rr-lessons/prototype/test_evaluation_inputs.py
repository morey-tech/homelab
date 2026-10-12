import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evaluation import build_inputs
from prepare import PreparationError, digest


class EvaluationInputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.seed_path = self.root / "seed.json"
        self.text = "## Episode 1\n\nHost: What is the distinction?\n\nGuest: Ownership can be risky.\n\nHost: Outcomes vary.\n"
        self.source = {"episode": 1, "commit": "a" * 40,
                       "sha256": digest(self.text.encode()), "transcript_url": "https://example.org/1"}
        self.seed = {"source_revision": "a" * 40, "episodes": [1], "groups": [
            {"id": "risk", "episode": 1, "anchors": ["Ownership can be risky."],
             "must_preserve": ["Do not promise success."],
             "queries": [{"id": "risk-plain", "kind": "paraphrase", "text": "Is owning a firm safe?"}]}],
            "negative_queries": [{"id": "negative", "group_id": "negative", "kind": "out_of_domain",
                                  "text": "How do I grow tomatoes?", "reason": "Unrelated"}]}

    def build(self, reports=()):
        self.seed_path.write_text(json.dumps(self.seed))
        with patch.object(build_inputs, "read_source", return_value=(self.source, self.text, self.text.index("\n"))):
            return build_inputs.build(self.root, self.seed_path, reports)

    def test_draft_inputs_resolve_exact_evidence_and_neighbor_context(self):
        bundle, texts, selection = self.build()
        self.assertIsNone(selection)
        self.assertEqual(bundle["record_count"], 0)
        self.assertEqual(bundle["status"], "draft_not_scorable")
        self.assertEqual(texts[1], self.text)
        evidence = bundle["evidence"][0]
        self.assertEqual(len(evidence["evidence_ids"]), 1)
        self.assertEqual(len(evidence["passages"]), 3)
        for passage in evidence["passages"]:
            self.assertEqual(self.text[passage["start_char"]:passage["end_char"]], passage["text"])
        for query in bundle["queries"]:
            self.assertIsNone(query["record_judgments"])
            self.assertEqual(query["split"], "development")
            self.assertEqual(query["label_status"], "draft_pending_human_review")
        self.assertIn("Do not promise success.", build_inputs.render(bundle))
        self.assertEqual(bundle, self.build()[0])

    def test_missing_or_ambiguous_anchor_fails(self):
        for anchor in ("Invented evidence.", "Host:"):
            with self.subTest(anchor=anchor):
                self.seed["groups"][0]["anchors"] = [anchor]
                with self.assertRaisesRegex(PreparationError, "exactly once"):
                    self.build()

    def test_duplicate_query_ids_fail(self):
        self.seed["negative_queries"][0]["id"] = "risk-plain"
        with self.assertRaisesRegex(PreparationError, "Duplicate query"):
            self.build()

    def test_corpus_snapshot_must_match_and_never_approves_labels(self):
        selection = {"records": [{"id": "one"}], "reports": [{"source": self.source}]}
        with patch.object(build_inputs, "select_reports", return_value=selection):
            bundle, _, selected = self.build([self.root])
            self.assertEqual(bundle["record_count"], 1)
            self.assertEqual(selected, selection)
            self.assertIsNotNone(bundle["selection_sha256"])
            self.assertEqual(bundle["status"], "draft_not_scorable")
        bad = copy.deepcopy(selection)
        bad["reports"][0]["source"]["commit"] = "b" * 40
        with patch.object(build_inputs, "select_reports", return_value=bad):
            with self.assertRaisesRegex(PreparationError, "differs"):
                self.build([self.root])


if __name__ == "__main__":
    unittest.main()
