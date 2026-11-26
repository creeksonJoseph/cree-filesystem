"""Interactive shell implemented with Python's cmd module."""
from __future__ import annotations

import argparse
import cmd
import shlex
import sys
from typing import Callable

from .filesystem import FileSystem, FileSystemError


class CreeShell(cmd.Cmd):
    """Command interpreter that delegates filesystem behaviour to FileSystem."""

    intro = "Cree Filesystem — type 'help' to list available commands."
    ruler = "-"

    def __init__(self, filesystem: FileSystem) -> None:
        super().__init__()
        self.fs = filesystem
        self.prompt = self._make_prompt()

    def _make_prompt(self) -> str:
        return f"{self.fs.current_user.username}@cree:{self.fs.cwd}$ "

    def postcmd(self, stop: bool, line: str) -> bool:
        self.prompt = self._make_prompt()
        return stop

    def onecmd(self, line: str) -> bool:
        """Keep malformed quoting from terminating the interactive session."""
        try:
            return super().onecmd(line)
        except ValueError as exc:
            print(f"syntax error: {exc}")
            return False

    @staticmethod
    def _args(argument: str) -> list[str]:
        return shlex.split(argument)

    def emptyline(self) -> None:
        """Do not repeat the previous command when the input line is empty."""

    def default(self, line: str) -> None:
        command = line.split(maxsplit=1)[0] if line.strip() else line
        print(f"{command}: command not found")

    def _run(self, operation: Callable, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except (FileSystemError, PermissionDenied, ValueError, OSError) as exc:
            print(f"error: {exc}")
            return None

    def do_pwd(self, argument: str) -> None:
        """pwd — print the current working directory."""
        print(self.fs.cwd)

    def do_whoami(self, argument: str) -> None:
        """whoami — print the active simulated username."""
        print(self.fs.current_user.username)

    def do_id(self, argument: str) -> None:
        """id — display the active simulated UID, primary GID and groups."""
        user = self.fs.current_user
        group_ids = sorted(self.fs.group_ids(user))
        names = [
            f"{self.fs.groups_by_gid[gid].name}({gid})"
            for gid in group_ids
        ]
        print(f"uid={user.uid}({user.username}) gid={user.primary_gid} "
              f"({self.fs.groups_by_gid[user.primary_gid].name}) "
              f"groups={','.join(names)}")

    def do_groups(self, argument: str) -> None:
        """groups [USER] — list the primary and supplementary groups."""
        args = self._args(argument)
        if len(args) > 1:
            print("usage: groups [USER]")
            return
        username = args[0] if args else self.fs.current_user.username
        user = self.fs.users.get(username)
        if user is None:
            print(f"error: unknown user: {username}")
            return
        names = [
            group.name for group in self.fs.groups.values()
            if group.gid in self.fs.group_ids(user)
        ]
        print(" ".join(names))

    def do_ls(self, argument: str) -> None:
        """ls [PATH] — list directory entries and their metadata."""
        args = self._args(argument)
        if len(args) > 1:
            print("usage: ls [PATH]")
            return
        entries = self._run(self.fs.list_dir, args[0] if args else ".")
        if entries is None:
            return
        for item in entries:
            kind = "d" if item["type"] == "directory" else "-"
            print(
                f"{kind}{item['mode']} {item['owner_uid']}:{item['group_gid']} "
                f"{item['inode']} {item['name']}"
            )

    def do_tree(self, argument: str) -> None:
        """tree [PATH] — display a directory hierarchy."""
        args = self._args(argument)
        if len(args) > 1:
            print("usage: tree [PATH]")
            return
        result = self._run(self.fs.tree, args[0] if args else "/")
        if result is not None:
            print(result)

    def do_cd(self, argument: str) -> None:
        """cd PATH — change the current working directory."""
        args = self._args(argument)
        if len(args) != 1:
            print("usage: cd PATH")
            return
        self._run(self.fs.change_directory, args[0])

    def do_mkdir(self, argument: str) -> None:
        """mkdir [-p] PATH — create a directory, optionally with parents."""
        args = self._args(argument)
        parents = "-p" in args
        paths = [item for item in args if item != "-p"]
        if len(paths) != 1:
            print("usage: mkdir [-p] PATH")
            return
        self._run(self.fs.mkdir, paths[0], parents=parents)

    def do_touch(self, argument: str) -> None:
        """touch PATH — create an empty file."""
        args = self._args(argument)
        if len(args) != 1:
            print("usage: touch PATH")
            return
        self._run(self.fs.create_file, args[0])

    def do_cat(self, argument: str) -> None:
        """cat PATH — print a file's contents."""
        args = self._args(argument)
        if len(args) != 1:
            print("usage: cat PATH")
            return
        content = self._run(self.fs.read_file, args[0])
        if content is not None:
            print(content)

    def _write(self, argument: str, append: bool) -> None:
        args = self._args(argument)
        if len(args) < 2:
            command = "append" if append else "write"
            print(f"usage: {command} PATH TEXT")
            return
        self._run(
            self.fs.write_file, args[0], " ".join(args[1:]), append=append
        )

    def do_write(self, argument: str) -> None:
        """write PATH TEXT — replace a file's contents."""
        self._write(argument, append=False)

    def do_append(self, argument: str) -> None:
        """append PATH TEXT — append text to a file."""
        self._write(argument, append=True)

    def do_rm(self, argument: str) -> None:
        """rm [-r] PATH — remove a file or directory."""
        args = self._args(argument)
        recursive = any(flag in args for flag in ("-r", "-R", "--recursive"))
        paths = [item for item in args if item not in ("-r", "-R", "--recursive")]
        if len(paths) != 1:
            print("usage: rm [-r] PATH")
            return
        self._run(self.fs.remove, paths[0], recursive=recursive)

    def do_mv(self, argument: str) -> None:
        """mv SOURCE DESTINATION — move or rename a file or directory."""
        args = self._args(argument)
        if len(args) != 2:
            print("usage: mv SOURCE DESTINATION")
            return
        self._run(self.fs.move, *args)

    def do_cp(self, argument: str) -> None:
        """cp SOURCE DESTINATION — copy a file or directory."""
        args = self._args(argument)
        if len(args) != 2:
            print("usage: cp SOURCE DESTINATION")
            return
        self._run(self.fs.copy, *args)

    def do_chmod(self, argument: str) -> None:
        """chmod MODE PATH — change owner/group/other permission bits."""
        args = self._args(argument)
        if len(args) != 2:
            print("usage: chmod MODE PATH")
            return
        self._run(self.fs.chmod, args[1], args[0])

    def do_chown(self, argument: str) -> None:
        """chown USER[:GROUP] PATH — change node ownership (root only)."""
        args = self._args(argument)
        if len(args) != 2:
            print("usage: chown USER[:GROUP] PATH")
            return
        owner, separator, group = args[0].partition(":")
        self._run(self.fs.chown, args[1], owner, group if separator else None)

    def do_useradd(self, argument: str) -> None:
        """useradd USER [GROUP] — create a user and optional primary group."""
        args = self._args(argument)
        if not 1 <= len(args) <= 2:
            print("usage: useradd USER [GROUP]")
            return
        self._run(self.fs.add_user, *args)

    def do_groupadd(self, argument: str) -> None:
        """groupadd GROUP — create a group."""
        args = self._args(argument)
        if len(args) != 1:
            print("usage: groupadd GROUP")
            return
        self._run(self.fs.add_group, args[0])

    def do_usermod(self, argument: str) -> None:
        """usermod -aG GROUP USER — add a user to a supplementary group."""
        args = self._args(argument)
        if len(args) != 3 or args[0] != "-aG":
            print("usage: usermod -aG GROUP USER")
            return
        self._run(self.fs.add_user_to_group, args[2], args[1])

    def do_su(self, argument: str) -> None:
        """su USER — switch the active simulated user."""
        args = self._args(argument)
        if len(args) != 1:
            print("usage: su USER")
            return
        user = self._run(self.fs.switch_user, args[0])
        if user is not None:
            print(f"Switched to {user.username}")

    def do_find(self, argument: str) -> None:
        """find NAME [PATH] — search directory entries by name."""
        self._search(argument, content=False)

    def do_grep(self, argument: str) -> None:
        """grep TEXT [PATH] — search file contents."""
        self._search(argument, content=True)

    def _search(self, argument: str, content: bool) -> None:
        args = self._args(argument)
        if not 1 <= len(args) <= 2:
            command = "grep TEXT" if content else "find NAME"
            print(f"usage: {command} [PATH]")
            return
        results = self._run(
            self.fs.search,
            args[0],
            args[1] if len(args) == 2 else "/",
            content=content,
        )
        if results is not None:
            for result in results:
                print(result)

    def do_stat(self, argument: str) -> None:
        """stat PATH — display inode metadata."""
        args = self._args(argument)
        if len(args) != 1:
            print("usage: stat PATH")
            return
        metadata = self._run(self.fs.stat, args[0])
        if metadata is not None:
            for key, value in metadata.items():
                print(f"{key}: {value}")

    def do_save(self, argument: str) -> None:
        """save — persist the simulated filesystem to JSON."""
        try:
            self.fs.save()
        except (FileSystemError, OSError) as exc:
            print(f"error: could not save filesystem: {exc}")
            return
        print("Filesystem saved.")

    def do_exit(self, argument: str) -> bool:
        """exit — save the filesystem and leave the shell."""
        try:
            self.fs.save()
        except (FileSystemError, OSError) as exc:
            print(f"error: could not save filesystem: {exc}")
            return False
        print("Filesystem saved.")
        return True

    def do_EOF(self, argument: str) -> bool:
        """Ctrl-D — save the filesystem and leave the shell."""
        print()
        return self.do_exit(argument)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cree Filesystem simulator")
    parser.add_argument("--storage", default="cree-fs.json")
    parser.add_argument("--fresh", action="store_true")
    options = parser.parse_args()

    try:
        if options.fresh:
            filesystem = FileSystem(options.storage)
        else:
            try:
                filesystem = FileSystem.load(options.storage)
            except FileNotFoundError:
                filesystem = FileSystem(options.storage)
        CreeShell(filesystem).cmdloop()
    except (OSError, ValueError, FileSystemError) as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
