import contextlib
from datetime import datetime
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

import lessons


class LessonsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.token = self.directory / "token"
        self.token.write_text("test-token")
        self.env = patch.dict(os.environ, {
            "STATE_DIR": str(self.directory), "LLM_TOKEN_FILE": str(self.token),
            "LLM_BASE_URL": "https://llm.test/v1", "LESSON_TIMEZONE": "America/Toronto",
            "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/123/test-secret",
            "TRANSCRIPT_CACHE_DIR": str(self.directory),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        (self.directory / "episode-headings.txt").write_text(
            f"{'a' * 40}:transcripts/groups_of_20/episodes_00041_to_00060.md:57:## Episode 42\n"
            f"{'a' * 40}:transcripts/groups_of_20/episodes_00081_to_00101.md:7500:## Episode 101\n"
            f"{'a' * 40}:transcripts/groups_of_20/episodes_00102_to_00123.md:1:## Episode 102\n")
        self.path = self.directory / "history.json"
        self.day = datetime.now(ZoneInfo("America/Toronto")).date().isoformat()
        self.excerpt = {"episode": 42, "key": "42:abc", "start": 3, "end": 9,
                        "text": "A strategy should match your ability to stay invested through uncertainty."}
        self.lesson = {"title": "Staying invested", "explanation": "A useful explanation.",
                       "takeaway": "Write down your reasoning.", "reflection": "What might change your plan?",
                       "evidence": "A strategy should match your ability to stay invested"}
        self.entry = {"status": "prepared", "episode": 42, "key": "42:abc",
                      "title": self.lesson["title"], "payload": lessons.make_payload(
                          self.lesson, self.excerpt, "a" * 40, self.day)}

    def model_response(self, lesson=None, reason="stop"):
        return json.dumps({"choices": [{"finish_reason": reason, "message": {
            "content": json.dumps(self.lesson if lesson is None else lesson)}}]})

    def test_parse_canonical_headings_missing_episodes_and_long_paragraphs(self):
        text = "# Collection\n\n## Episode 1\n" + "a" * 15000 + "\n\n## Episode 3\n" + "b" * 500
        chunks = lessons.excerpts(text)
        self.assertEqual([c["episode"] for c in chunks], [1, 1, 3])
        self.assertTrue(all(len(c["text"]) <= lessons.MAX_EXCERPT for c in chunks))
        for chunk in chunks:
            source = "\n".join(text.splitlines()[chunk["start"] - 1:chunk["end"]])
            self.assertIn(chunk["text"], source)
        self.assertEqual(chunks, lessons.excerpts(text))

    def test_empty_source_fails_closed(self):
        with self.assertRaises(lessons.LessonError):
            lessons.excerpts("No transcripts here")

    def test_rotate_episodes_before_reusing_chunks(self):
        history = {"2026-10-01": self.entry | {"status": "sent"}}
        fresh = self.excerpt | {"episode": 43, "key": "43:def"}
        self.assertEqual(lessons.choose([self.excerpt, fresh], history, self.day), fresh)
        history["2026-10-01"]["status"] = "sending"
        self.assertEqual(lessons.choose([self.excerpt, fresh], history, self.day), fresh)
        other_chunk = self.excerpt | {"key": "42:unused"}
        self.assertEqual(lessons.choose([self.excerpt, other_chunk], history, self.day), other_chunk)

    def test_model_auth_and_grounding(self):
        with patch.object(lessons, "request", return_value=self.model_response()) as request:
            self.assertEqual(lessons.generate(self.excerpt, {}), self.lesson)
        self.assertEqual(request.call_args.kwargs["token"], "test-token")
        payload = request.call_args.kwargs["payload"]
        self.assertIn(self.excerpt["text"], payload["messages"][1]["content"])
        self.assertNotIn("test-secret", json.dumps(payload))

    def test_reject_invented_quotes_links_and_truncated_output(self):
        for update, reason in [({"evidence": "This quotation does not occur in the transcript"}, "stop"),
                               ({"takeaway": "Go to https://example.com"}, "stop"), ({}, "length")]:
            with self.subTest(update=update, reason=reason), patch.object(
                    lessons, "request", return_value=self.model_response(self.lesson | update, reason)):
                with self.assertRaises(lessons.LessonError):
                    lessons.generate(self.excerpt, {})

    def test_skip_housekeeping(self):
        with patch.object(lessons, "request", return_value=self.model_response({"skip": True})):
            self.assertIsNone(lessons.generate(self.excerpt, {}))

    def test_payload_has_pinned_source_and_disables_mentions(self):
        payload = lessons.make_payload(self.lesson, self.excerpt, "a" * 40, self.day)
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertIn("/blob/" + "a" * 40, payload["embeds"][0]["url"])
        source = payload["embeds"][0]["url"]
        self.assertTrue(source.endswith("/transcripts/groups_of_20/episodes_00041_to_00060.md?plain=1#L57"))
        self.assertIn(f"[Episode transcript]({source})", payload["embeds"][0]["fields"][0]["value"])
        self.assertNotIn("all.md", json.dumps(payload))
        self.assertIn("**Reflect**", payload["embeds"][0]["description"])

    def test_group_links_use_real_ranges_across_missing_episode_numbers(self):
        self.assertTrue(lessons.transcript_url(101, "a" * 40).endswith(
            "episodes_00081_to_00101.md?plain=1#L7500"))
        self.assertTrue(lessons.transcript_url(102, "a" * 40).endswith(
            "episodes_00102_to_00123.md?plain=1#L1"))
        with self.assertRaises(lessons.LessonError):
            lessons.transcript_url(999, "a" * 40)

    def test_ambiguous_group_does_not_emit_broken_link(self):
        with (self.directory / "episode-headings.txt").open("a") as handle:
            handle.write(f"{'a' * 40}:transcripts/groups_of_20/episodes_00040_to_00059.md:23:## Episode 42\n")
        with self.assertRaises(lessons.LessonError):
            lessons.transcript_url(42, "a" * 40)

    def test_webhook_wait_preserves_thread_and_rejects_other_hosts(self):
        value = lessons.webhook_url(os.environ["DISCORD_WEBHOOK_URL"] + "?thread_id=456&wait=false")
        self.assertTrue(value.endswith("thread_id=456&wait=true"))
        for value in ("http://discord.com/api/webhooks/123/x", "https://evil.test/api/webhooks/123/x"):
            with self.assertRaises(lessons.LessonError):
                lessons.webhook_url(value)

    def test_success_saves_confirmation_and_rerun_does_not_post(self):
        output = io.StringIO()
        with patch.object(lessons, "prepare", return_value=self.entry), patch.object(
                lessons, "request", return_value='{"id":"12345"}') as request, contextlib.redirect_stdout(output):
            lessons.run()
            lessons.run()
        request.assert_called_once()
        self.assertEqual(json.loads(self.path.read_text())[self.day]["message_id"], "12345")
        for value in self.lesson.values():
            self.assertIn(value, output.getvalue())
        self.assertIn("Episode transcript", output.getvalue())
        self.assertIn("Discord message ID 12345", output.getvalue())
        self.assertIn("already delivered; skipping", output.getvalue())
        self.assertNotIn("test-secret", output.getvalue())
        self.assertNotIn("test-token", output.getvalue())

    def test_ambiguous_delivery_is_persisted_and_not_retried(self):
        output = io.StringIO()
        def disconnect(*args, **kwargs):
            self.assertEqual(json.loads(self.path.read_text())[self.day]["status"], "sending")
            self.assertIn(self.lesson["explanation"], output.getvalue())
            raise lessons.LessonError("connection lost")
        with patch.object(lessons, "prepare", return_value=self.entry), patch.object(
                lessons, "request", side_effect=disconnect) as request, contextlib.redirect_stdout(output):
            with self.assertRaises(lessons.LessonError):
                lessons.run()
            with self.assertRaisesRegex(lessons.LessonError, "unconfirmed"):
                lessons.run()
        request.assert_called_once()

    def test_distinct_test_jobs_send_extra_lessons_and_preserve_daily_history(self):
        daily = self.entry | {"status": "sent", "message_id": "daily-message"}
        lessons.save(self.path, {self.day: daily})
        with patch.object(lessons, "prepare", side_effect=lambda *args: json.loads(json.dumps(self.entry))) as prepare, \
                patch.object(lessons, "request", return_value='{"id":"test-message"}') as request:
            with patch.dict(os.environ, {"LESSON_RUN_ID": "test-a"}):
                lessons.run(allow_duplicate=True)
                lessons.run(allow_duplicate=True)  # Retrying the same Job does not send twice.
            with patch.dict(os.environ, {"LESSON_RUN_ID": "test-b"}):
                lessons.run(allow_duplicate=True)
            lessons.run()  # The normal daily run still skips today's confirmed delivery.
        self.assertEqual(request.call_count, 2)
        self.assertEqual(prepare.call_count, 2)
        history = json.loads(self.path.read_text())
        self.assertEqual(history[self.day], daily)
        self.assertEqual(len(history), 3)
        for key in (f"{self.day}/test-test-a", f"{self.day}/test-test-b"):
            self.assertTrue(history[key]["test_run"])
            self.assertEqual(history[key]["status"], "sent")

    def test_test_lesson_does_not_consume_normal_daily_delivery(self):
        with patch.object(lessons, "prepare", side_effect=lambda *args: json.loads(json.dumps(self.entry))), \
                patch.object(lessons, "request", return_value='{"id":"123"}') as request, \
                patch.dict(os.environ, {"LESSON_RUN_ID": "test-a"}):
            lessons.run(allow_duplicate=True)
            self.assertNotIn(self.day, json.loads(self.path.read_text()))
            lessons.run()
        self.assertEqual(request.call_count, 2)
        self.assertEqual(len(json.loads(self.path.read_text())), 2)

    def test_unconfirmed_test_delivery_is_not_retried_with_same_job_id(self):
        with patch.object(lessons, "prepare", return_value=self.entry), \
                patch.object(lessons, "request", side_effect=lessons.LessonError("connection lost")) as request, \
                patch.dict(os.environ, {"LESSON_RUN_ID": "test-a"}):
            with self.assertRaises(lessons.LessonError):
                lessons.run(allow_duplicate=True)
            with self.assertRaisesRegex(lessons.LessonError, "unconfirmed"):
                lessons.run(allow_duplicate=True)
        request.assert_called_once()

    def test_duplicate_mode_cli_and_environment_are_opt_in(self):
        for argv, value, expected in ((["lessons.py"], "false", False),
                                      (["lessons.py", "--allow-duplicate"], "false", True),
                                      (["lessons.py"], "true", True)):
            with self.subTest(argv=argv, value=value), patch.object(lessons.sys, "argv", argv), \
                    patch.dict(os.environ, {"ALLOW_DUPLICATE_LESSONS": value}), \
                    patch.object(lessons, "run") as run:
                self.assertEqual(lessons.main(), 0)
                run.assert_called_once_with(False, None, expected)

    def test_unconfirmed_response_does_not_mark_sent(self):
        with patch.object(lessons, "prepare", return_value=self.entry), patch.object(
                lessons, "request", return_value="{}"):
            with self.assertRaises(lessons.LessonError):
                lessons.run()
        self.assertEqual(json.loads(self.path.read_text())[self.day]["status"], "sending")

    def test_generation_failure_can_retry_without_consuming_day(self):
        with patch.object(lessons, "prepare", side_effect=lessons.LessonError("model down")):
            with self.assertRaises(lessons.LessonError):
                lessons.run()
        self.assertFalse(self.path.exists())

    def test_preview_never_posts_or_writes_history(self):
        output, progress = io.StringIO(), io.StringIO()
        def prepare(*args):
            lessons.log("Preparing preview")
            return self.entry
        with patch.object(lessons, "prepare", side_effect=prepare), patch.object(
                lessons, "request") as request, contextlib.redirect_stdout(output), contextlib.redirect_stderr(progress):
            lessons.run(preview=True)
        request.assert_not_called()
        self.assertFalse(self.path.exists())
        self.assertEqual(json.loads(output.getvalue()), self.entry["payload"])
        self.assertIn("Preparing preview", progress.getvalue())

    def test_http_errors_do_not_leak_webhook(self):
        url = os.environ["DISCORD_WEBHOOK_URL"]
        with patch.object(lessons, "urlopen", side_effect=HTTPError(url, 429, url, {}, None)):
            with self.assertRaises(lessons.LessonError) as error:
                lessons.request(url, payload={})
        self.assertRegex(str(error.exception), r"HTTP request failed \(status 429, after [\d.]+s\)")

    def test_http_failure_identifies_service_without_logging_credentials(self):
        for service in ("Inference", "Discord"):
            with self.subTest(service=service):
                url = os.environ["DISCORD_WEBHOOK_URL"]
                output = io.StringIO()
                with patch.object(lessons, "urlopen", side_effect=HTTPError(url, 403, url, {}, None)), \
                        contextlib.redirect_stdout(output), self.assertRaises(lessons.LessonError) as error:
                    lessons.request(url, token="test-token", payload={"secret": "test-secret"}, service=service)
                self.assertIn(f"{service} request started", output.getvalue())
                self.assertIn(f"{service} request failed (status 403", str(error.exception))
                for secret in (url, "test-token", "test-secret"):
                    self.assertNotIn(secret, output.getvalue() + str(error.exception))


if __name__ == "__main__":
    unittest.main()
