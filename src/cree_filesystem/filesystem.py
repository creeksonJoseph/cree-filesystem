"""In-memory inode-table filesystem with Unix-style permissions and JSON persistence."""
from __future__ import annotations

import json
import posixpath
import uuid
from pathlib import Path

from .models import Directory, File, Group, Node, User, node_from_dict
from .permissions import PermissionDenied, PermissionManager as PM


class FileSystemError(Exception):
    """Raised when a filesystem operation cannot be completed."""


class FileSystem:
    """Owns filesystem state and operations independently of the interactive shell."""

    VERSION = 2

    def __init__(self, storage_path: str | Path | None = None) -> None:
        self.storage_path = Path(storage_path) if storage_path else None
        root_user = User("root", 0, 0, True)
        root_group = Group("root", 0, [0])
        self.users: dict[str, User] = {root_user.username: root_user}
        self.groups: dict[str, Group] = {root_group.name: root_group}

        root = Directory("/", 0, 0, 0o755)
        self.root_inode = root.inode
        self.inodes: dict[str, Node] = {root.inode: root}
        self.current_dir = root.inode
        self.cwd = "/"
        self.current_user = root_user

    @property
    def groups_by_gid(self) -> dict[int, Group]:
        """Return the group table indexed by numeric GID."""
        return {group.gid: group for group in self.groups.values()}

    @property
    def root(self) -> Directory:
        node = self.inodes[self.root_inode]
        if not isinstance(node, Directory):
            raise FileSystemError("The root inode must reference a directory")
        return node

    def group_ids(self, user: User) -> set[int]:
        """Return a user's primary and supplementary group IDs."""
        return (
            {group.gid for group in self.groups.values() if user.uid in group.members}
            | {user.primary_gid}
        )

    def _absolute(self, path: str) -> str:
        if not isinstance(path, str) or not path:
            raise FileSystemError("Path must be a non-empty string")
        combined = path if path.startswith("/") else posixpath.join(self.cwd, path)
        normalized = posixpath.normpath(combined)
        if normalized.startswith("//"):
            normalized = "/" + normalized.lstrip("/")
        return normalized

    def _parts(self, path: str) -> list[str]:
        return [part for part in self._absolute(path).split("/") if part]

    def _require(self, node: Node, permission: int) -> None:
        PM.require(node, self.current_user, self.group_ids(self.current_user), permission)

    def resolve(self, path: str, user: User | None = None) -> Node:
        """Resolve a path by walking directory name-to-inode entries from root."""
        actor = user or self.current_user
        inode = self.root_inode
        for part in self._parts(path):
            directory = self.inodes.get(inode)
            if not isinstance(directory, Directory):
                raise FileSystemError("A path component is not a directory")
            PM.require(directory, actor, self.group_ids(actor), PM.EXECUTE)
            child_inode = directory.children.get(part)
            if child_inode is None:
                raise FileSystemError(f"No such file or directory: {path}")
            child = self.inodes.get(child_inode)
            if child is None:
                raise FileSystemError(f"Corrupt inode reference: {child_inode}")
            inode = child_inode
        return self.inodes[inode]

    def _parent(self, path: str) -> tuple[Directory, str]:
        absolute = self._absolute(path)
        name = posixpath.basename(absolute)
        if absolute == "/" or name in ("", ".", ".."):
            raise FileSystemError("A valid file or directory name is required")
        if "/" in name:
            raise FileSystemError("Names cannot contain '/'")
        parent_path = posixpath.dirname(absolute) or "/"
        parent = self.resolve(parent_path)
        if not isinstance(parent, Directory):
            raise FileSystemError(f"Not a directory: {parent_path}")
        self._require(parent, PM.WRITE | PM.EXECUTE)
        return parent, name

    def _attributes(self, name: str, mode: int | str) -> dict:
        return {
            "name": name,
            "owner_uid": self.current_user.uid,
            "group_gid": self.current_user.primary_gid,
            "mode": PM.parse_mode(mode),
        }

    def _register(self, parent: Directory, name: str, node: Node) -> Node:
        if name in parent.children:
            raise FileSystemError(f"Already exists: {name}")
        self.inodes[node.inode] = node
        parent.children[name] = node.inode
        parent.touch()
        return node

    def mkdir(
        self, path: str, mode: int | str = 0o755, parents: bool = False
    ) -> Directory:
        if parents:
            parsed_mode = PM.parse_mode(mode)
            current = self.root
            created: list[tuple[Directory, str, str, str]] = []
            try:
                for part in self._parts(path):
                    self._require(current, PM.EXECUTE)
                    child_inode = current.children.get(part)
                    if child_inode is not None:
                        child = self.inodes.get(child_inode)
                        if not isinstance(child, Directory):
                            raise FileSystemError(
                                f"Path component exists and is not a directory: {part}"
                            )
                        current = child
                        continue
                    self._require(current, PM.WRITE | PM.EXECUTE)
                    prev_mtime = current.modified_at
                    child = Directory(**self._attributes(part, parsed_mode))
                    self._register(current, part, child)
                    created.append((current, part, child.inode, prev_mtime))
                    current = child
                return current
            except Exception:
                for parent_dir, name, child_inode, prev_mtime in reversed(created):
                    parent_dir.children.pop(name, None)
                    self.inodes.pop(child_inode, None)
                    parent_dir.modified_at = prev_mtime
                raise

        parent, name = self._parent(path)
        node = Directory(**self._attributes(name, mode))
        return self._register(parent, name, node)  # type: ignore[return-value]

    def create_file(
        self, path: str, content: str = "", mode: int | str = 0o644
    ) -> File:
        parent, name = self._parent(path)
        node = File(**self._attributes(name, mode), content=content)
        return self._register(parent, name, node)  # type: ignore[return-value]

    def read_file(self, path: str) -> str:
        node = self.resolve(path)
        if not isinstance(node, File):
            raise FileSystemError(f"Not a file: {path}")
        self._require(node, PM.READ)
        return node.content

    def write_file(self, path: str, content: str, append: bool = False) -> File:
        node = self.resolve(path)
        if not isinstance(node, File):
            raise FileSystemError(f"Not a file: {path}")
        self._require(node, PM.WRITE)
        node.content = node.content + content if append else content
        node.touch()
        return node

    def list_dir(self, path: str = ".") -> list[dict]:
        node = self.resolve(path)
        if not isinstance(node, Directory):
            raise FileSystemError(f"Not a directory: {path}")
        self._require(node, PM.READ)
        children = []
        for inode in node.children.values():
            child = self.inodes.get(inode)
            if child is None:
                raise FileSystemError(f"Corrupt inode reference: {inode}")
            children.append(child)
        return [child.metadata() for child in sorted(children, key=lambda item: item.name)]

    def change_directory(self, path: str) -> str:
        node = self.resolve(path)
        if not isinstance(node, Directory):
            raise FileSystemError(f"Not a directory: {path}")
        self._require(node, PM.EXECUTE)
        self.cwd = self._absolute(path)
        self.current_dir = node.inode
        return self.cwd

    def _collect_remove_inodes(self, inode: str) -> list[str]:
        node = self.inodes.get(inode)
        if node is None:
            raise FileSystemError(f"Corrupt inode reference: {inode}")
        inodes = [inode]
        if isinstance(node, Directory) and node.children:
            self._require(node, PM.READ | PM.WRITE | PM.EXECUTE)
            for child_inode in node.children.values():
                inodes.extend(self._collect_remove_inodes(child_inode))
        return inodes

    def remove(self, path: str, recursive: bool = False) -> None:
        parent, name = self._parent(path)
        inode = parent.children.get(name)
        if inode is None:
            raise FileSystemError(f"No such file or directory: {path}")
        node = self.inodes.get(inode)
        if node is None:
            raise FileSystemError(f"Corrupt inode reference: {inode}")
        if node.inode == self.root_inode:
            raise FileSystemError("The root directory cannot be removed")
        if isinstance(node, Directory) and node.children and not recursive:
            raise FileSystemError("Directory is not empty (use recursive removal)")

        inodes_to_remove = self._collect_remove_inodes(inode)
        absolute = self._absolute(path)
        if self.cwd == absolute or self.cwd.startswith(absolute + "/"):
            self.cwd = "/"
            self.current_dir = self.root_inode

        del parent.children[name]
        for target_inode in inodes_to_remove:
            del self.inodes[target_inode]
        parent.touch()

    def rename(self, source: str, destination: str) -> None:
        src_parent, src_name = self._parent(source)
        inode = src_parent.children.get(src_name)
        if inode is None:
            raise FileSystemError(f"No such file or directory: {source}")
        node = self.inodes.get(inode)
        if node is None:
            raise FileSystemError(f"Corrupt inode reference: {inode}")
        src = self._absolute(source)
        requested_destination = self._absolute(destination)

        # Match the useful Unix mv behaviour: an existing directory is a target
        # container, while a non-existing path is the new name.
        try:
            existing_destination = self.resolve(requested_destination)
        except FileSystemError as exc:
            if not str(exc).startswith("No such file or directory:"):
                raise
            existing_destination = None
        if isinstance(existing_destination, Directory):
            requested_destination = posixpath.join(requested_destination, src_name)

        dst_parent, dst_name = self._parent(requested_destination)
        dst = self._absolute(requested_destination)
        if dst_parent is src_parent and dst_name == src_name:
            return
        if dst_name in dst_parent.children:
            raise FileSystemError(f"Already exists: {dst}")
        if isinstance(node, Directory) and (dst == src or dst.startswith(src + "/")):
            raise FileSystemError("Cannot move a directory into itself")

        del src_parent.children[src_name]
        node.name = dst_name
        node.touch()
        dst_parent.children[dst_name] = inode
        src_parent.touch()
        if dst_parent is not src_parent:
            dst_parent.touch()
        if self.cwd == src or self.cwd.startswith(src + "/"):
            self.cwd = dst + self.cwd[len(src):]

    def _collect_copy(
        self, source_inode: str, new_name: str, pending: dict[str, Node]
    ) -> Node:
        source = self.inodes.get(source_inode)
        if source is None:
            raise FileSystemError(f"Corrupt inode reference: {source_inode}")
        if isinstance(source, File):
            self._require(source, PM.READ)
        else:
            self._require(source, PM.READ | PM.EXECUTE)

        attributes = {
            **source.base_dict(),
            "name": new_name,
            "owner_uid": self.current_user.uid,
            "group_gid": self.current_user.primary_gid,
            "inode": uuid.uuid4().hex[:12],
        }
        if isinstance(source, File):
            clone: Node = File(**attributes, content=source.content)
        else:
            clone = Directory(**attributes)
            for child_name, child_inode in source.children.items():
                child = self._collect_copy(child_inode, child_name, pending)
                clone.children[child_name] = child.inode
        clone.touch()
        pending[clone.inode] = clone
        return clone

    def copy(self, source: str, destination: str) -> Node:
        original = self.resolve(source)
        destination_path = self._absolute(destination)
        try:
            existing_destination = self.resolve(destination_path)
        except FileSystemError as exc:
            if not str(exc).startswith("No such file or directory:"):
                raise
            existing_destination = None
        source_name = posixpath.basename(self._absolute(source))
        if isinstance(existing_destination, Directory):
            destination_path = posixpath.join(destination_path, source_name)

        parent, name = self._parent(destination_path)
        if name in parent.children:
            raise FileSystemError(f"Already exists: {destination_path}")
        if isinstance(original, Directory):
            source_path = self._absolute(source)
            if destination_path.startswith(source_path.rstrip("/") + "/"):
                raise FileSystemError("Cannot copy a directory into itself")

        pending: dict[str, Node] = {}
        duplicate = self._collect_copy(original.inode, name, pending)
        self.inodes.update(pending)
        parent.children[name] = duplicate.inode
        parent.touch()
        return duplicate

    def move(self, source: str, destination: str) -> None:
        self.rename(source, destination)

    def chmod(self, path: str, mode: int | str) -> None:
        node = self.resolve(path)
        if not self.current_user.is_root and self.current_user.uid != node.owner_uid:
            raise PermissionDenied("Only the owner or root can change permissions")
        node.mode = PM.parse_mode(mode)
        node.touch()

    def chown(
        self, path: str, username: str, groupname: str | None = None
    ) -> None:
        node = self.resolve(path)
        if not self.current_user.is_root:
            raise PermissionDenied("Only root can change ownership")
        if username not in self.users:
            raise FileSystemError(f"Unknown user: {username}")
        if groupname is not None and groupname not in self.groups:
            raise FileSystemError(f"Unknown group: {groupname}")
        node.owner_uid = self.users[username].uid
        if groupname is not None:
            node.group_gid = self.groups[groupname].gid
        node.touch()

    @staticmethod
    def _is_valid_identifier(name: str) -> bool:
        return bool(name) and ":" not in name and not any(ch.isspace() for ch in name)

    def add_user(self, username: str, groupname: str | None = None) -> User:
        if not self.current_user.is_root:
            raise PermissionDenied("Only root can add users")
        if not self._is_valid_identifier(username) or username in self.users:
            raise FileSystemError(f"Invalid or existing username: {username}")
        groupname = groupname or username
        if not self._is_valid_identifier(groupname):
            raise FileSystemError(f"Invalid group name: {groupname}")
        if groupname not in self.groups:
            gid = max(group.gid for group in self.groups.values()) + 1
            self.groups[groupname] = Group(groupname, gid)
        uid = max(user.uid for user in self.users.values()) + 1
        group = self.groups[groupname]
        user = User(username, uid, group.gid)
        group.members.append(uid)
        self.users[username] = user
        return user

    def add_group(self, name: str) -> Group:
        if not self.current_user.is_root:
            raise PermissionDenied("Only root can add groups")
        if not self._is_valid_identifier(name) or name in self.groups:
            raise FileSystemError(f"Invalid or existing group: {name}")
        group = Group(name, max(item.gid for item in self.groups.values()) + 1)
        self.groups[name] = group
        return group

    def add_user_to_group(self, username: str, groupname: str) -> None:
        if not self.current_user.is_root:
            raise PermissionDenied("Only root can change group membership")
        user = self.users.get(username)
        group = self.groups.get(groupname)
        if user is None:
            raise FileSystemError(f"Unknown user: {username}")
        if group is None:
            raise FileSystemError(f"Unknown group: {groupname}")
        if user.uid not in group.members:
            group.members.append(user.uid)

    def switch_user(self, username: str) -> User:
        user = self.users.get(username)
        if user is None:
            raise FileSystemError(f"Unknown user: {username}")
        self.current_user = user
        self.cwd = "/"
        self.current_dir = self.root_inode
        return user

    def search(
        self, query: str, path: str = "/", content: bool = False
    ) -> list[str]:
        if not query:
            raise FileSystemError("Search query cannot be empty")
        start = self.resolve(path)
        base = self._absolute(path)
        results: list[str] = []

        if not content and query.casefold() in start.name.casefold() and base != "/":
            results.append(base)
        if isinstance(start, File):
            if content:
                self._require(start, PM.READ)
                if query.casefold() in start.content.casefold():
                    results.append(base)
            return sorted(set(results))

        def walk(directory: Directory, current_path: str) -> None:
            self._require(directory, PM.READ | PM.EXECUTE)
            for name, inode in directory.children.items():
                child = self.inodes.get(inode)
                if child is None:
                    raise FileSystemError(f"Corrupt inode reference: {inode}")
                child_path = posixpath.join(current_path, name)
                if not content and query.casefold() in name.casefold():
                    results.append(child_path)
                if isinstance(child, File) and content:
                    self._require(child, PM.READ)
                    if query.casefold() in child.content.casefold():
                        results.append(child_path)
                elif isinstance(child, Directory):
                    walk(child, child_path)

        walk(start, base)
        return sorted(set(results))

    def tree(self, path: str = "/") -> str:
        start = self.resolve(path)
        lines = [self._absolute(path)]

        def walk(directory: Directory, prefix: str) -> None:
            self._require(directory, PM.READ | PM.EXECUTE)
            children: list[tuple[str, Node]] = []
            for name, inode in directory.children.items():
                child = self.inodes.get(inode)
                if child is None:
                    raise FileSystemError(f"Corrupt inode reference: {inode}")
                children.append((name, child))
            children.sort(key=lambda item: item[0])
            for index, (name, child) in enumerate(children):
                last = index == len(children) - 1
                lines.append(prefix + ("└── " if last else "├── ") + name)
                if isinstance(child, Directory):
                    walk(child, prefix + ("    " if last else "│   "))

        if isinstance(start, Directory):
            walk(start, "")
        return "\n".join(lines)

    def stat(self, path: str) -> dict:
        return self.resolve(path).metadata()

    def _state(self) -> dict:
        return {
            "version": self.VERSION,
            "root_inode": self.root_inode,
            "current_dir": self.current_dir,
            "cwd": self.cwd,
            "current_user": self.current_user.username,
            "inodes": {inode: node.to_dict() for inode, node in self.inodes.items()},
            "users": [user.to_dict() for user in self.users.values()],
            "groups": [group.to_dict() for group in self.groups.values()],
        }

    @staticmethod
    def _is_int(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)

    def save(self, path: str | Path | None = None) -> None:
        target = Path(path) if path else self.storage_path
        if target is None:
            raise FileSystemError("No storage path configured")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        try:
            temporary.write_text(json.dumps(self._state(), indent=2), encoding="utf-8")
            temporary.replace(target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def _validate_state(self) -> None:
        """Validate inode references and ownership before accepting loaded state."""
        root = self.inodes.get(self.root_inode)
        if not isinstance(root, Directory) or root.name != "/":
            raise FileSystemError("Invalid root inode")

        for user in self.users.values():
            if (
                not isinstance(user.username, str)
                or not self._is_int(user.uid)
                or not self._is_int(user.primary_gid)
                or not isinstance(user.is_root, bool)
            ):
                raise FileSystemError("Invalid user record in saved state")
        for group in self.groups.values():
            if (
                not isinstance(group.name, str)
                or not self._is_int(group.gid)
                or not isinstance(group.members, list)
                or any(not self._is_int(uid) for uid in group.members)
            ):
                raise FileSystemError("Invalid group record in saved state")

        uid_map = {user.uid: user for user in self.users.values()}
        gid_map = {group.gid: group for group in self.groups.values()}
        if len(uid_map) != len(self.users) or len(gid_map) != len(self.groups):
            raise FileSystemError("Duplicate UID or GID in saved state")
        if "root" not in self.users or self.users["root"].uid != 0:
            raise FileSystemError("Saved state must contain UID 0 as root")
        if any(user.is_root != (name == "root") for name, user in self.users.items()):
            raise FileSystemError("Only the root account may have root privileges")
        if any(name != user.username for name, user in self.users.items()):
            raise FileSystemError("User table key does not match username")
        if any(name != group.name for name, group in self.groups.items()):
            raise FileSystemError("Group table key does not match group name")
        if "root" not in self.groups or self.groups["root"].gid != 0:
            raise FileSystemError("Saved state must contain GID 0 as root")

        for user in self.users.values():
            if user.primary_gid not in gid_map:
                raise FileSystemError(f"Unknown primary GID for user {user.username}")
        for group in self.groups.values():
            if any(uid not in uid_map for uid in group.members):
                raise FileSystemError(f"Unknown member in group {group.name}")
        for inode, node in self.inodes.items():
            if (
                not isinstance(inode, str)
                or not isinstance(node.inode, str)
                or not isinstance(node.name, str)
                or not self._is_int(node.owner_uid)
                or not self._is_int(node.group_gid)
                or not self._is_int(node.mode)
            ):
                raise FileSystemError(f"Invalid inode metadata on inode {inode}")
            if isinstance(node, File) and not isinstance(node.content, str):
                raise FileSystemError(f"Invalid file content on inode {inode}")
            if isinstance(node, Directory) and any(
                not isinstance(k, str) or not isinstance(v, str)
                for k, v in node.children.items()
            ):
                raise FileSystemError(f"Invalid directory children on inode {inode}")
            if inode != node.inode:
                raise FileSystemError(f"Inode table key mismatch: {inode}")
            if node.owner_uid not in uid_map or node.group_gid not in gid_map:
                raise FileSystemError(f"Unknown owner or group on inode {inode}")
            if not 0 <= node.mode <= 0o777:
                raise FileSystemError(f"Invalid permission mode on inode {inode}")

        visited: set[str] = set()
        active: set[str] = set()
        parent_counts: dict[str, int] = {inode: 0 for inode in self.inodes}

        def visit(inode: str) -> None:
            if inode in active:
                raise FileSystemError("Directory cycle detected in saved state")
            if inode in visited:
                return
            node = self.inodes.get(inode)
            if node is None:
                raise FileSystemError(f"Missing inode reference: {inode}")
            active.add(inode)
            if isinstance(node, Directory):
                for name, child_inode in node.children.items():
                    if name in ("", ".", "..") or "/" in name:
                        raise FileSystemError(f"Invalid directory entry name: {name!r}")
                    child = self.inodes.get(child_inode)
                    if child is None:
                        raise FileSystemError(f"Missing inode reference: {child_inode}")
                    if child.name != name:
                        raise FileSystemError(f"Directory entry name mismatch: {name}")
                    parent_counts[child_inode] += 1
                    visit(child_inode)
            active.remove(inode)
            visited.add(inode)

        visit(self.root_inode)
        if visited != set(self.inodes):
            raise FileSystemError("Saved state contains unreachable inodes")
        if parent_counts[self.root_inode] != 0:
            raise FileSystemError("Root inode cannot have a parent")
        if any(count != 1 for inode, count in parent_counts.items() if inode != self.root_inode):
            raise FileSystemError("Each non-root inode must have exactly one parent")

        current = self.inodes.get(self.current_dir)
        if not isinstance(current, Directory):
            raise FileSystemError("Current directory inode is invalid")
        if not isinstance(self.cwd, str) or not self.cwd.startswith("/"):
            raise FileSystemError("Saved working directory must be an absolute path")
        if self._absolute(self.cwd) != self.cwd:
            raise FileSystemError("Saved working directory must be normalized")
        # A process may retain its working directory after permissions change.
        # Resolve as root here to validate identity, not current-user access.
        if self.resolve(self.cwd, user=self.users["root"]).inode != self.current_dir:
            raise FileSystemError("Saved path and current directory inode do not match")

    @classmethod
    def load(cls, path: str | Path) -> "FileSystem":
        target = Path(path)
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise FileSystemError(f"Invalid JSON save file: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("version") != cls.VERSION:
            raise FileSystemError("Unsupported filesystem save version")

        try:
            if not isinstance(payload["inodes"], dict):
                raise FileSystemError("Invalid inodes table in saved state")
            if not isinstance(payload["users"], list) or not isinstance(payload["groups"], list):
                raise FileSystemError("Invalid users or groups table in saved state")
            fs = cls(target)
            fs.inodes = {
                inode: node_from_dict(data)
                for inode, data in payload["inodes"].items()
            }
            fs.root_inode = payload["root_inode"]
            fs.users = {
                user["username"]: User.from_dict(user)
                for user in payload["users"]
            }
            fs.groups = {
                group["name"]: Group.from_dict(group)
                for group in payload["groups"]
            }
            if len(fs.users) != len(payload["users"]) or len(fs.groups) != len(payload["groups"]):
                raise FileSystemError("Duplicate username or group name in saved state")
            fs.cwd = payload.get("cwd", "/")
            fs.current_dir = payload.get("current_dir", fs.root_inode)
            fs.current_user = fs.users[payload.get("current_user", "root")]
            fs._validate_state()
            return fs
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            if isinstance(exc, FileSystemError):
                raise
            raise FileSystemError(f"Invalid filesystem save data: {exc}") from exc
