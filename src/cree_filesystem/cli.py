"""Interactive Unix-like shell built on Python's cmd module."""
import argparse
import cmd
import shlex
import sys

from .filesystem import FileSystem, FileSystemError
from .permissions import PermissionDenied


class CreeShell(cmd.Cmd):
    """Translate shell commands into FileSystem operations.

    The shell owns command parsing and presentation only. Filesystem rules,
    path resolution, permissions and persistence stay in FileSystem.
    """

    intro = "Cree Filesystem — Unix-inspired filesystem simulator. Type 'help' for commands."
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

    @staticmethod
    def _args(argument: str) -> list[str]:
        return shlex.split(argument)

    def emptyline(self) -> None:
        """Do not repeat the previous command on an empty line."""

    def default(self, line: str) -> None:
        command = line.split(maxsplit=1)[0] if line.strip() else line
        print(f"{command}: command not found")

    def _run(self, operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except (IndexError, StopIteration, ValueError, FileSystemError,
                PermissionDenied) as exc:
            print(f"{type(exc).__name__}: {exc}")
            return None

    def do_pwd(self, argument: str) -> None:
        """pwd — print the current directory."""
        print(self.fs.cwd)

    def do_ls(self, argument: str) -> None:
        """ls [PATH] — list directory contents."""
        args = self._args(argument)
        entries = self._run(self.fs.list_dir, args[0] if args else ".")
        if entries is None:
            return
        for item in entries:
            kind = "d" if item["type"] == "directory" else "-"
            print(f"{kind}{item['mode']} {item['owner_uid']}:{item['group_gid']} "
                  f"{item['inode']} {item['name']}")

    def do_tree(self, argument: str) -> None:
        """tree [PATH] — display the directory hierarchy."""
        args = self._args(argument)
        result = self._run(self.fs.tree, args[0] if args else "/")
        if result is not None:
            print(result)

    def do_cd(self, argument: str) -> None:
        """cd PATH — change the current directory."""
        args = self._args(argument)
        if len(args) != 1:
            print("usage: cd PATH")
            return
        self._run(self.fs.change_directory, args[0])

    def do_mkdir(self, argument: str) -> None:
        """mkdir [-p] PATH — create a directory."""
        args = self._args(argument)
        parents = "-p" in args
        paths = [arg for arg in args if arg != "-p"]
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
        result = self._run(self.fs.read_file, args[0])
        if result is not None:
            print(result)

    def _write(self, argument: str, append: bool) -> None:
        args = self._args(argument)
        if len(args) < 2:
            print(f"usage: {'append' if append else 'write'} PATH TEXT")
            return
        self._run(self.fs.write_file, args[0], " ".join(args[1:]), append=append)

    def do_write(self, argument: str) -> None:
        """write PATH TEXT — replace a file's contents."""
        self._write(argument, append=False)

    def do_append(self, argument: str) -> None:
        """append PATH TEXT — append to a file's contents."""
        self._write(argument, append=True)

    def do_rm(self, argument: str) -> None:
        """rm [-r] PATH — remove a file or directory."""
        args = self._args(argument)
        recursive = "-r" in args
        paths = [arg for arg in args if arg != "-r"]
        if len(paths) != 1:
            print("usage: rm [-r] PATH")
            return
        self._run(self.fs.remove, paths[0], recursive=recursive)

    def do_mv(self, argument: str) -> None:
        """mv SOURCE DESTINATION — move or rename a node."""
        args = self._args(argument)
        if len(args) != 2:
            print("usage: mv SOURCE DESTINATION")
            return
        self._run(self.fs.move, *args)

    def do_cp(self, argument: str) -> None:
        """cp SOURCE DESTINATION — copy a node."""
        args = self._args(argument)
        if len(args) != 2:
            print("usage: cp SOURCE DESTINATION")
            return
        self._run(self.fs.copy, *args)

    def do_chmod(self, argument: str) -> None:
        """chmod MODE PATH — change Unix-style permissions."""
        args = self._args(argument)
        if len(args) != 2:
            print("usage: chmod MODE PATH")
            return
        self._run(self.fs.chmod, args[1], args[0])

    def do_chown(self, argument: str) -> None:
        """chown USER[:GROUP] PATH — change ownership (root only)."""
        args = self._args(argument)
        if len(args) != 2:
            print("usage: chown USER[:GROUP] PATH")
            return
        owner, separator, group = args[0].partition(":")
        self._run(self.fs.chown, args[1], owner, group if separator else None)

    def do_useradd(self, argument: str) -> None:
        """useradd USER [GROUP] — add a simulated user (root only)."""
        args = self._args(argument)
        if not 1 <= len(args) <= 2:
            print("usage: useradd USER [GROUP]")
            return
        self._run(self.fs.add_user, *args)

    def do_groupadd(self, argument: str) -> None:
        """groupadd GROUP — add a simulated group (root only)."""
        args = self._args(argument)
        if len(args) != 1:
            print("usage: groupadd GROUP")
            return
        self._run(self.fs.add_group, args[0])

    def do_su(self, argument: str) -> None:
        """su USER — switch the simulated user."""
        args = self._args(argument)
        if len(args) != 1:
            print("usage: su USER")
            return
        user = self._run(self.fs.switch_user, args[0])
        if user is not None:
            print(f"Switched to {user.username}")

    def do_find(self, argument: str) -> None:
        """find NAME [PATH] — search names in the filesystem."""
        self._search(argument, content=False)

    def do_grep(self, argument: str) -> None:
        """grep TEXT [PATH] — search file contents."""
        self._search(argument, content=True)

    def _search(self, argument: str, content: bool) -> None:
        args = self._args(argument)
        if not 1 <= len(args) <= 2:
            print(f"usage: {'grep TEXT' if content else 'find NAME'} [PATH]")
            return
        results = self._run(self.fs.search, args[0],
                            args[1] if len(args) == 2 else "/",
                            content=content)
        if results is not None:
            for result in results:
                print(result)

    def do_stat(self, argument: str) -> None:
        """stat PATH — display node metadata."""
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
            print("Filesystem saved.")
        except (OSError, FileSystemError) as exc:
            print(f"error: {exc}")

    def do_exit(self, argument: str) -> bool:
        """exit — save and leave the shell."""
        self.do_save(argument)
        return True

    def do_EOF(self, argument: str) -> bool:
        """Ctrl-D — save and leave the shell."""
        print()
        return self.do_exit(argument)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cree Filesystem simulator")
    parser.add_argument("--storage", default="cree-fs.json")
    parser.add_argument("--fresh", action="store_true")
    options = parser.parse_args()

    try:
        if options.fresh:
            fs = FileSystem(options.storage)
        else:
            try:
                fs = FileSystem.load(options.storage)
            except FileNotFoundError:
                fs = FileSystem(options.storage)
        CreeShell(fs).cmdloop()
    except (OSError, ValueError, FileSystemError) as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
