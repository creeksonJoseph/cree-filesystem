"""Tests for shell resilience, error isolation, and operation atomicity."""
from __future__ import annotations

import io
from contextlib import redirect_stdout
from unittest.mock import patch

from cree_filesystem import FileSystem
from cree_filesystem.cli import CreeShell
from tests.helpers import ShellTestCase


class TestShellResilienceAndAtomicity(ShellTestCase):
    """Verify the same CreeShell instance recovers cleanly after every failure."""

    def test_sequence_of_failures_in_same_shell_instance(self) -> None:
        # Prepare filesystem state in the shared shell instance
        self.run_cmd("useradd bob")
        self.run_cmd("mkdir /public")
        self.run_cmd("chmod 777 /public")
        self.run_cmd("touch /root_secret.txt")
        self.run_cmd("write /root_secret.txt secret")
        self.run_cmd("chmod 600 /root_secret.txt")

        # 1. Invalid arguments
        stop, out = self.run_cmd("ls --bad-opt")
        self.assertFalse(stop)
        self.assertIn("usage: ls", out)
        stop, out = self.run_cmd("pwd")
        self.assertFalse(stop)
        self.assertEqual(out.strip(), "/")

        # 2. Nonexistent path
        stop, out = self.run_cmd("cat /does/not/exist.txt")
        self.assertFalse(stop)
        self.assertIn("error:", out)
        stop, out = self.run_cmd("mkdir /public/after_missing")
        self.assertFalse(stop)
        self.assertEqual(out, "")

        # 3. Permission check failure
        self.run_cmd("su bob")
        stop, out = self.run_cmd("cat /root_secret.txt")
        self.assertFalse(stop)
        self.assertIn("Permission denied", out)
        stop, out = self.run_cmd("ls /public")
        self.assertFalse(stop)
        self.assertIn("after_missing", out)

        # 4. Malformed quoting
        stop, out = self.run_cmd('mkdir "/public/unclosed')
        self.assertFalse(stop)
        self.assertIn("syntax error:", out)
        stop, out = self.run_cmd('pwd "unclosed')
        self.assertFalse(stop)
        self.assertIn("syntax error:", out)
        stop, out = self.run_cmd("mkdir /public/after_quote_err")
        self.assertFalse(stop)
        self.assertEqual(out, "")

        # 5. Simulated unexpected internal exception inside a command
        with patch.object(self.fs, "stat", side_effect=RuntimeError("boom")):
            stop, out = self.run_cmd("stat /public")
            self.assertFalse(stop)
            self.assertIn("internal error while running stat: boom", out)

        # 6. Subsequent valid commands in the exact same shell instance still work
        stop, out = self.run_cmd("pwd")
        self.assertFalse(stop)
        self.assertEqual(out.strip(), "/")
        stop, out = self.run_cmd("ls /public")
        self.assertFalse(stop)
        self.assertIn("after_missing", out)
        self.assertIn("after_quote_err", out)
        stop, out = self.run_cmd("mkdir /public/final_dir")
        self.assertFalse(stop)
        self.assertEqual(out, "")

    def test_base_exceptions_are_not_swallowed_by_onecmd(self) -> None:
        with patch.object(self.fs, "list_dir", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.shell.onecmd("ls")

        with patch.object(self.fs, "list_dir", side_effect=SystemExit(2)):
            with self.assertRaises(SystemExit) as ctx:
                self.shell.onecmd("ls")
            self.assertEqual(ctx.exception.code, 2)

    def test_mkdir_p_is_atomic_on_midway_failure(self) -> None:
        self.run_cmd("useradd alice")
        self.run_cmd("mkdir /sandbox")
        self.run_cmd("chown alice:alice /sandbox")
        self.run_cmd("su alice")
        inode_count_before = len(self.fs.inodes)

        # Creating with mode 000 as non-root fails on second segment; /sandbox/a must roll back
        with self.assertRaises(PermissionError):
            self.fs.mkdir("/sandbox/a/b", mode=0o000, parents=True)

        self.assertEqual(len(self.fs.inodes), inode_count_before)
        _, out = self.run_cmd("ls /sandbox")
        self.assertEqual(out.strip(), "")

    def test_rm_recursive_is_atomic_on_nested_permission_failure(self) -> None:
        self.run_cmd("useradd alice")
        self.run_cmd("mkdir -p /work/deletable")
        self.run_cmd("touch /work/deletable/ok.txt")
        self.run_cmd("mkdir -p /work/locked")
        self.run_cmd("touch /work/locked/root_file.txt")
        self.run_cmd("chown alice:alice /work")
        self.run_cmd("chown alice:alice /work/deletable")
        self.run_cmd("chown alice:alice /work/deletable/ok.txt")
        # /work/locked stays owned by root with mode 000
        self.run_cmd("chmod 000 /work/locked")

        self.run_cmd("su alice")
        inodes_before = set(self.fs.inodes.keys())

        _, out = self.run_cmd("rm -r /work")
        self.assertIn("Permission denied", out)
        # Neither /work/deletable nor /work/deletable/ok.txt should have been deleted
        self.assertEqual(set(self.fs.inodes.keys()), inodes_before)
        _, out = self.run_cmd("cat /work/deletable/ok.txt")
        self.assertEqual(out.strip(), "")

    def test_cp_is_atomic_on_nested_unreadable_file(self) -> None:
        self.run_cmd("useradd alice")
        self.run_cmd("mkdir -p /tree_src/sub")
        self.run_cmd("touch /tree_src/good.txt")
        self.run_cmd("touch /tree_src/sub/secret.txt")
        self.run_cmd("chmod 000 /tree_src/sub/secret.txt")
        self.run_cmd("mkdir /dest")
        self.run_cmd("chown alice:alice /dest")

        self.run_cmd("su alice")
        inodes_before = set(self.fs.inodes.keys())

        _, out = self.run_cmd("cp /tree_src /dest/copied")
        self.assertIn("Permission denied", out)
        self.assertEqual(set(self.fs.inodes.keys()), inodes_before)
        _, out = self.run_cmd("ls /dest")
        self.assertEqual(out.strip(), "")

    def test_queued_session_survives_errors_and_continues(self) -> None:
        _, output = self.run_session([
            "mkdir /one",
            'mkdir "/broken',
            "cat /missing",
            "ls -bad",
            "mkdir /two",
            "ls /",
            "exit",
        ])
        self.assertIn("syntax error:", output)
        self.assertIn("error:", output)
        self.assertIn("usage: ls", output)
        self.assertIn("one  two", output)
        self.assertIn("Filesystem saved.", output)
        # Verify persisted state from queued session
        reloaded = FileSystem.load(self.storage_path)
        names = [item["name"] for item in reloaded.list_dir("/")]
        self.assertEqual(names, ["one", "two"])
