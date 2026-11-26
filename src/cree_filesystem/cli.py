"""Interactive CLI for Cree Filesystem."""
import argparse
import shlex
import sys
from .filesystem import FileSystem, FileSystemError
from .permissions import PermissionDenied

HELP = """Commands:
  help                         Show help
  pwd                          Print current directory
  ls [path]                    List directory contents
  tree [path]                  Display directory hierarchy
  cd <path>                    Change directory
  mkdir [-p] <path>            Create directory
  touch <path>                 Create empty file
  cat <path>                   Read file
  write <path> <text>          Replace file contents
  append <path> <text>         Append file contents
  rm [-r] <path>               Remove file or directory
  mv <source> <destination>    Move or rename
  cp <source> <destination>    Copy file or directory
  chmod <mode> <path>          Change permissions
  chown <user> [group] <path>  Change ownership (root only)
  useradd <name> [group]       Add simulated user (root only)
  groupadd <name>              Add simulated group (root only)
  su <username>                Switch simulated user
  find <name> [path]           Search filenames
  grep <text> [path]           Search file contents
  stat <path>                  Show metadata
  save                         Save filesystem
  exit                         Save and quit
"""


def display_entries(entries: list[dict]) -> None:
    if not entries:
        print("(empty)")
        return
    print(f"{'TYPE':<10} {'MODE':<6} {'OWNER':<8} {'GROUP':<8} {'INODE':<14} NAME")
    for item in entries:
        print(f"{item['type']:<10} {item['mode']:<6} {item['owner_uid']:<8} "
              f"{item['group_gid']:<8} {item['inode']:<14} {item['name']}")


def run_shell(fs: FileSystem) -> None:
    print("Cree Filesystem — Unix-inspired filesystem simulator")
    print("Type 'help' for commands.")
    while True:
        try:
            line = input(f"{fs.current_user.username}@cree:{fs.cwd}$ ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line.strip():
            continue
        try:
            parts = shlex.split(line)
            command, *args = parts
            if command == "help":
                print(HELP)
            elif command == "exit":
                fs.save()
                print("Filesystem saved.")
                break
            elif command == "pwd":
                print(fs.cwd)
            elif command == "ls":
                display_entries(fs.list_dir(args[0] if args else "."))
            elif command == "tree":
                print(fs.tree(args[0] if args else "/"))
            elif command == "cd":
                print(fs.change_directory(args[0]))
            elif command == "mkdir":
                parents = "-p" in args
                fs.mkdir(next(a for a in args if a != "-p"), parents=parents)
            elif command == "touch":
                fs.create_file(args[0])
            elif command == "cat":
                print(fs.read_file(args[0]))
            elif command in ("write", "append"):
                fs.write_file(args[0], " ".join(args[1:]), append=command == "append")
            elif command == "rm":
                recursive = "-r" in args
                fs.remove(next(a for a in args if a != "-r"), recursive=recursive)
            elif command in ("mv", "cp"):
                (fs.move if command == "mv" else fs.copy)(args[0], args[1])
            elif command == "chmod":
                fs.chmod(args[1], args[0])
            elif command == "chown":
                fs.chown(args[-1], args[0], args[1] if len(args) == 3 else None)
            elif command == "useradd":
                fs.add_user(args[0], args[1] if len(args) > 1 else None)
            elif command == "groupadd":
                fs.add_group(args[0])
            elif command == "su":
                fs.switch_user(args[0])
                print(f"Switched to {fs.current_user.username}")
            elif command in ("find", "grep"):
                for result in fs.search(args[0], args[1] if len(args) > 1 else "/",
                                         content=command == "grep"):
                    print(result)
            elif command == "stat":
                for key, value in fs.stat(args[0]).items():
                    print(f"{key}: {value}")
            elif command == "save":
                fs.save()
                print("Filesystem saved.")
            else:
                print(f"Unknown command: {command}. Type 'help'.")
        except (IndexError, StopIteration, ValueError, FileSystemError, PermissionDenied) as exc:
            print(f"error: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cree Filesystem simulator")
    parser.add_argument("--storage", default="cree-fs.json")
    parser.add_argument("--fresh", action="store_true")
    options = parser.parse_args()
    try:
        fs = FileSystem(options.storage)
        if not options.fresh:
            try:
                fs = FileSystem.load(options.storage)
            except FileNotFoundError:
                pass
        run_shell(fs)
    except (OSError, ValueError, FileSystemError) as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
