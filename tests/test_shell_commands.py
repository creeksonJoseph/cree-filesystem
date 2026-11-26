"""Comprehensive shell-level tests covering every CreeShell command."""
from __future__ import annotations

from tests.helpers import ShellTestCase


class TestAllShellCommands(ShellTestCase):
    """Exercise every implemented command through CreeShell."""

    def test_help_and_unknown_and_empty_line(self) -> None:
        stop, out = self.run_cmd("help")
        self.assertFalse(stop)
        for cmd_name in (
            "pwd", "whoami", "id", "groups", "ls", "tree", "cd", "mkdir",
            "touch", "cat", "write", "append", "rm", "mv", "cp", "chmod",
            "chown", "useradd", "groupadd", "usermod", "su", "find", "grep",
            "stat", "save", "exit", "EOF",
        ):
            self.assertIn(cmd_name, out)

        _, out = self.run_cmd("help ls")
        self.assertIn("ls [-a] [-l] [PATH]", out)

        _, out = self.run_cmd("help nonexistent_cmd")
        self.assertIn("No help on nonexistent_cmd", out)

        _, out = self.run_cmd("notacommand arg1")
        self.assertEqual(out.strip(), "notacommand: command not found")

        # Empty line should not repeat previous command
        self.run_cmd("mkdir /onlyonce")
        _, out = self.run_cmd("")
        self.assertEqual(out, "")

    def test_identity_commands_pwd_whoami_id_groups(self) -> None:
        _, out = self.run_cmd("pwd")
        self.assertEqual(out.strip(), "/")
        _, out = self.run_cmd("pwd extra")
        self.assertEqual(out.strip(), "usage: pwd")

        _, out = self.run_cmd("whoami")
        self.assertEqual(out.strip(), "root")
        _, out = self.run_cmd("whoami extra")
        self.assertEqual(out.strip(), "usage: whoami")

        _, out = self.run_cmd("id")
        self.assertIn("uid=0(root)", out)
        self.assertIn("gid=0", out)
        self.assertIn("root(0)", out)
        _, out = self.run_cmd("id extra")
        self.assertEqual(out.strip(), "usage: id")

        _, out = self.run_cmd("groups")
        self.assertEqual(out.strip(), "root")
        _, out = self.run_cmd("groups root")
        self.assertEqual(out.strip(), "root")
        _, out = self.run_cmd("groups nobody")
        self.assertIn("unknown user: nobody", out)
        _, out = self.run_cmd("groups a b")
        self.assertEqual(out.strip(), "usage: groups [USER]")

    def test_mkdir_cd_pwd_and_spaces(self) -> None:
        self.run_cmd('mkdir "/project files"')
        self.run_cmd('mkdir -p "/project files/sub dir/deep"')
        _, out = self.run_cmd('cd "/project files/sub dir"')
        self.assertEqual(out, "")
        _, out = self.run_cmd("pwd")
        self.assertEqual(out.strip(), "/project files/sub dir")

        # Normalization of // and .. and .
        self.run_cmd("cd //project\\ files/../project\\ files/.")
        _, out = self.run_cmd("pwd")
        self.assertEqual(out.strip(), "/project files")

        # Dashed dir name via --
        self.run_cmd("mkdir -- -dashed")
        _, out = self.run_cmd("ls")
        self.assertIn("-dashed", out)

        # Invalid options / args / errors
        _, out = self.run_cmd("mkdir -z bad")
        self.assertEqual(out.strip(), "usage: mkdir [-p] PATH")
        _, out = self.run_cmd("mkdir")
        self.assertEqual(out.strip(), "usage: mkdir [-p] PATH")
        _, out = self.run_cmd("mkdir /project\\ files")
        self.assertIn("error:", out)

        self.run_cmd("touch /afile")
        _, out = self.run_cmd("cd /afile")
        self.assertIn("Not a directory", out)
        _, out = self.run_cmd("cd /missing")
        self.assertIn("No such file or directory", out)
        _, out = self.run_cmd("cd")
        self.assertEqual(out.strip(), "usage: cd PATH")

    def test_ls_options_and_end_of_options(self) -> None:
        self.run_cmd("mkdir /box")
        self.run_cmd("touch /box/alpha.txt")
        self.run_cmd("touch /box/.secret")
        self.run_cmd("mkdir /box/sub")
        self.run_cmd("touch /box/-weird")

        # Default ls: names only, no dotfiles
        _, out = self.run_cmd("ls /box")
        self.assertEqual(out.strip(), "-weird  alpha.txt  sub")
        self.assertNotIn(".secret", out)

        # -a includes dotfiles
        _, out = self.run_cmd("ls -a /box")
        self.assertIn(".secret", out)
        self.assertIn("alpha.txt", out)

        # -l displays detailed metadata without dotfiles
        _, out = self.run_cmd("ls -l /box")
        self.assertNotIn(".secret", out)
        self.assertIn("-rw-r--r-- 0:0", out)
        self.assertIn("drwxr-xr-x 0:0", out)
        self.assertIn("alpha.txt", out)

        # -la and -al
        _, out_la = self.run_cmd("ls -la /box")
        _, out_al = self.run_cmd("ls -al /box")
        self.assertEqual(out_la, out_al)
        self.assertIn(".secret", out_la)
        self.assertIn("-rw-r--r--", out_la)

        # -- ends option parsing
        self.run_cmd("mkdir /box/-a")
        self.run_cmd("touch /box/-a/inside.txt")
        _, out = self.run_cmd("ls -- /box/-a")
        self.assertEqual(out.strip(), "inside.txt")

        # Invalid option and invalid target
        _, out = self.run_cmd("ls -x /box")
        self.assertEqual(out.strip(), "usage: ls [-a] [-l] [PATH]")
        _, out = self.run_cmd("ls /box/alpha.txt")
        self.assertIn("Not a directory", out)
        _, out = self.run_cmd("ls /box /extra")
        self.assertEqual(out.strip(), "usage: ls [-a] [-l] [PATH]")

    def test_tree_touch_cat_write_append_stat(self) -> None:
        self.run_cmd('mkdir -p "/docs/my notes"')
        self.run_cmd('touch "/docs/my notes/hello world.txt"')
        self.run_cmd('write "/docs/my notes/hello world.txt" "first line"')
        _, out = self.run_cmd('cat "/docs/my notes/hello world.txt"')
        self.assertEqual(out.strip(), "first line")

        self.run_cmd('append "/docs/my notes/hello world.txt" " and second"')
        _, out = self.run_cmd('cat "/docs/my notes/hello world.txt"')
        self.assertEqual(out.strip(), "first line and second")

        # write overwrites
        self.run_cmd('write "/docs/my notes/hello world.txt" replaced text')
        _, out = self.run_cmd('cat "/docs/my notes/hello world.txt"')
        self.assertEqual(out.strip(), "replaced text")

        # tree
        _, out = self.run_cmd("tree /docs")
        self.assertIn("/docs", out)
        self.assertIn("my notes", out)
        self.assertIn("hello world.txt", out)

        # stat
        _, out = self.run_cmd('stat "/docs/my notes/hello world.txt"')
        self.assertIn("name: hello world.txt", out)
        self.assertIn("type: file", out)
        self.assertIn("mode: 0644", out)

        # Error & usage cases
        _, out = self.run_cmd("touch")
        self.assertEqual(out.strip(), "usage: touch PATH")
        _, out = self.run_cmd('touch "/docs/my notes/hello world.txt"')
        self.assertIn("Already exists", out)
        _, out = self.run_cmd("cat /docs")
        self.assertIn("Not a file", out)
        _, out = self.run_cmd("write /docs text")
        self.assertIn("Not a file", out)
        _, out = self.run_cmd("write /onlypath")
        self.assertEqual(out.strip(), "usage: write PATH TEXT")
        _, out = self.run_cmd("append /onlypath")
        self.assertEqual(out.strip(), "usage: append PATH TEXT")
        _, out = self.run_cmd("tree /missing")
        self.assertIn("No such file or directory", out)
        _, out = self.run_cmd("tree a b")
        self.assertEqual(out.strip(), "usage: tree [PATH]")
        _, out = self.run_cmd("stat /missing")
        self.assertIn("No such file or directory", out)
        _, out = self.run_cmd("stat")
        self.assertEqual(out.strip(), "usage: stat PATH")

    def test_mv_cp_and_rm(self) -> None:
        self.run_cmd("mkdir -p /src/sub")
        self.run_cmd('touch "/src/sub/my file.txt"')
        self.run_cmd('write "/src/sub/my file.txt" "data"')
        _, stat_before = self.run_cmd('stat "/src/sub/my file.txt"')
        inode_before = [line for line in stat_before.splitlines() if line.startswith("inode:")][0]

        # cp file and directory
        self.run_cmd('cp "/src/sub/my file.txt" "/src/sub/copy file.txt"')
        _, out = self.run_cmd('cat "/src/sub/copy file.txt"')
        self.assertEqual(out.strip(), "data")

        self.run_cmd("mkdir /backup")
        self.run_cmd("cp /src /backup")
        _, out = self.run_cmd("tree /backup")
        self.assertIn("copy file.txt", out)

        # Self-copy rejected
        _, out = self.run_cmd("cp /src /src/sub/inside")
        self.assertIn("Cannot copy a directory into itself", out)

        # mv file preserves inode
        self.run_cmd('mv "/src/sub/my file.txt" "/src/renamed.txt"')
        _, stat_after = self.run_cmd("stat /src/renamed.txt")
        inode_after = [line for line in stat_after.splitlines() if line.startswith("inode:")][0]
        self.assertEqual(inode_before, inode_after)

        # mv directory while cwd is inside it updates cwd
        self.run_cmd("cd /src/sub")
        self.run_cmd("mv /src /moved_src")
        _, out = self.run_cmd("pwd")
        self.assertEqual(out.strip(), "/moved_src/sub")

        # mv into itself rejected
        _, out = self.run_cmd("mv /moved_src /moved_src/sub")
        self.assertIn("Cannot move a directory into itself", out)

        # rm non-empty without -r fails, with -r succeeds and resets cwd if inside
        _, out = self.run_cmd("rm /moved_src")
        self.assertIn("Directory is not empty", out)
        _, out = self.run_cmd("rm -x /moved_src")
        self.assertEqual(out.strip(), "usage: rm [-r] PATH")
        _, out = self.run_cmd("rm /")
        self.assertIn("error:", out)

        self.run_cmd("rm -r /moved_src")
        _, out = self.run_cmd("pwd")
        self.assertEqual(out.strip(), "/")

        # rm -- -dashed file
        self.run_cmd("touch -odd")
        self.run_cmd("rm -- -odd")
        _, out = self.run_cmd("ls /")
        self.assertNotIn("-odd", out)

        # Usage checks
        _, out = self.run_cmd("mv onlyone")
        self.assertEqual(out.strip(), "usage: mv SOURCE DESTINATION")
        _, out = self.run_cmd("cp onlyone")
        self.assertEqual(out.strip(), "usage: cp SOURCE DESTINATION")

    def test_find_and_grep(self) -> None:
        self.run_cmd("mkdir -p /workspace/sub")
        self.run_cmd("touch /workspace/readme.txt")
        self.run_cmd("write /workspace/readme.txt \"needle in haystack\"")
        self.run_cmd("touch /workspace/sub/needle.txt")
        self.run_cmd("write /workspace/sub/needle.txt \"nothing matching here\"")
        self.run_cmd("mkdir /workspace/needle_dir")

        _, out = self.run_cmd("find needle /workspace")
        lines = out.strip().splitlines()
        self.assertEqual(lines, ["/workspace/needle_dir", "/workspace/sub/needle.txt"])

        # grep must search contents only, never match filename/dirname alone
        _, out = self.run_cmd("grep needle /workspace")
        self.assertEqual(out.strip().splitlines(), ["/workspace/readme.txt"])

        _, out = self.run_cmd("grep needle /workspace/sub/needle.txt")
        self.assertEqual(out.strip(), "")

        _, out = self.run_cmd("grep needle /workspace/needle_dir")
        self.assertEqual(out.strip(), "")

        # Usage & error checks
        _, out = self.run_cmd("find")
        self.assertEqual(out.strip(), "usage: find NAME [PATH]")
        _, out = self.run_cmd("grep")
        self.assertEqual(out.strip(), "usage: grep TEXT [PATH]")
        _, out = self.run_cmd('grep "" /workspace')
        self.assertIn("Search query cannot be empty", out)

    def test_chmod_chown_user_group_su_and_save_exit(self) -> None:
        self.run_cmd("groupadd devs")
        self.run_cmd("useradd alice")
        self.run_cmd("usermod -aG devs alice")
        self.run_cmd("touch /shared.txt")
        self.run_cmd("chown alice:devs /shared.txt")
        self.run_cmd("chmod 640 /shared.txt")

        _, out = self.run_cmd("stat /shared.txt")
        self.assertIn("mode: 0640", out)
        self.assertIn("owner_uid: 1", out)
        self.assertIn("group_gid: 1", out)

        _, out = self.run_cmd("groups alice")
        self.assertEqual(set(out.strip().split()), {"alice", "devs"})

        # Usage & validation checks
        _, out = self.run_cmd("chown alice: /shared.txt")
        self.assertEqual(out.strip(), "usage: chown USER[:GROUP] PATH")
        _, out = self.run_cmd("chown :devs /shared.txt")
        self.assertEqual(out.strip(), "usage: chown USER[:GROUP] PATH")
        _, out = self.run_cmd("chmod 999 /shared.txt")
        self.assertIn("error:", out)
        _, out = self.run_cmd("usermod -G devs alice")
        self.assertEqual(out.strip(), "usage: usermod -aG GROUP USER")
        _, out = self.run_cmd("su nobody")
        self.assertIn("Unknown user", out)

        _, out = self.run_cmd("su alice")
        self.assertEqual(out.strip(), "Switched to alice")
        _, out = self.run_cmd("whoami")
        self.assertEqual(out.strip(), "alice")
        _, out = self.run_cmd("save")
        self.assertEqual(out.strip(), "Filesystem saved.")
        self.assertTrue(self.storage_path.exists())

        stop, out = self.run_cmd("exit")
        self.assertTrue(stop)
        self.assertEqual(out.strip(), "Filesystem saved.")
