"""Shared test helpers for CreeShell integration tests."""
from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from cree_filesystem import FileSystem
from cree_filesystem.cli import CreeShell


class ShellTestCase(unittest.TestCase):
    """Base test case providing an isolated FileSystem and CreeShell per test."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.storage_path = self.tmp_path / "test-fs.json"
        self.fs = FileSystem(self.storage_path)
        self.shell = CreeShell(self.fs)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def run_cmd(self, line: str, shell: CreeShell | None = None) -> tuple[bool, str]:
        """Execute one command through CreeShell.onecmd and capture output."""
        target = shell or self.shell
        buf = io.StringIO()
        with redirect_stdout(buf):
            stop = target.onecmd(line)
            target.postcmd(stop, line)
        return stop, buf.getvalue()

    def run_session(
        self, lines: list[str], fs: FileSystem | None = None
    ) -> tuple[CreeShell, str]:
        """Run a full CreeShell.cmdloop session with an in-memory input stream."""
        target_fs = fs if fs is not None else self.fs
        stdin = io.StringIO("\n".join(lines) + "\n")
        stdout = io.StringIO()
        shell = CreeShell(target_fs, stdin=stdin, stdout=stdout)
        shell.cmdloop()
        return shell, stdout.getvalue()
