"""Exercise the actual sync script against a local Git origin, without network access."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import lessons


SCRIPT = Path(__file__).with_name("sync-transcripts.sh")


class TranscriptCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.origin = self.root / "origin"
        self.cache = self.root / "cache"
        self.origin.mkdir()
        self.git("init", "--initial-branch=master")
        (self.origin / "transcripts").mkdir()
        self.source = self.origin / "transcripts/all.md"
        self.source.write_text("## Episode 1\n\n" + "An educational transcript. " * 30)
        self.groups = self.origin / "transcripts/groups_of_20"
        self.groups.mkdir()
        (self.groups / "episodes_00001_to_00001.md").write_text(self.source.read_text())
        (self.origin / "unrelated.txt").write_text("Not checked out")
        self.commit()
        self.env = os.environ | {"TRANSCRIPT_CACHE_DIR": str(self.cache),
                                 "TRANSCRIPT_REPO_URL": self.origin.as_uri()}

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.origin), "-c", "user.name=Cache Test",
                               "-c", "user.email=cache@example.invalid", *args],
                              check=True, capture_output=True, text=True).stdout.strip()

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-m", "Update transcript fixture")
        return self.git("rev-parse", "HEAD")

    def sync(self, check=True, **env):
        return subprocess.run(["sh", str(SCRIPT)], env=self.env | env, check=check,
                              capture_output=True, text=True)

    def test_initial_fetch_unchanged_rerun_and_incremental_update(self):
        self.sync()
        snapshot = self.cache / "all.md"
        revision = self.cache / "revision"
        first_revision = revision.read_text()
        self.assertEqual(first_revision.strip(), self.git("rev-parse", "HEAD"))
        self.assertEqual(snapshot.read_text(), self.source.read_text())
        self.assertFalse((self.cache / "unrelated.txt").exists())
        # Neither the snapshot nor Git object store should be replaced on an unchanged run.
        before = snapshot.stat().st_mtime_ns
        object_store_inode = (self.cache / "repository.git/objects").stat().st_ino
        self.assertIn("unchanged", self.sync().stdout)
        self.assertEqual(snapshot.stat().st_mtime_ns, before)
        self.source.write_text(self.source.read_text() + "\n## Episode 2\nNew material.\n")
        (self.groups / "episodes_00001_to_00001.md").unlink()
        (self.groups / "episodes_00001_to_00002.md").write_text(self.source.read_text())
        second_revision = self.commit()
        self.sync()
        self.assertEqual(revision.read_text().strip(), second_revision)
        self.assertNotEqual(revision.read_text(), first_revision)
        self.assertEqual(snapshot.read_text(), self.source.read_text())
        self.assertEqual((self.cache / "repository.git/objects").stat().st_ino, object_store_inode)
        self.assertTrue((self.cache / "repository.git/shallow").exists())
        index = (self.cache / "episode-headings.txt").read_text()
        self.assertIn(f"{second_revision}:transcripts/groups_of_20/episodes_00001_to_00002.md:1:## Episode 1", index)
        self.assertNotIn("episodes_00001_to_00001.md", index)

    def test_existing_cache_gains_group_index_without_upstream_change(self):
        self.sync()
        (self.cache / "episode-headings.txt").unlink()
        revision = (self.cache / "revision").read_text()
        self.sync()
        self.assertEqual((self.cache / "revision").read_text(), revision)
        with patch.dict(os.environ, self.env):
            self.assertTrue(lessons.transcript_url(1, revision.strip()).endswith(
                "episodes_00001_to_00001.md?plain=1#L1"))

    def test_failed_fetch_preserves_cache_but_fails_init(self):
        self.sync()
        revision = (self.cache / "revision").read_text()
        snapshot = (self.cache / "all.md").read_text()
        result = self.sync(check=False, TRANSCRIPT_REPO_URL=(self.root / "missing").as_uri())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.cache / "revision").read_text(), revision)
        self.assertEqual((self.cache / "all.md").read_text(), snapshot)

    def test_missing_transcript_does_not_publish_new_revision(self):
        self.sync()
        revision = (self.cache / "revision").read_text()
        self.source.unlink()
        self.commit()
        self.assertNotEqual(self.sync(check=False).returncode, 0)
        self.assertEqual((self.cache / "revision").read_text(), revision)

    def test_resume_initialized_cache_after_interrupted_first_fetch(self):
        self.cache.mkdir()
        subprocess.run(["git", "init", "--bare", str(self.cache / "repository.git")],
                       check=True, capture_output=True)
        self.sync()
        self.assertEqual((self.cache / "all.md").read_text(), self.source.read_text())

    def test_python_reads_snapshot_without_network_and_validates_revision(self):
        self.sync()
        with patch.dict(os.environ, self.env), patch.object(lessons, "request") as request:
            text, revision = lessons.read_transcripts()
            self.assertEqual(text, self.source.read_text())
            self.assertEqual(revision, self.git("rev-parse", "HEAD"))
            request.assert_not_called()
            (self.cache / "revision").write_text("invalid")
            with self.assertRaises(lessons.LessonError):
                lessons.read_transcripts()

    def test_python_rejects_empty_cache(self):
        self.sync()
        (self.cache / "all.md").write_text("")
        with patch.dict(os.environ, self.env), self.assertRaises(lessons.LessonError):
            lessons.read_transcripts()


if __name__ == "__main__":
    unittest.main()
