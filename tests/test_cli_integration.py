"""End-to-end tests that exercise the installed CLI process through stdin/stdout."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cree_filesystem import FileSystem


class TestCLIProcessWorkflows(unittest.TestCase):
    """Verify real command-loop workflows, not only direct onecmd calls."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.workdir = Path(self._tmpdir.name)
        self.storage = self.workdir / "state" / "filesystem.json"
        self.repo_root = Path(__file__).resolve().parent.parent
        self.env = {
            **os.environ,
            "PYTHONPATH": str(self.repo_root / "src"),
            "PYTHONUNBUFFERED": "1",
        }

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def run_cli(self, commands: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "cree_filesystem",
                "--storage",
                str(self.storage),
                *(["--fresh"] if not self.storage.exists() else []),
            ],
            input="\n".join(commands) + "\n",
            text=True,
            capture_output=True,
            cwd=self.workdir,
            env=self.env,
            timeout=10,
            check=False,
        )

    def test_real_cli_workflow_and_persistence_across_processes(self) -> None:
        first = self.run_cli(
            [
                "groupadd engineering",
                "useradd alice",
                "usermod -aG engineering alice",
                'mkdir -p "/srv/project files/logs"',
                'touch "/srv/project files/logs/app.log"',
                'write "/srv/project files/logs/app.log" "first entry"',
                'append "/srv/project files/logs/app.log" " second entry"',
                'chown alice:engineering "/srv/project files/logs/app.log"',
                'chmod 640 "/srv/project files/logs/app.log"',
                'cd "/srv/project files"',
                "pwd",
                "save",
                "exit",
            ]
        )

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stderr, "")
        self.assertIn("/srv/project files", first.stdout)
        self.assertGreaterEqual(first.stdout.count("Filesystem saved."), 2)
        self.assertTrue(self.storage.is_file())

        restored = FileSystem.load(self.storage)
        self.assertEqual(restored.cwd, "/srv/project files")
        self.assertEqual(restored.current_dir, restored.resolve("/srv/project files").inode)
        self.assertEqual(restored.read_file("/srv/project files/logs/app.log"), "first entry second entry")
        metadata = restored.stat("/srv/project files/logs/app.log")
        self.assertEqual(metadata["mode"], "0640")
        self.assertEqual(metadata["owner_uid"], 1)
        self.assertEqual(metadata["group_gid"], 1)
        self.assertEqual(set(restored.group_ids(restored.users["alice"])), {1, 2})

        # A second OS process must load the saved state and see the same data.
        second = self.run_cli(
            [
                'cat "/srv/project files/logs/app.log"',
                'stat "/srv/project files/logs/app.log"',
                "groups alice",
                "exit",
            ]
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("first entry second entry", second.stdout)
        self.assertIn("mode: 0640", second.stdout)
        self.assertIn("owner_uid: 1", second.stdout)
        self.assertIn("engineering", second.stdout)

    def test_real_cli_survives_bad_commands_and_keeps_processing_input(self) -> None:
        result = self.run_cli(
            [
                "mkdir /before",
                'mkdir "/unterminated',
                "cat /does-not-exist",
                "mkdir /after",
                "ls /",
                "exit",
            ]
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("syntax error:", result.stdout)
        self.assertIn("error:", result.stdout)
        self.assertIn("before", result.stdout)
        self.assertIn("after", result.stdout)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

        restored = FileSystem.load(self.storage)
        self.assertEqual(
            [entry["name"] for entry in restored.list_dir("/")],
            ["after", "before"],
        )

    def test_real_cli_rejects_corrupt_persistence_without_traceback(self) -> None:
        self.storage.parent.mkdir(parents=True)
        self.storage.write_text("{not valid json", encoding="utf-8")

        result = self.run_cli(["pwd"])

        self.assertEqual(result.returncode, 1)
        self.assertIn("fatal:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.storage.read_text(encoding="utf-8"), "{not valid json")


if __name__ == "__main__":
    unittest.main()
