"""Tests for Ctrl-C, Ctrl-D, exit, save errors, and CLI startup behaviour."""
from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from cree_filesystem import FileSystem
from cree_filesystem.cli import CreeShell, main
from tests.helpers import ShellTestCase


class InterruptingStream(io.StringIO):
    """Input stream that executes initial lines then raises KeyboardInterrupt."""

    def __init__(self, lines: list[str]) -> None:
        super().__init__("\n".join(lines) + ("\n" if lines else ""))
        self._raised = False

    def readline(self, size: int = -1) -> str:
        line = super().readline(size)
        if line == "" and not self._raised:
            self._raised = True
            raise KeyboardInterrupt
        return line


class TestShellShutdownAndCLI(ShellTestCase):
    """Verify Ctrl-C, Ctrl-D, exit, save error reporting, and CLI entrypoints."""

    def test_ctrl_c_saves_and_exits_cleanly_without_traceback(self) -> None:
        stdin = InterruptingStream(["mkdir /before_sigint", "touch /before_sigint/f.txt"])
        stdout = io.StringIO()
        shell = CreeShell(self.fs, stdin=stdin, stdout=stdout)

        shell.cmdloop()
        out = stdout.getvalue()

        self.assertNotIn("Traceback", out)
        self.assertIn("Filesystem saved.", out)
        self.assertTrue(self.storage_path.exists())
        reloaded = FileSystem.load(self.storage_path)
        self.assertEqual(
            [e["name"] for e in reloaded.list_dir("/before_sigint")],
            ["f.txt"],
        )

    def test_ctrl_c_reports_save_failure_cleanly(self) -> None:
        # Point storage_path at an existing directory to force an OSError on save
        bad_storage = self.tmp_path / "dir_not_file"
        bad_storage.mkdir()
        fs = FileSystem(bad_storage)
        stdin = InterruptingStream(["mkdir /unsaved"])
        stdout = io.StringIO()
        shell = CreeShell(fs, stdin=stdin, stdout=stdout)

        shell.cmdloop()
        out = stdout.getvalue()

        self.assertNotIn("Traceback", out)
        self.assertIn("error: could not save filesystem:", out)

    def test_ctrl_d_saves_and_exits_cleanly(self) -> None:
        stdin = io.StringIO("mkdir /from_eof\n")
        stdout = io.StringIO()
        shell = CreeShell(self.fs, stdin=stdin, stdout=stdout)

        shell.cmdloop()
        out = stdout.getvalue()

        self.assertIn("Filesystem saved.", out)
        reloaded = FileSystem.load(self.storage_path)
        self.assertEqual([e["name"] for e in reloaded.list_dir("/")], ["from_eof"])

    def test_ctrl_d_when_save_fails_does_not_infinite_loop(self) -> None:
        bad_storage = self.tmp_path / "dir_not_file"
        bad_storage.mkdir()
        fs = FileSystem(bad_storage)
        stdin = io.StringIO("mkdir /x\n")
        stdout = io.StringIO()
        shell = CreeShell(fs, stdin=stdin, stdout=stdout)

        shell.cmdloop()
        out = stdout.getvalue()

        self.assertIn("error: could not save filesystem:", out)
        self.assertEqual(out.count("error: could not save filesystem:"), 1)

    def test_exit_and_in_memory_exit(self) -> None:
        bad_storage = self.tmp_path / "dir_not_file"
        bad_storage.mkdir()
        shell_bad = CreeShell(FileSystem(bad_storage))
        stop, out = self.run_cmd("exit", shell=shell_bad)
        self.assertFalse(stop)
        self.assertIn("error: could not save filesystem:", out)

        # In-memory filesystem without storage_path should report and still allow exit
        shell_mem = CreeShell(FileSystem())
        stop, out = self.run_cmd("exit", shell=shell_mem)
        self.assertTrue(stop)
        self.assertIn("error: could not save filesystem: No storage path configured", out)

    def test_cli_fresh_and_persistent_and_corrupt_startup(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        env = {**os.environ, "PYTHONPATH": str(repo_root / "src")}

        # 1. Start fresh, create state, exit
        proc = subprocess.run(
            [sys.executable, "-m", "cree_filesystem", "--fresh", "--storage", str(self.storage_path)],
            input="mkdir /persisted\ntouch /persisted/note.txt\nwrite /persisted/note.txt hello\nexit\n",
            text=True,
            capture_output=True,
            env=env,
            cwd=str(self.tmp_path),
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Filesystem saved.", proc.stdout)

        # 2. Normal persistent startup reloads saved state
        proc2 = subprocess.run(
            [sys.executable, "-m", "cree_filesystem", "--storage", str(self.storage_path)],
            input="cat /persisted/note.txt\nexit\n",
            text=True,
            capture_output=True,
            env=env,
            cwd=str(self.tmp_path),
            check=False,
        )
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        self.assertIn("hello", proc2.stdout)

        # 3. Corrupt save file exits cleanly with fatal message and no traceback
        self.storage_path.write_text("{corrupt json", encoding="utf-8")
        proc3 = subprocess.run(
            [sys.executable, "-m", "cree_filesystem", "--storage", str(self.storage_path)],
            input="",
            text=True,
            capture_output=True,
            env=env,
            cwd=str(self.tmp_path),
            check=False,
        )
        self.assertEqual(proc3.returncode, 1)
        self.assertIn("fatal:", proc3.stderr)
        self.assertNotIn("Traceback", proc3.stderr)

        # 4. Verify main() direct call with --fresh in isolated cwd
        with patch.object(sys, "argv", ["cree-fs", "--fresh", "--storage", str(self.tmp_path / "fresh.json")]):
            with patch("sys.stdin", io.StringIO("pwd\nexit\n")):
                stdout = io.StringIO()
                with patch("sys.stdout", stdout):
                    main()
                self.assertIn("Filesystem saved.", stdout.getvalue())
