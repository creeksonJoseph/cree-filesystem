# Cree Filesystem

Cree Filesystem is a Python 3 simulation of a Unix-like filesystem. It models files, directories, inode identities, users, groups, ownership, Unix-style permissions and persistent storage. It is an educational userspace simulation, not a kernel filesystem or a Linux clone.

## Architecture

The implementation follows a small layered design:

- **Shell (\`cmd.Cmd\`)** — owns the interactive command loop, prompt, help, command parsing and terminal output. Each shell command is implemented as a \`do_<command>()\` method. The shell delegates operations; it does not implement filesystem rules.
- **Filesystem** — owns the inode table, root inode, current-directory inode, path resolution, directory traversal, file operations, permission enforcement and JSON persistence.
- **Models** — represent inodes, files, directories, users and groups.
- **Permissions** — centralizes owner/group/other permission checks and octal mode parsing.

### Inode-table model

The filesystem keeps a central mapping of inode IDs to node objects. A directory stores entries as \`name -> inode_id\` references; it does not own nested file or directory objects. The root and current working directory are tracked by inode ID. Paths are resolved by traversing directory entries from the root inode.

The simulated filesystem is rooted at \`/\`. Paths are resolved only inside this in-memory tree. The host filesystem is used only for the JSON save file.

## Features

- Create directories and files; read and write file contents.
- List directories and inspect the hierarchy.
- Rename, move, copy and remove files/directories.
- Octal permissions such as \`755\` and \`644\` with owner/group/other access checks.
- Simulated users and groups, ownership changes and root permission bypass.
- Search by filename or file content.
- Metadata including inode ID, owner, group, mode and timestamps.
- Save and restore the filesystem state as JSON.

Hard links, symbolic links, GUI, real disk allocation, journaling, networking, concurrency, kernel integration and full Unix shell compatibility are intentionally out of scope.

## Run

Requires Python 3.10 or newer.

    python -m venv .venv
    source .venv/bin/activate
    pip install -e .
    cree-fs

Or run without installing:

    PYTHONPATH=src python -m cree_filesystem

Use \`--fresh\` to start with a clean in-memory filesystem. The default save file is \`cree-fs.json\` in the current working directory. The shell saves when \`exit\` or Ctrl-D is used.

## Example

    root@cree:/$ mkdir /home
    root@cree:/$ mkdir /home/joseph
    root@cree:/$ touch /home/joseph/notes.txt
    root@cree:/$ write /home/joseph/notes.txt "Hello filesystem"
    root@cree:/$ cat /home/joseph/notes.txt
    Hello filesystem
    root@cree:/$ tree /
    /
    └── home
        └── joseph
            └── notes.txt

## Python API

    from cree_filesystem import FileSystem

    fs = FileSystem("cree-fs.json")
    fs.mkdir("/home")
    fs.create_file("/home/hello.txt", "Hello!")
    print(fs.read_file("/home/hello.txt"))
    fs.save()

## Scope

This project applies Unix-inspired filesystem concepts to an in-memory inode table. It does not mount a disk, alter host permissions, execute host commands, or provide operating-system-level isolation. JSON is the simulator's persistence format.
