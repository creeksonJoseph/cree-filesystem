# Cree Filesystem

Cree Filesystem is a Python 3 userspace simulation of a Unix-like filesystem. It models an inode table, directory entries, file contents, users, groups, ownership, Unix-style permissions and JSON persistence. It does not mount a real filesystem or execute host operating-system commands.

## Architecture

The project uses a layered design with explicit ownership of responsibilities:

- **Interactive shell — cmd.Cmd:** owns the REPL, prompt, command dispatch, help, argument parsing and terminal output. Commands are implemented as do_<command>() methods. The shell delegates filesystem behaviour and does not manipulate inode state directly.
- **Filesystem — FileSystem:** owns the inode table, root/current-directory inode IDs, path resolution, directory traversal, file operations, permission enforcement, user/group state and persistence.
- **Models:** represent inodes, files, directories, users and groups.
- **Permission manager:** centralizes owner/group/other permission checks and octal mode parsing.

### Inode-table model

The filesystem stores nodes in one central mapping:

- inode_id -> Node in the filesystem inode table.
- entry_name -> inode_id in each directory's children mapping.
- The root directory and current working directory are tracked by inode ID.

Directories do not contain nested Node objects. Path lookup starts at the root inode and follows directory entries one component at a time. Hard links and symbolic links are not implemented, so each non-root inode has exactly one parent.

The simulated namespace is rooted at /. The host filesystem is used only for the JSON persistence file.

## Requirements

- Python 3.10 or newer.
- uv for environment and project management.

## Setup

From the repository root:

    uv sync

This creates .venv, installs the project in editable mode and uses the committed uv.lock to keep the environment reproducible.

Start the interactive shell:

    uv run cree-fs

Start with a fresh in-memory filesystem:

    uv run cree-fs --fresh

Choose a persistence file:

    uv run cree-fs --storage ./data/filesystem.json

The default persistence file is cree-fs.json in the current working directory. The shell saves when save, exit or Ctrl-D is used. --fresh starts with a clean state; it does not delete an existing save file until the new state is saved.

## Shell commands

| Command | Purpose |
|---|---|
| help | List commands or show command help |
| pwd, cd PATH | Print or change the working directory |
| ls [-a] [-l] [PATH], tree [PATH] | List names by default; `-l` shows metadata and `-a` includes dotfiles |
| mkdir [-p] PATH, touch PATH | Create directories or files |
| cat PATH, write PATH TEXT, append PATH TEXT | Read or modify file contents |
| rm [-r] PATH | Remove a file or directory |
| mv SOURCE DEST, cp SOURCE DEST | Move/rename or copy nodes |
| chmod MODE PATH, chown USER[:GROUP] PATH | Change permissions or ownership |
| useradd USER [GROUP], groupadd GROUP | Create simulated users and groups |
| usermod -aG GROUP USER | Add a user to a supplementary group |
| su USER, whoami, id, groups [USER] | Switch or inspect simulated identity |
| find NAME [PATH], grep TEXT [PATH] | Search names or file contents |
| stat PATH | Display inode metadata |
| save, exit | Persist state or save and leave |

Arguments containing spaces should be quoted:

    mkdir "/home/project files"
    write "/home/project files/notes.txt" "filesystem assignment"

## Permissions

Permission modes use the familiar octal owner/group/other representation:

- 7 — read, write and execute.
- 6 — read and write.
- 5 — read and execute.
- 4 — read only.
- 0 — no permissions.

For example, chmod 640 report.txt grants read/write to the owner, read to the group and no access to others. Directory traversal requires execute permission; listing/searching directory entries requires read permission, and recursive traversal requires execute permission.

The simulator includes a root user with permission bypass. User switching is a simulation convenience, not an authentication system: there are no passwords, sessions or host security boundaries.

## Example session

    root@cree:/$ mkdir -p /home/joseph/projects
    root@cree:/$ touch /home/joseph/projects/notes.txt
    root@cree:/$ write /home/joseph/projects/notes.txt "Hello filesystem"
    root@cree:/$ cat /home/joseph/projects/notes.txt
    Hello filesystem
    root@cree:/$ chmod 640 /home/joseph/projects/notes.txt
    root@cree:/$ tree /
    /
    └── home
        └── joseph
            └── projects
                └── notes.txt

## Persistence format

The JSON save contains the format version, inode table, directory entry references, user/group records and current session state. Loading validates inode references, reachability, parent counts, ownership IDs and the saved working directory before accepting the state.

## Scope

Included:

- In-memory hierarchical filesystem and path traversal.
- Inode identities and directory name-to-inode references.
- File and directory creation, reading, writing, listing, renaming, moving, copying and deletion.
- Owner/group/other rwx permissions, UID/GID ownership, supplementary groups and root bypass.
- Metadata, filename/content search and JSON persistence.
- Interactive Unix-inspired command interface built with Python's standard-library cmd module.

Intentionally excluded:

- Kernel integration, mounting, real disk allocation and block management.
- Hard links, symbolic links, journaling and crash recovery.
- GUI, networking, concurrency and full Unix shell compatibility.
- Password authentication, process permissions and host operating-system isolation.

This is an educational filesystem model, not a secure sandbox or a replacement for a real operating-system filesystem.
