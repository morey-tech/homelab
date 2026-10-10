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
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.path = self.directory / "history.json"
        self.day = datetime.now(ZoneInfo("America/Toronto")).date().isoformat()
        self.excerpt = {"episode": 42, "key": "42:abc", "start": 3, "end": 9,
                        "text": "A strategy should match your ability to stay invested through uncertainty."}
        self.lesson = {"title": "Staying invested", "explanation": "A useful explanation.",
                       "takeaway": "Write down your reasoning.", "reflection": "What might change your plan?",
                       "evidence": "A strategy should match your ability to stay invested"}
        self.entry = {"status": "prepared", "episode": 42, "key": "42:abc",
                      "title": self.lesson["title"], "payload": {"embeds": []}}

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
        self.assertTrue(payload["embeds"][0]["url"].endswith("#L3-L9"))
        self.assertIn("**Reflect**", payload["embeds"][0]["description"])

    def test_webhook_wait_preserves_thread_and_rejects_other_hosts(self):
        value = lessons.webhook_url(os.environ["DISCORD_WEBHOOK_URL"] + "?thread_id=456&wait=false")
        self.assertTrue(value.endswith("thread_id=456&wait=true"))
        for value in ("http://discord.com/api/webhooks/123/x", "https://evil.test/api/webhooks/123/x"):
            with self.assertRaises(lessons.LessonError):
                lessons.webhook_url(value)

    def test_success_saves_confirmation_and_rerun_does_not_post(self):
        with patch.object(lessons, "prepare", return_value=self.entry), patch.object(
                lessons, "request", return_value='{"id":"12345"}') as request:
            lessons.run()
            lessons.run()
        request.assert_called_once()
        self.assertEqual(json.loads(self.path.read_text())[self.day]["message_id"], "12345")

    def test_ambiguous_delivery_is_persisted_and_not_retried(self):
        def disconnect(*args, **kwargs):
            self.assertEqual(json.loads(self.path.read_text())[self.day]["status"], "sending")
            raise lessons.LessonError("connection lost")
        with patch.object(lessons, "prepare", return_value=self.entry), patch.object(
                lessons, "request", side_effect=disconnect) as request:
            with self.assertRaises(lessons.LessonError):
                lessons.run()
            with self.assertRaisesRegex(lessons.LessonError, "unconfirmed"):
                lessons.run()
        request.assert_called_once()

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
        with patch.object(lessons, "prepare", return_value=self.entry), patch.object(
                lessons, "request") as request, contextlib.redirect_stdout(io.StringIO()):
            lessons.run(preview=True)
        request.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_http_errors_do_not_leak_webhook(self):
        url = os.environ["DISCORD_WEBHOOK_URL"]
        with patch.object(lessons, "urlopen", side_effect=HTTPError(url, 429, url, {}, None)):
            with self.assertRaises(lessons.LessonError) as error:
                lessons.request(url, payload={})
        self.assertEqual(str(error.exception), "HTTP request failed (status 429)")


if __name__ == "__main__":
    unittest.main()
