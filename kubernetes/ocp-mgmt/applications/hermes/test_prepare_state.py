import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from prepare_state import prepare_state


class StatePreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.volume = Path(self.temp.name)

    def test_fresh_home_is_private_and_owned_by_process(self):
        (self.volume / "lost+found").mkdir()
        home = prepare_state(self.volume)
        self.assertEqual(home.stat().st_uid, os.getuid())
        self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o700)
        self.assertTrue((self.volume / "lost+found").is_dir())

    def test_migration_preserves_files_wal_and_workspace_in_place(self):
        (self.volume / "workspace").mkdir()
        (self.volume / "workspace" / "task.txt").write_text("user work")
        contents = {"config.yaml": "user config", "state.db": "db",
                    "state.db-wal": "wal", ".hermes_history": "history"}
        inodes = {}
        for name, value in contents.items():
            (self.volume / name).write_text(value)
            inodes[name] = (self.volume / name).stat().st_ino
        home = prepare_state(self.volume)
        for name, value in contents.items():
            self.assertEqual((home / name).read_text(), value)
            self.assertEqual((home / name).stat().st_ino, inodes[name])
        self.assertEqual((home / "workspace" / "task.txt").read_text(), "user work")
        self.assertEqual(prepare_state(self.volume), home)

    def test_conflicting_state_fails_before_any_move(self):
        home = prepare_state(self.volume)
        (home / "config.yaml").write_text("private")
        (self.volume / "state.db").write_text("legacy db")
        (self.volume / "config.yaml").write_text("legacy config")
        with self.assertRaisesRegex(ValueError, "overlap"):
            prepare_state(self.volume)
        self.assertEqual((home / "config.yaml").read_text(), "private")
        self.assertEqual((self.volume / "state.db").read_text(), "legacy db")

    def test_interrupted_migration_resumes(self):
        for name in ("state.db", "state.db-wal", "config.yaml"):
            (self.volume / name).write_text(name)
        original = Path.rename
        calls = 0

        def interrupted(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated interruption")
            return original(source, destination)

        with patch.object(Path, "rename", interrupted):
            with self.assertRaises(OSError):
                prepare_state(self.volume)
        home = prepare_state(self.volume)
        for name in ("state.db", "state.db-wal", "config.yaml"):
            self.assertEqual((home / name).read_text(), name)

    def test_symlink_home_is_rejected_without_changing_target(self):
        outside = self.volume / "outside"
        outside.mkdir(mode=0o755)
        (self.volume / "hermes-home").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            prepare_state(self.volume)
        self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o755)

    def test_foreign_owner_is_rejected(self):
        home = prepare_state(self.volume)
        with patch("prepare_state.os.getuid", return_value=home.stat().st_uid + 1):
            with self.assertRaisesRegex(ValueError, "application UID"):
                prepare_state(self.volume)


if __name__ == "__main__":
    unittest.main()
