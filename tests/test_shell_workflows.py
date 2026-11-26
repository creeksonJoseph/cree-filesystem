"""End-to-end persistence, corrupt-save, and permission/user workflow tests."""
from __future__ import annotations

import json

from cree_filesystem import FileSystem
from cree_filesystem.cli import CreeShell
from cree_filesystem.filesystem import FileSystemError
from tests.helpers import ShellTestCase


class TestPersistenceAndPermissionsWorkflow(ShellTestCase):
    """Test complete user-facing persistence and multi-user permission workflows."""

    def test_full_persistence_roundtrip_via_shell(self) -> None:
        self.run_session([
            "groupadd team",
            "useradd alice",
            "usermod -aG team alice",
            'mkdir -p "/srv/project files"',
            'touch "/srv/project files/log.txt"',
            'write "/srv/project files/log.txt" "line one"',
            'append "/srv/project files/log.txt" " | line two"',
            'chown alice:team "/srv/project files/log.txt"',
            'chmod 640 "/srv/project files/log.txt"',
            'cd "/srv/project files"',
            "save",
            "exit",
        ])

        reloaded = FileSystem.load(self.storage_path)
        new_shell = CreeShell(reloaded)

        _, out = self.run_cmd("pwd", shell=new_shell)
        self.assertEqual(out.strip(), "/srv/project files")

        _, out = self.run_cmd('cat "/srv/project files/log.txt"', shell=new_shell)
        self.assertEqual(out.strip(), "line one | line two")

        _, out = self.run_cmd('stat "/srv/project files/log.txt"', shell=new_shell)
        self.assertIn("mode: 0640", out)
        self.assertIn("owner_uid: 1", out)
        self.assertIn("group_gid: 1", out)

        _, out = self.run_cmd("groups alice", shell=new_shell)
        self.assertEqual(set(out.strip().split()), {"alice", "team"})

    def test_corrupt_and_malformed_save_files_raise_controlled_errors(self) -> None:
        # Invalid JSON
        self.storage_path.write_text("{bad json", encoding="utf-8")
        with self.assertRaises(FileSystemError):
            FileSystem.load(self.storage_path)

        # Invalid UTF-8 bytes
        self.storage_path.write_bytes(b"\xff\xfe\xfd")
        with self.assertRaises(FileSystemError):
            FileSystem.load(self.storage_path)

        # Unsupported version
        self.storage_path.write_text(json.dumps({"version": 999}), encoding="utf-8")
        with self.assertRaises(FileSystemError):
            FileSystem.load(self.storage_path)

        # Valid base state for targeted corruption tests
        self.run_cmd("mkdir /dir")
        self.run_cmd("touch /dir/f.txt")
        self.run_cmd("save")
        base = json.loads(self.storage_path.read_text(encoding="utf-8"))

        corrupt_cases = []

        # Boolean uid/mode (Python bool is subclass of int)
        bad_bool_uid = json.loads(json.dumps(base))
        bad_bool_uid["users"][0]["uid"] = False
        corrupt_cases.append(bad_bool_uid)

        # Non-root user marked is_root=True
        bad_root_flag = json.loads(json.dumps(base))
        bad_root_flag["users"].append(
            {"username": "evil", "uid": 1, "primary_gid": 0, "is_root": True}
        )
        corrupt_cases.append(bad_root_flag)

        # Non-string file content
        bad_content = json.loads(json.dumps(base))
        file_inode = bad_content["inodes"][bad_content["inodes"][bad_content["root_inode"]]["children"]["dir"]]["children"]["f.txt"]
        bad_content["inodes"][file_inode]["content"] = 12345
        corrupt_cases.append(bad_content)

        # Directory cycle
        bad_cycle = json.loads(json.dumps(base))
        dir_inode = bad_cycle["inodes"][bad_cycle["root_inode"]]["children"]["dir"]
        bad_cycle["inodes"][dir_inode]["children"]["/"] = bad_cycle["root_inode"]
        corrupt_cases.append(bad_cycle)

        # Unreachable orphan inode
        bad_orphan = json.loads(json.dumps(base))
        bad_orphan["inodes"]["deadbeef0001"] = {
            "name": "orphan",
            "owner_uid": 0,
            "group_gid": 0,
            "mode": 0o644,
            "inode": "deadbeef0001",
            "created_at": "2026-01-01T00:00:00Z",
            "modified_at": "2026-01-01T00:00:00Z",
            "kind": "file",
            "content": "",
        }
        corrupt_cases.append(bad_orphan)

        # Duplicate username
        bad_dup_user = json.loads(json.dumps(base))
        bad_dup_user["users"].append(
            {"username": "root", "uid": 99, "primary_gid": 0, "is_root": False}
        )
        corrupt_cases.append(bad_dup_user)

        for idx, payload in enumerate(corrupt_cases):
            with self.subTest(case=idx):
                self.storage_path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(FileSystemError):
                    FileSystem.load(self.storage_path)

    def test_realistic_multi_user_and_permission_workflow(self) -> None:
        # Setup groups and users as root
        self.run_cmd("groupadd engineering")
        self.run_cmd("useradd alice")
        self.run_cmd("useradd bob")
        self.run_cmd("usermod -aG engineering alice")

        # Create workspace with owner/group/other permission differences
        self.run_cmd("mkdir -p /srv/eng/vault")
        self.run_cmd("touch /srv/eng/notes.txt")
        self.run_cmd('write /srv/eng/notes.txt "eng-only"')
        self.run_cmd("touch /srv/eng/vault/secret.txt")
        self.run_cmd('write /srv/eng/vault/secret.txt "top-secret"')

        self.run_cmd("chown alice:engineering /srv/eng")
        self.run_cmd("chmod 750 /srv/eng")
        self.run_cmd("chown root:engineering /srv/eng/notes.txt")
        self.run_cmd("chmod 640 /srv/eng/notes.txt")
        self.run_cmd("chown root:engineering /srv/eng/vault")
        # Vault has read only (4) for group, no execute (traversal denied for group)
        self.run_cmd("chmod 740 /srv/eng/vault")

        # Switch to alice (owner of /srv/eng, supplementary member of engineering)
        self.run_cmd("su alice")
        _, out = self.run_cmd("whoami")
        self.assertEqual(out.strip(), "alice")

        # Owner can list and create inside /srv/eng (750)
        _, out = self.run_cmd("ls /srv/eng")
        self.assertIn("notes.txt", out)
        self.run_cmd("touch /srv/eng/alice_file.txt")
        self.run_cmd("write /srv/eng/alice_file.txt \"by alice\"")

        # Supplementary group read works on notes.txt (640), write denied
        _, out = self.run_cmd("cat /srv/eng/notes.txt")
        self.assertEqual(out.strip(), "eng-only")
        _, out = self.run_cmd("write /srv/eng/notes.txt \"hacked\"")
        self.assertIn("Permission denied", out)

        # Group has r (4) on /srv/eng/vault, so ls works, but lacks x so traversal/cat fails
        _, out = self.run_cmd("ls /srv/eng/vault")
        self.assertEqual(out.strip(), "secret.txt")
        _, out = self.run_cmd("cd /srv/eng/vault")
        self.assertIn("Permission denied", out)
        _, out = self.run_cmd("cat /srv/eng/vault/secret.txt")
        self.assertIn("Permission denied", out)

        # Non-root cannot run admin commands
        _, out = self.run_cmd("useradd charlie")
        self.assertIn("Only root can add users", out)
        _, out = self.run_cmd("chown alice /srv/eng/notes.txt")
        self.assertIn("Only root can change ownership", out)

        # Switch to bob (not owner, not in engineering -> 'other' = 0)
        self.run_cmd("su bob")
        _, out = self.run_cmd("ls /srv/eng")
        self.assertIn("Permission denied", out)
        _, out = self.run_cmd("cat /srv/eng/notes.txt")
        self.assertIn("Permission denied", out)

        # Switch back to root and verify administrative operations & bypass
        self.run_cmd("su root")
        _, out = self.run_cmd("cat /srv/eng/vault/secret.txt")
        self.assertEqual(out.strip(), "top-secret")
        self.run_cmd("chmod 750 /srv/eng/vault")
        self.run_cmd("su alice")
        _, out = self.run_cmd("cat /srv/eng/vault/secret.txt")
        self.assertEqual(out.strip(), "top-secret")
