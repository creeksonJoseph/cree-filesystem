# Cree Filesystem

Cree Filesystem is a Python 3 implementation of a userspace Unix-like filesystem simulator. It provides a hierarchical filesystem namespace, inode-based identity, file and directory operations, Unix-style ownership and permissions, simulated users and groups, an interactive command-line shell, and JSON persistence.

The project models core filesystem behaviour in application memory. It does **not** mount a filesystem, manage physical disk blocks, execute host commands, or provide operating-system-level isolation.

## Contents

- [Features](#features)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Running the application](#running-the-application)
- [Command reference](#command-reference)
- [Paths and command input](#paths-and-command-input)
- [Users, groups, ownership, and permissions](#users-groups-ownership-and-permissions)
- [Persistence](#persistence)
- [Python API](#python-api)
- [Testing](#testing)
- [Project structure](#project-structure)
- [Design boundaries](#design-boundaries)

## Features

- Hierarchical directory and file namespace rooted at `/`.
- Central inode table with directory entries that reference inode IDs.
- Absolute and relative path resolution, current working directory, and path normalization.
- File creation, reading, overwriting, and appending.
- Directory creation, including recursive parent creation with `mkdir -p`.
- File and directory deletion, including recursive directory removal.
- Rename and move operations that preserve the moved node's inode identity.
- File and directory copying with newly allocated inode identities for copied nodes.
- Owner, group, and other read/write/execute permission bits.
- Simulated users, primary groups, supplementary groups, and ownership changes.
- Root permission bypass within the simulator.
- Directory listings, recursive tree output, inode metadata, filename search, and content search.
- Versioned JSON save files with validation when loading.
- Interactive shell with command help, quoted arguments, and recoverable command errors.
- Automated unit, shell, workflow, and CLI-process integration tests.

## How it works

The implementation separates the terminal interface from filesystem state and behaviour.

| Component | Responsibility |
|---|---|
| `CreeShell` | Interactive REPL, prompt, command dispatch, argument parsing, help text, and terminal output. |
| `FileSystem` | Inode table, path resolution, directory traversal, filesystem operations, permissions, user/group state, and persistence. |
| Models | Represent filesystem nodes, files, directories, users, and groups. |
| `PermissionManager` | Parse octal permission modes and evaluate owner/group/other access. |

The shell acts as an adapter. A command handler parses user input, calls the corresponding `FileSystem` operation, and formats the result. Filesystem rules and inode mutations belong in the filesystem layer rather than being duplicated in shell commands.

### Inode-table model

The filesystem has one central mapping:

```text
inode_id -> Node
```

Each directory stores a mapping from entry names to inode IDs:

```text
entry_name -> inode_id
```

A directory does not embed child `Node` objects. It stores references to nodes in the central inode table. The root directory and current working directory are also tracked by inode ID.

Path resolution starts at the root inode and follows directory entries one component at a time. The current working directory's path is retained for display and relative path resolution, while its inode ID identifies the directory itself.

Hard links and symbolic links are not implemented. Consequently, each non-root inode has exactly one parent directory.

### Permission evaluation

For a non-root user, access is evaluated using the first matching class:

1. Owner bits, when the user's UID matches the node owner.
2. Group bits, when the node's group is one of the user's groups.
3. Other bits, otherwise.

The requested permission must be fully present in the selected class. The simulated root account bypasses these checks.

## Requirements

- Python 3.10 or newer.
- [uv](https://docs.astral.sh/uv/) for dependency and environment management.

The application currently has no third-party runtime dependencies. The project uses the Python standard library and setuptools for packaging.

## Installation

Clone the repository and enter the project directory:

```bash
git clone https://github.com/creeksonJoseph/cree-filesystem.git
cd cree-filesystem
```

Create the virtual environment and install the project:

```bash
uv sync
```

This installs the package in the project environment and uses the committed `uv.lock` file for reproducible dependency resolution.

## Running the application

Start the interactive shell:

```bash
uv run cree-fs
```

The default save-file path is `cree-fs.json` in the current host working directory.

Start with a new in-memory filesystem:

```bash
uv run cree-fs --fresh
```

Choose a save-file location:

```bash
uv run cree-fs --storage ./data/filesystem.json
```

The options can be combined:

```bash
uv run cree-fs --fresh --storage ./data/test-filesystem.json
```

Run the module directly instead of using the installed console command:

```bash
uv run python -m cree_filesystem
```

### Startup and shutdown behaviour

- On normal startup, the application loads the selected save file if it exists.
- If the save file does not exist, a new filesystem is initialized.
- `--fresh` starts with a new in-memory state instead of loading the existing save file. It does not immediately delete or overwrite that file; a later save can replace it.
- `save` writes the current state to the configured save file.
- `exit`, Ctrl-D (EOF), and Ctrl-C attempt to save before leaving the shell.
- A command-level error is reported to the user and does not normally terminate the interactive shell.
- A malformed or unsupported save file is rejected at startup rather than silently replaced.

The save file is stored on the host filesystem. The simulated files and directories exist inside the application's in-memory inode table; they are not created as host files.

## Command reference

Use `help` inside the shell to list commands, or `help COMMAND` for command-specific usage.

| Command | Syntax | Description |
|---|---|---|
| `help` | `help [COMMAND]` | List available commands or show help for one command. |
| `pwd` | `pwd` | Print the current simulated working directory. |
| `cd` | `cd PATH` | Change the current working directory. |
| `ls` | `ls [-a] [-l] [PATH]` | List directory entries. By default, names beginning with a dot are hidden. |
| `tree` | `tree [PATH]` | Display a directory hierarchy as a tree. Defaults to `/`. |
| `mkdir` | `mkdir [-p] PATH` | Create a directory. `-p` creates missing parent directories. |
| `touch` | `touch PATH` | Create an empty file. Existing files are not overwritten. |
| `cat` | `cat PATH` | Print a file's contents. |
| `write` | `write PATH TEXT` | Replace a file's contents with the supplied text. |
| `append` | `append PATH TEXT` | Append the supplied text to a file. |
| `rm` | `rm [-r] PATH` | Remove a file. Use `-r` (or `-R`, `--recursive`) to remove a directory tree. |
| `mv` | `mv SOURCE DESTINATION` | Move or rename a file or directory. |
| `cp` | `cp SOURCE DESTINATION` | Copy a file or directory tree. |
| `chmod` | `chmod MODE PATH` | Change a node's octal permission mode. |
| `chown` | `chown USER[:GROUP] PATH` | Change a node's owner and optionally its group. |
| `useradd` | `useradd USER [GROUP]` | Create a simulated user, optionally specifying a primary group. |
| `groupadd` | `groupadd GROUP` | Create a simulated group. |
| `usermod` | `usermod -aG GROUP USER` | Add a user to a supplementary group. |
| `su` | `su USER` | Switch the active simulated user. |
| `whoami` | `whoami` | Print the active simulated username. |
| `id` | `id` | Display the active user's UID, primary GID, and group memberships. |
| `groups` | `groups [USER]` | List the active user's groups or another user's groups. |
| `find` | `find NAME [PATH]` | Search directory entries for names containing the supplied text. |
| `grep` | `grep TEXT [PATH]` | Search file contents for the supplied text. |
| `stat` | `stat PATH` | Display inode metadata for a file or directory. |
| `save` | `save` | Persist the current simulated filesystem. |
| `exit` | `exit` | Save and leave the shell. |

### Listing options

- `ls` lists names in the target directory.
- `ls -a` or `ls --all` includes dotfiles.
- `ls -l` or `ls --long` displays type, permission string, owner UID, group GID, inode ID, and name.
- Short options can be combined: `ls -la` and `ls -al` are equivalent.
- `--` ends option parsing where supported, allowing a path beginning with a dash to be supplied as an argument.

Examples:

```text
ls /
ls -la /home
tree /var
stat /home/notes.txt
```

### File and directory operations

```text
mkdir -p /home/alex/projects/demo
touch /home/alex/projects/demo/notes.txt
write /home/alex/projects/demo/notes.txt "first version"
append /home/alex/projects/demo/notes.txt " - updated"
cat /home/alex/projects/demo/notes.txt

cp /home/alex/projects/demo/notes.txt /home/alex/notes-copy.txt
mv /home/alex/notes-copy.txt /home/alex/archive.txt
rm /home/alex/archive.txt
rm -r /home/alex/projects
```

Copying creates new nodes with new inode IDs. Moving or renaming changes directory entries while retaining the moved node's inode identity.

### Search

`find` searches names in a directory hierarchy. `grep` searches file contents; it does not match a file merely because its name contains the query.

```text
find report /home
grep "error" /var/log
```

## Paths and command input

- The simulated namespace starts at `/`.
- Absolute paths begin with `/`; relative paths are resolved from the current working directory.
- `.` and `..` are normalized during path resolution.
- Directory and file names may contain spaces.
- The shell uses shell-style quoting through Python's `shlex` parser. Quote paths and text containing spaces.

```text
mkdir "/home/project files"
touch "/home/project files/meeting notes.txt"
write "/home/project files/meeting notes.txt" "notes from the meeting"
cat "/home/project files/meeting notes.txt"
```

The `write` and `append` commands take the first parsed argument as the path and join the remaining parsed arguments with spaces. They are intended for simple text content, not multiline terminal input or shell redirection. Escape sequences such as `\\n` are stored as literal characters rather than converted into line breaks.

## Users, groups, ownership, and permissions

The initial filesystem contains a simulated `root` user (UID 0) and `root` group (GID 0). New users and groups receive numeric IDs managed by the simulator.

Users have:
- A username and UID.
- One primary GID.
- Zero or more supplementary group memberships.

Nodes store:
- Owner UID.
- Group GID.
- Permission mode.

### Octal modes

Permission modes use the conventional three-digit owner/group/other representation. Each digit is the sum of read (4), write (2), and execute (1):

| Digit | Permissions |
|---|---|
| `7` | read, write, execute |
| `6` | read, write |
| `5` | read, execute |
| `4` | read |
| `3` | write, execute |
| `2` | write |
| `1` | execute |
| `0` | no permissions |

For example, `640` means:
- Owner: read and write.
- Group: read.
- Others: no access.

```text
groupadd engineering
useradd alice
usermod -aG engineering alice
chown alice:engineering /srv/project/report.txt
chmod 640 /srv/project/report.txt
stat /srv/project/report.txt
su alice
whoami
id
groups
```

The simulator enforces permissions during operations. Directory execute permission is required to traverse a directory; directory read permission is required to list its entries. Creating or removing entries requires write and execute permission on the parent directory. File reads and writes require the corresponding file permission.

The simulated root account bypasses permission checks. User switching is a development and simulation feature, not authentication: there are no passwords, login sessions, process credentials, or host operating-system security boundaries. It must not be treated as a security sandbox.

## Persistence

Filesystem state is stored as JSON in the configured host-side save file. The versioned document includes:

- Save-format version.
- Inode table and node data.
- Directory entry name-to-inode references.
- Root inode identity.
- User and group records.
- Current working directory path and inode identity.
- Current simulated user.

File contents are stored in the JSON representation. Timestamps are stored as ISO 8601 strings in UTC.

The current save format version is `2`. Loading reconstructs the in-memory models and validates the state before accepting it. Validation includes inode references, directory entry consistency, reachability from the root, parent counts, user/group ownership references, and consistency between the saved working-directory path and inode.

Saving writes through a temporary file and replaces the target save file after serialization. This reduces the chance of leaving a partially written save file if the write is interrupted, but it is not a journaling or full crash-recovery system.

Do not manually edit a save file unless you understand the data model and validation rules. Invalid, corrupt, or unsupported save data is rejected.

## Python API

The filesystem engine can be used without starting the interactive shell. Import `FileSystem` from the package:

```python
from cree_filesystem import FileSystem

# Create an in-memory filesystem. The optional path configures persistence.
fs = FileSystem("filesystem.json")

fs.mkdir("/workspace", parents=True)
fs.create_file("/workspace/readme.txt", content="Hello from Python")
print(fs.read_file("/workspace/readme.txt"))

fs.write_file("/workspace/readme.txt", "Updated content")
fs.write_file("/workspace/readme.txt", " plus more", append=True)

print(fs.list_dir("/workspace"))
print(fs.stat("/workspace/readme.txt"))
print(fs.tree("/"))

fs.save()
```

To restore a saved filesystem:

```python
from cree_filesystem import FileSystem

fs = FileSystem.load("filesystem.json")
print(fs.cwd)
print(fs.read_file("/workspace/readme.txt"))
```

### Main `FileSystem` operations

| Method | Purpose |
|---|---|
| `resolve(path, user=None)` | Resolve a path to its node, optionally checking access as another simulated user. |
| `mkdir(path, mode=0o755, parents=False)` | Create a directory, optionally creating missing parents. |
| `create_file(path, content="", mode=0o644)` | Create a file. |
| `read_file(path)` | Read file contents. |
| `write_file(path, content, append=False)` | Replace or append file contents. |
| `list_dir(path=".")` | Return metadata for entries in a directory. |
| `change_directory(path)` | Change the current working directory. |
| `remove(path, recursive=False)` | Remove a file or directory tree. |
| `rename(source, destination)` | Rename a node. |
| `move(source, destination)` | Move a node to another directory or path. |
| `copy(source, destination)` | Copy a file or directory tree. |
| `chmod(path, mode)` | Change permission mode. |
| `chown(path, username, groupname=None)` | Change ownership. |
| `add_user(username, groupname=None)` | Create a simulated user. |
| `add_group(name)` | Create a simulated group. |
| `add_user_to_group(username, groupname)` | Add supplementary group membership. |
| `switch_user(username)` | Change the active simulated user. |
| `group_ids(user)` | Return a user's primary and supplementary GIDs. |
| `search(query, path="/", content=False)` | Search names or file contents below a path. |
| `tree(path="/")` | Return a formatted directory tree. |
| `stat(path)` | Return metadata for a node. |
| `save(path=None)` | Save to the configured path or an explicitly supplied path. |
| `FileSystem.load(path)` | Load and validate a saved filesystem. |

Filesystem operations raise `FileSystemError` when an operation cannot be completed. Permission failures are represented by `PermissionDenied`, which is a `PermissionError` subclass. Invalid permission modes and other invalid arguments may raise `ValueError`.

The public package also exposes the filesystem models and permission types through its package modules. The interactive CLI is an optional interface over the same filesystem engine.

## Testing

Run the complete test suite from the repository root:

```bash
uv run python -m unittest discover -s tests -v
```

The tests cover filesystem operations, command parsing and behaviour, shell workflows, error handling, shutdown behaviour, and end-to-end CLI workflows. CLI integration tests start the application as a separate Python process, send commands through standard input, inspect standard output and error, and verify that state survives a process restart.

Tests use temporary directories and isolated save files; they do not need to modify the default `cree-fs.json` file.

## Project structure

```text
cree-filesystem/
├── src/
│   └── cree_filesystem/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── filesystem.py
│       ├── models.py
│       └── permissions.py
├── tests/
│   ├── helpers.py
│   ├── test_cli_integration.py
│   ├── test_shell_commands.py
│   ├── test_shell_resilience.py
│   ├── test_shell_shutdown.py
│   └── test_shell_workflows.py
├── docs/
│   └── architecture.md
├── pyproject.toml
├── uv.lock
└── README.md
```

## Design boundaries

Cree Filesystem focuses on filesystem concepts that can be modelled in a single-process Python application.

Not currently implemented:

- Kernel integration, mounting, FUSE integration, or physical disk/block allocation.
- Hard links and symbolic links.
- Journaling, snapshots, or crash recovery.
- Concurrent access, locking, or multi-process coordination.
- GUI, networking, pipes, redirection, job control, or full POSIX shell compatibility.
- Password authentication, real user isolation, or host operating-system security enforcement.
- Full POSIX metadata and semantics such as ACLs, special permission bits, devices, sockets, and symbolic-link handling.

These are explicit boundaries of the current implementation, not guarantees that the simulator behaves exactly like a production Unix filesystem. The host filesystem is used only for the JSON persistence file.

## Contributing

Changes should preserve the separation between the shell adapter and filesystem engine. New commands should delegate to filesystem operations, and filesystem rules should remain in the `FileSystem` layer rather than being reimplemented in command handlers.

When changing inode relationships, permission behaviour, or persistence, update the relevant tests and documentation. Run the complete test suite before submitting a change.

## License

No license has been declared in this repository yet. Until a license is added, the project should not be assumed to grant permissions to use, modify, or redistribute its code.
