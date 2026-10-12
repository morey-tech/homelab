import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import prepare


def response(content, finish="stop"):
    return {"choices": [{"finish_reason": finish, "message": {"content": json.dumps(content)}}]}


class FakeModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def complete(self, messages, schema):
        self.calls += 1
        return next(self.responses)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))

    def repo(self, text="## Episode 1\n\nHost: Why?\n\nGuest: Because of the tradeoff."):
        repo = self.root / "repo"
        repo.mkdir()
        self.file = repo / "transcripts/individual/episode_1.md"
        self.file.parent.mkdir(parents=True)
        self.file.write_text(text)
        for args in (("init", "-q"), ("add", "."), ("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")):
            subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
        return repo

    def report(self, body="Host: Why does this matter?\n\nGuest: Tradeoffs need context."):
        text = "## Episode 1\n\n" + body
        source = {"episode": 1, "commit": "a" * 40, "sha256": prepare.digest(text.encode()),
                  "transcript_url": "https://github.com/morey-tech/rr-scraper/blob/" + "a" * 40 + "/transcripts/individual/episode_1.md"}
        items = prepare.passages(source, text, len("## Episode 1"))
        return {"source": source, "passages": items, "sections": prepare.sections(items), "status": "prepared"}

    def question(self, report):
        ids = [p["id"] for p in report["passages"]]
        return {"concept": "Tradeoffs", "question": "Why do tradeoffs need context?",
                "answer_outline": [{"claim": "The guest says tradeoffs need context.", "passage_ids": [ids[-1]]}],
                "context_ids": [ids[0]], "qualifications": [], "prerequisites": []}

    def test_reads_pinned_git_objects_not_dirty_checkout(self):
        repo = self.repo()
        original = self.file.read_bytes()
        self.file.write_text("Dirty local changes")
        source, text, _ = prepare.read_source(repo, "HEAD", 1)
        self.assertEqual(text.encode(), original)
        self.assertEqual(source["sha256"], prepare.digest(original))
        self.assertRegex(source["commit"], r"^[0-9a-f]{40}$")
        self.assertIsNone(source["publication_date"])
        with self.assertRaises(prepare.PreparationError):
            prepare.read_source(repo, "HEAD", 2)
        with self.assertRaises(prepare.PreparationError):
            prepare.read_source(repo, "--bad-option", 1)

    def test_wrong_or_multiple_episode_headings_fail(self):
        repo = self.repo("## Episode 1\n\nBody\n\n## Episode 2\n\nOther")
        with self.assertRaises(prepare.PreparationError):
            prepare.read_source(repo, "HEAD", 1)

    def test_source_offsets_unicode_speaker_and_long_paragraph_coverage(self):
        body = "Host: Why café investing?\n\nGuest: " + "An answer. " * 900 + "\n\nA continuation."
        report = self.report(body)
        text = "## Episode 1\n\n" + body
        items = report["passages"]
        reconstructed = "".join(p["text"] for p in items)
        self.assertEqual("".join(reconstructed.split()), "".join(body.split()))
        self.assertEqual(items[-1]["speaker_hint"], "Guest")
        self.assertFalse(items[-1]["speaker_label_in_passage"])
        for p in items:
            self.assertEqual(p["text"], text[p["start_char"]:p["end_char"]])
            self.assertLessEqual(len(p["text"]), prepare.MAX_PASSAGE)
            self.assertEqual(p["start_line"], text[:p["start_char"]].count("\n") + 1)
        self.assertEqual(items, self.report(body)["passages"])
        focused = [key for s in report["sections"] for key in s["focus_ids"]]
        self.assertEqual(focused, [p["id"] for p in items])
        self.assertIn(items[0]["id"], prepare.expand([items[1]["id"]], items))

    def test_fabricated_evidence_and_context_are_rejected(self):
        report = self.report()
        ids = [p["id"] for p in report["passages"]]
        question = self.question(report)
        prepare.validate_question(question, ids, ids)
        question["answer_outline"][0]["passage_ids"] = ["invented"]
        with self.assertRaisesRegex(prepare.PreparationError, "not supplied"):
            prepare.validate_question(question, ids, ids)
        question = self.question(report)
        question["context_ids"] = ["invented"]
        with self.assertRaises(prepare.PreparationError):
            prepare.validate_question(question, ids, ids)
        question = self.question(report)
        with self.assertRaisesRegex(prepare.PreparationError, "focus"):
            prepare.validate_question(question, ids, [ids[0]])

    def test_trailing_unicode_whitespace_does_not_merge_speaker_turns(self):
        report = self.report("Host: Question?\u00a0\n\nGuest: Answer.\u00a0\n\nMore explanation.  \n\nHost: Next?")
        items = report["passages"]
        self.assertEqual([p["speaker_hint"] for p in items], ["Host", "Guest", "Guest", "Host"])
        self.assertEqual([p["text"] for p in items], ["Host: Question?", "Guest: Answer.", "More explanation.", "Host: Next?"])

    def test_review_requires_real_booleans_and_all_checks(self):
        review = {"supported": True, "context_sufficient": False, "teachable": True, "reason": "Missing qualification", "confidence": "low", "confidence_reason": "Missing surrounding evidence"}
        self.assertFalse(prepare.validate_review(review))
        review["supported"] = "true"
        with self.assertRaises(prepare.PreparationError):
            prepare.validate_review(review)

    def test_full_pipeline_checkpoints_and_human_review_gate(self):
        report = self.report()
        review = {"supported": True, "context_sufficient": True, "teachable": True, "reason": "Supported in context", "confidence": "high", "confidence_reason": "Both statements are explicit in the supplied discussion"}
        q = self.question(report)
        model = FakeModel([response({"questions": [q, q]}), response(review)])
        output = self.root / "run"
        prompts = {"extract": "extract prompt", "review": "review prompt"}
        prepare.evaluate(report, model, output, prompts, 0)
        self.assertEqual(model.calls, 2)
        self.assertEqual(report["status"], "needs_human_review")
        self.assertEqual(report["questions"][0]["human_review"], "pending")
        self.assertEqual(report["questions"][0]["review"]["confidence"], "high")
        rendered = (output / "report.md").read_text()
        self.assertIn("— needs_human_review — High confidence", rendered)
        self.assertLess(rendered.index(q["question"]),
                        rendered.index("Model confidence in source faithfulness: High"))
        self.assertEqual(report["questions"][1]["status"], "duplicate")
        self.assertIn("Guest: Tradeoffs need context.", (output / "report.md").read_text())
        cached = FakeModel([])
        prepare.evaluate(report, cached, output, prompts, 0)
        self.assertEqual(cached.calls, 0)

    def test_confidence_is_required_validated_and_cannot_override_failed_checks(self):
        valid = {"supported": True, "context_sufficient": True, "teachable": True,
                 "reason": "Supported", "confidence": "medium", "confidence_reason": "Attribution needs checking"}
        for value in (None, 0.9, True, [], "certain"):
            with self.subTest(confidence=value), self.assertRaises(prepare.PreparationError):
                prepare.validate_review({**valid, "confidence": value})
        with self.assertRaises(prepare.PreparationError):
            prepare.validate_review({**valid, "confidence_reason": ""})
        with self.assertRaises(prepare.PreparationError):
            prepare.validate_review({**valid, "supported": False, "confidence": "high"})
        with self.assertRaises(prepare.PreparationError):
            prepare.validate_review({k: v for k, v in valid.items() if k != "confidence"})

    def test_every_confidence_level_preserves_human_review(self):
        for level in ("low", "medium", "high"):
            with self.subTest(level=level):
                report = self.report()
                review = {"supported": True, "context_sufficient": True, "teachable": True,
                          "reason": "Candidate is supported", "confidence": level,
                          "confidence_reason": "A model assessment requiring human confirmation"}
                model = FakeModel([response({"questions": [self.question(report)]}), response(review)])
                prepare.evaluate(report, model, self.root / level, {"extract": "a", "review": "b"}, 0)
                self.assertEqual(report["questions"][0]["status"], "needs_human_review")
                self.assertEqual(report["questions"][0]["human_review"], "pending")

    def test_legacy_report_does_not_invent_confidence(self):
        report = self.report()
        report["questions"] = [{"id": "old-q1", "candidate": self.question(report),
                                 "status": "needs_human_review", "review": {"reason": "Old review"}}]
        prepare.save_report(self.root, report)
        self.assertIn("Model confidence: Not assessed", (self.root / "report.md").read_text())

    def test_truncated_output_is_retained_and_episode_is_partial(self):
        report = self.report()
        model = FakeModel([response({"questions": []}, finish="length")])
        output = self.root / "run"
        prepare.evaluate(report, model, output, {"extract": "extract", "review": "review"}, 0)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(len(report["failures"]), 1)
        self.assertEqual(len(list((output / "responses").glob("*.json"))), 1)

    def test_rejected_model_review_is_not_accepted(self):
        report = self.report()
        model = FakeModel([response({"questions": [self.question(report)]}), response({
            "supported": False, "context_sufficient": True, "teachable": True, "reason": "Claim contradicts evidence", "confidence": "low", "confidence_reason": "The central claim contradicts the cited source"})])
        prepare.evaluate(report, model, self.root / "run", {"extract": "a", "review": "b"}, 0)
        self.assertEqual(report["questions"][0]["status"], "rejected")
        self.assertEqual(report["questions"][0]["rejection_reason"], "Claim contradicts evidence")
        rendered = (self.root / "run/report.md").read_text()
        self.assertIn("**Why rejected:** Claim contradicts evidence", rendered)
        self.assertIn("**Reviewer checks that failed:** source support", rendered)
        self.assertIn("— rejected — Low confidence", rendered)

    def test_invalid_review_keeps_explanation_question_and_source_context(self):
        report = self.report()
        review = {"supported": False, "context_sufficient": True, "teachable": True,
                  "reason": "The answer adds causation absent from the source", "confidence": "high",
                  "confidence_reason": "An inconsistent model assessment"}
        model = FakeModel([response({"questions": [self.question(report)]}), response(review)])
        prepare.evaluate(report, model, self.root / "run", {"extract": "a", "review": "b"}, 0)
        entry = report["questions"][0]
        self.assertEqual(entry["status"], "rejected")
        self.assertEqual(entry["review"], review)
        rendered = (self.root / "run/report.md").read_text()
        self.assertIn("**Why rejected:** A failed review must have low confidence", rendered)
        self.assertIn("The answer adds causation absent from the source", rendered)
        self.assertIn("Reported confidence: high (not validated)", rendered)
        self.assertIn("— rejected — High confidence (unvalidated)", rendered)
        self.assertLess(rendered.index("Why do tradeoffs need context?"), rendered.index("**Why rejected:**"))
        self.assertIn("Why do tradeoffs need context?", rendered)
        self.assertIn("Guest: Tradeoffs need context.", rendered)

    def test_malformed_candidate_shows_reason_and_original_output(self):
        report = self.report()
        model = FakeModel([response({"questions": [{"question": "Incomplete question"}]})])
        prepare.evaluate(report, model, self.root / "run", {"extract": "a", "review": "b"}, 0)
        rendered = (self.root / "run/report.md").read_text()
        self.assertIn("**Why rejected:** Question fields do not match", rendered)
        self.assertIn("Original candidate:", rendered)
        self.assertIn("Incomplete question", rendered)

    def test_section_limit_cannot_produce_complete_report(self):
        report = self.report("Host: " + "Large discussion. " * 1600)
        model = FakeModel([response({"questions": []})])
        prepare.evaluate(report, model, self.root / "run", {"extract": "a", "review": "b"}, 1)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["completed_sections"], 1)

    def test_context_budget_checks_happen_before_generation(self):
        model = prepare.Model(prepare.DEFAULT_URL, "local-llm", "secret")
        with patch.object(model, "post", return_value={"count": prepare.CONTEXT_LIMIT}) as post:
            with self.assertRaisesRegex(prepare.PreparationError, "context budget"):
                model.complete([], {})
            self.assertEqual(post.call_count, 1)
        with self.assertRaises(prepare.PreparationError):
            prepare.Model("http://example.com/v1", "model", "secret")

    def test_prepare_only_and_changed_manifest_guard(self):
        repo = self.repo()
        output = self.root / "output"
        args = ["prepare.py", "--repo", str(repo), "--revision", "HEAD", "--episode", "1",
                "--output", str(output), "--prepare-only"]
        with patch("sys.argv", args), patch.object(prepare.Model, "complete", side_effect=AssertionError("Inference used")):
            self.assertEqual(prepare.main(), 0)
        self.assertEqual(json.loads((output / "report.json").read_text())["status"], "prepared")
        with patch("sys.argv", [*args, "--model-revision", "changed"]):
            with self.assertRaisesRegex(prepare.PreparationError, "different source"):
                prepare.main()


if __name__ == "__main__":
    unittest.main()
