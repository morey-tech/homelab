import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import prepare
import retrieve


class FakeEmbedder:
    spec = {"model": "test-only", "revision": "1", "dimensions": 3}

    def encode(self, texts, query=False):
        return [[1., 0., 0.] if "ownership" in text.lower() else [0., 1., 0.] for text in texts]


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def fixture(self, episode=1):
        directory = self.root / f"episode-{episode}"
        directory.mkdir()
        text = f"## Episode {episode}\n\nHost: Who holds wealth?\n\nGuest: Business ownership contributes to wealth.\n\nHost: In this sample."
        source = {"episode": episode, "commit": "a" * 40, "sha256": prepare.digest(text.encode()),
                  "transcript_url": f"https://example.org/episode-{episode}"}
        passages = prepare.passages(source, text, text.index("\n"))
        candidate = {"concept": "Business ownership", "question": "How does ownership contribute to wealth?",
                     "answer_outline": [{"claim": "Business ownership contributes to wealth.",
                                         "passage_ids": [passages[1]["id"]]}],
                     "context_ids": [], "qualifications": ["In this sample."], "prerequisites": []}
        review = {"supported": True, "context_sufficient": True, "teachable": True,
                  "reason": "Explicit in source", "confidence": "high", "confidence_reason": "Directly stated"}
        question = {"id": "section-001-q1", "candidate": candidate, "review": review,
                    "status": "needs_human_review", "human_review": "pending",
                    "review_passage_ids": [p["id"] for p in passages]}
        report = {"source": source, "passages": passages, "sections": prepare.sections(passages),
                  "status": "partial", "completed_sections": 1, "questions": [question]}
        (directory / "source.md").write_text(text)
        (directory / "manifest.json").write_bytes(prepare.encoded({"source": source}))
        self.write_report(directory, report)
        return directory, report

    def write_report(self, directory, report):
        (directory / "report.json").write_bytes(prepare.encoded(report))

    def test_selection_excludes_failed_high_ratings_and_retains_provenance(self):
        directory, report = self.fixture()
        for field, value in (("status", "rejected"), ("human_review", "rejected"), ("error", "Invalid review")):
            entry = copy.deepcopy(report["questions"][0])
            entry["id"] = field
            entry[field] = value
            report["questions"].append(entry)
        for level, supported in (("medium", True), ("low", True), ("high", False)):
            entry = copy.deepcopy(report["questions"][0])
            entry["id"] = f"{level}-{supported}"
            entry["review"].update(confidence=level, supported=supported)
            report["questions"].append(entry)
        self.write_report(directory, report)
        original = (directory / "report.json").read_bytes()
        bundle = retrieve.select_reports([directory])
        self.assertEqual(len(bundle["records"]), 1)
        self.assertEqual(len(bundle["excluded"]), 6)
        selected = bundle["records"][0]
        self.assertFalse(selected["production_approved"])
        self.assertEqual(selected["human_review"], "pending")
        self.assertEqual(selected["passages"], report["passages"])
        self.assertEqual(selected["candidate"]["qualifications"], ["In this sample."])
        self.assertEqual(bundle["reports"][0]["status"], "partial")
        self.assertEqual((directory / "report.json").read_bytes(), original)

    def test_source_tampering_and_incomplete_context_fail(self):
        directory, report = self.fixture()
        original = copy.deepcopy(report)
        for mutation in (lambda r: r["passages"][1].update(text="Invented statement"),
                         lambda r: r["passages"][1].update(source_url="https://wrong.example"),
                         lambda r: r["questions"][0].update(review_passage_ids=[r["passages"][1]["id"]])):
            report = copy.deepcopy(original)
            mutation(report)
            self.write_report(directory, report)
            with self.assertRaises(prepare.PreparationError):
                retrieve.select_reports([directory])
        self.write_report(directory, original)
        (directory / "source.md").write_text("Changed source")
        with self.assertRaises(prepare.PreparationError):
            retrieve.select_reports([directory])

    def test_ids_do_not_collide_across_episodes_and_order_is_stable(self):
        one, _ = self.fixture(1)
        two, _ = self.fixture(2)
        first = retrieve.select_reports([one, two])
        self.assertEqual(first, retrieve.select_reports([two, one]))
        self.assertEqual(len({r["id"] for r in first["records"]}), 2)

    @unittest.skipUnless(importlib.util.find_spec("lancedb"), "Install retrieval requirements for real LanceDB tests")
    def test_persistence_repeat_ingest_mismatch_and_context_roundtrip(self):
        directory, report = self.fixture()
        bundle = retrieve.select_reports([directory])
        embedder = FakeEmbedder()
        output = self.root / "index"
        self.assertFalse(retrieve.ingest(bundle, output, embedder)["reused"])
        self.assertEqual(retrieve.ingest(bundle, output, embedder), {"records": 1, "reused": True})
        result = retrieve.search(output, "ownership", embedder)
        hit = result["hits"][0]
        self.assertEqual(hit["candidate"], report["questions"][0]["candidate"])
        self.assertEqual(hit["passages"], report["passages"])
        self.assertLess(abs(hit["distance"]), 0.00001)
        self.assertIn("In this sample.", retrieve.render(result))
        changed = copy.deepcopy(bundle)
        changed["records"][0]["candidate"]["question"] = "Changed?"
        with self.assertRaises(prepare.PreparationError):
            retrieve.ingest(changed, output, embedder)
        embedder.spec = {**embedder.spec, "revision": "2"}
        with self.assertRaises(prepare.PreparationError):
            retrieve.search(output, "ownership", embedder)

    @unittest.skipUnless(importlib.util.find_spec("lancedb"), "Install retrieval requirements for real LanceDB tests")
    def test_failed_embedding_leaves_no_partial_index(self):
        directory, _ = self.fixture()
        bundle = retrieve.select_reports([directory])
        embedder = FakeEmbedder()
        embedder.encode = lambda texts: [[1., 0.]]
        output = self.root / "index"
        with self.assertRaises(prepare.PreparationError):
            retrieve.ingest(bundle, output, embedder)
        self.assertFalse(output.exists())
        self.assertFalse(list(self.root.glob(".index-*")))
        with patch("retrieve.atomic_write", side_effect=OSError("Simulated disk failure")):
            with self.assertRaises(OSError):
                retrieve.ingest(bundle, output, FakeEmbedder())
        self.assertFalse(output.exists())
        self.assertFalse(list(self.root.glob(".index-*")))


if __name__ == "__main__":
    unittest.main()
