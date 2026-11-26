# Architecture Decision Record

## Status

Accepted.

## Overview

Cree Filesystem is a userspace filesystem simulator implemented in Python. It provides a Unix-inspired directory hierarchy, inode identity, path resolution, ownership, permissions, file operations and JSON persistence through an interactive command-line interface.

The project focuses on filesystem behaviour and clear separation of responsibilities. It does not implement a kernel filesystem or attempt to reproduce the complete Unix operating-system environment.

## Architectural decisions

### 1. Use Python's standard-library `cmd` module for the shell

The interactive shell subclasses `cmd.Cmd`. Each command is exposed through a `do_<command>()` method, and `cmd.Cmd` manages the command loop, dispatch and built-in help behaviour.

The shell is an adapter between terminal input and the filesystem API. It parses arguments, calls `FileSystem` methods and formats output. It does not own inode state, resolve paths, enforce permissions or implement filesystem mutations.

This keeps the command-line interface separate from the filesystem implementation and avoids maintaining a custom command dispatcher.

### 2. Use a central inode table

`FileSystem` owns one mapping of inode IDs to `Node` instances:

    inode_id -> Node

Each `Directory` stores child entries as:

    entry_name -> inode_id

A directory does not store nested `File` or `Directory` objects. This avoids maintaining two competing sources of truth and makes inode identity explicit.

The root directory is identified by `root_inode`. The current working directory is identified by `current_dir`. The cwd string is a display/path representation, not the identity of the current directory.

Hard links and symbolic links are not currently supported. Consequently, every non-root inode has exactly one parent.

### 3. Keep filesystem behaviour behind a single API

Responsibilities are separated as follows:

- **CreeShell:** command input, argument parsing, help, prompt and output.
- **FileSystem:** inode table, path resolution, directory traversal, filesystem operations, user/group state, permission checks at operation boundaries and persistence.
- **Node, File, Directory, User and Group:** filesystem data models and serialization.
- **PermissionManager:** owner/group/other mode evaluation and octal mode parsing.

New shell commands should delegate to existing `FileSystem` operations. Filesystem rules should not be duplicated in command handlers.

### 4. Model Unix-style ownership and permissions

Each node stores an owner UID, group GID and octal permission mode. Permission evaluation follows the owner, group and other classes. The simulated root account bypasses permission checks.

Users have a primary group and may belong to supplementary groups. User switching changes the active simulated user; it is not an authentication mechanism. Password authentication and operating-system security boundaries are outside the scope of this simulator.

### 5. Persist simulator state as versioned JSON

The save file records the inode table, directory entry references, users, groups, root inode, current directory inode and current session user.

Loading rebuilds the in-memory objects and validates references, reachability, parent counts, ownership IDs and the saved working directory before accepting the state.

The host filesystem is used only to read and write the simulator's JSON save file. Simulated files and directories are represented by the in-memory model and are not created as ordinary host filesystem entries.

### 6. Keep the feature set focused

The current feature set covers:

- Creating and removing files and directories.
- Navigating and inspecting the directory hierarchy.
- Renaming nodes while preserving inode identity.
- Enforcing owner/group/other read, write and execute permissions.
- Searching by filename and file content.
- Inspecting inode metadata.
- Saving and restoring simulator state.
- Copying and moving files or directory trees.

The project prioritises a coherent filesystem model and predictable behaviour over implementing unrelated operating-system functionality.

## Explicit non-goals

The following capabilities are intentionally outside the current project scope:

- Kernel integration, mounting, disk blocks or physical storage allocation.
- Hard links, symbolic links, journaling or crash recovery.
- GUI, networking or concurrent filesystem access.
- Full Unix shell compatibility, pipes, redirection, job control or host command execution.
- Password authentication or real process/user isolation.

These boundaries keep the implementation focused on the userspace filesystem model. They can be revisited if the project requirements change.

## Change control

Proposed features and refactors should preserve the architectural decisions above. When a change requires a decision to be revised, update this document and explain the reasoning and trade-offs in the associated change.
