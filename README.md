# Cree Filesystem

Cree Filesystem is a Python 3 simulation of a Unix-like filesystem. It models a directory tree, files, users, groups, ownership, Unix-style permissions and persistent storage. It is an educational userspace simulation, not a kernel filesystem or a Linux clone.

## Architecture

- Models: users, groups, files, directories, inode-like identifiers and metadata.
- Permissions: owner/group/other read, write and execute checks, including root bypass.
- Filesystem: path resolution, directory traversal, file operations, search and JSON persistence.
- CLI: interactive shell exposing the filesystem operations.

The simulated filesystem is rooted at /. Paths are resolved inside the simulated tree. The host filesystem is used only for the JSON save file.

## Features

- Create directories and files; read and write file contents.
- List directories and inspect the hierarchy.
- Rename, move, copy and remove files/directories.
- Octal permissions such as 755 and 644 with owner/group/other access checks.
- Simulated users and groups, ownership changes and root permission bypass.
- Search by filename or file content.
- Metadata: inode-like ID, owner, group, mode and timestamps.
- Save and restore the complete filesystem state as JSON.

Hard links, symbolic links, GUI, kernel integration and full Unix command compatibility are intentionally out of scope.

## Run

Requires Python 3.10 or newer.

    python -m venv .venv
    source .venv/bin/activate
    pip install -e .
    cree-fs

Or run without installing:

    PYTHONPATH=src python -m cree_filesystem

Use --fresh to start with a clean in-memory filesystem. The default save file is cree-fs.json in the current working directory. The shell saves automatically on exit.

## Example

    root@cree:/$ mkdir /home
    root@cree:/$ mkdir /home/joseph
    root@cree:/$ touch /home/joseph/notes.txt
    root@cree:/$ write /home/joseph/notes.txt Hello filesystem
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

This project applies Unix-inspired concepts to an in-memory tree. It does not mount a disk, alter host permissions, execute host commands, or provide operating-system-level isolation. JSON is the simulator's persistence format.
