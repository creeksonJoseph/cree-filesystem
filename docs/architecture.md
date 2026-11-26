# Architecture Decision Record

## Status

Accepted for the current assignment.

## Context

The project models a small Unix-inspired filesystem in Python. The objective is to demonstrate filesystem concepts—hierarchy, inode identity, path traversal, ownership, permissions, file operations and persistence—without implementing a kernel filesystem or reproducing the full Unix userland.

The implementation must remain achievable within the assignment time budget. Features that do not strengthen the required filesystem model are deliberately excluded.

## Decisions

### 1. Use Python's standard-library cmd module for the shell

The interactive shell subclasses cmd.Cmd. Each command is exposed through a do_<command>() method, and cmd.Cmd owns the command loop, dispatch and built-in help behaviour.

The shell is an adapter between terminal input and the filesystem API. It parses arguments, calls FileSystem methods and formats output. It must not own inode state, resolve paths, enforce permissions or implement filesystem mutations.

A hand-written input loop or a separate custom command dispatcher is not used.

### 2. Use a central inode table

FileSystem owns one mapping of inode IDs to Node instances:

    inode_id -> Node

Each Directory stores child entries as:

    entry_name -> inode_id

A directory must not store nested File or Directory objects. This avoids maintaining two competing sources of truth and makes inode identity explicit.

The root directory is identified by root_inode. The current working directory is identified by current_dir. The cwd string is a display/path representation, not the identity of the current directory.

Hard links and symbolic links are excluded. Therefore, every non-root inode has exactly one parent.

### 3. Keep filesystem behaviour behind a single API

The responsibilities are separated as follows:

- CreeShell: command input, argument parsing, help, prompt and output.
- FileSystem: inode table, path resolution, directory traversal, operations, user/group state, permission checks at operation boundaries and persistence.
- Node, File, Directory, User and Group: filesystem data models and serialization.
- PermissionManager: owner/group/other mode evaluation and octal mode parsing.

New shell commands should delegate to existing FileSystem operations. Filesystem rules should not be duplicated in command handlers.

### 4. Model Unix-style ownership and permissions

Each node stores an owner UID, group GID and octal permission mode. Permission evaluation follows owner, then group, then other. The simulated root account bypasses permission checks.

Users have a primary group and may belong to supplementary groups. User switching is a simulation convenience; password authentication and operating-system security boundaries are not part of the assignment.

### 5. Persist simulator state as versioned JSON

The save file records the inode table, directory entry references, users, groups, root inode, current directory inode and current session user.

Loading must rebuild the in-memory objects and validate references, reachability, parent counts, ownership IDs and the saved working directory before accepting the state.

The host filesystem is used only to read and write the simulator's JSON save file.

### 6. Keep the feature set bounded

Required capabilities:

- Create and remove files/directories.
- Navigate and inspect the directory hierarchy.
- Rename nodes and preserve inode identity.
- Enforce owner/group/other read, write and execute permissions.
- Search by filename and file content.
- Inspect inode metadata.
- Save and restore state.

Copy and move are useful secondary operations. The implementation should not add unrelated operating-system features at the expense of completing the required capabilities.

## Explicit non-goals

- Kernel integration, mounting, disk blocks or physical storage allocation.
- Hard links, symbolic links, journaling or crash recovery.
- GUI, networking or concurrent filesystem access.
- Full Unix shell compatibility, pipes, redirection, job control or host command execution.
- Password authentication or real process/user isolation.

## Change control

A proposed feature or refactor should preserve the decisions above. If a decision must change, update this document and explain the trade-off in the pull request before changing the implementation.
