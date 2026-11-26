"""In-memory inode-table filesystem, Unix-style operations and JSON persistence."""
from __future__ import annotations

import json
import posixpath
import uuid
from pathlib import Path

from .models import Directory, File, Group, Node, User, node_from_dict
from .permissions import PermissionDenied, PermissionManager as PM


class FileSystemError(Exception):
    """Base filesystem operation error."""


class FileSystem:
    VERSION = 2

    def __init__(self, storage_path: str | Path | None = None) -> None:
        self.storage_path = Path(storage_path) if storage_path else None
        self.users = {"root": User("root", 0, 0, True)}
        self.groups = {"root": Group("root", 0, [0])}

        root = Directory("/", 0, 0, 0o755)
        self.root_inode = root.inode
        self.inodes: dict[str, Node] = {root.inode: root}
        self.current_dir = root.inode
        self.cwd = "/"
        self.current_user = self.users["root"]

    @property
    def root(self) -> Directory:
        return self.inodes[self.root_inode]  # type: ignore[return-value]

    def group_ids(self, user: User) -> set[int]:
        return ({group.gid for group in self.groups.values()
                 if user.uid in group.members} | {user.primary_gid})

    def _absolute(self, path: str) -> str:
        if not path:
            raise FileSystemError("Path cannot be empty")
        combined = path if path.startswith("/") else posixpath.join(self.cwd, path)
        return posixpath.normpath(combined)

    def _parts(self, path: str) -> list[str]:
        return [part for part in self._absolute(path).split("/") if part]

    def _require(self, node: Node, permission: int) -> None:
        PM.require(node, self.current_user,
                   self.group_ids(self.current_user), permission)

    def resolve(self, path: str, user: User | None = None) -> Node:
        actor = user or self.current_user
        inode = self.root_inode
        for part in self._parts(path):
            directory = self.inodes[inode]
            if not isinstance(directory, Directory):
                raise FileSystemError(f"'{directory.name}' is not a directory")
            PM.require(directory, actor, self.group_ids(actor), PM.EXECUTE)
            child_inode = directory.children.get(part)
            if child_inode is None:
                raise FileSystemError(f"No such file or directory: {path}")
            if child_inode not in self.inodes:
                raise FileSystemError(f"Corrupt inode reference: {child_inode}")
            inode = child_inode
        return self.inodes[inode]

    def _parent(self, path: str) -> tuple[Directory, str]:
        absolute = self._absolute(path)
        name = posixpath.basename(absolute)
        if absolute == "/" or not name:
            raise FileSystemError("A valid file or directory name is required")
        parent_path = posixpath.dirname(absolute) or "/"
        parent = self.resolve(parent_path)
        if not isinstance(parent, Directory):
            raise FileSystemError(f"Not a directory: {parent_path}")
        self._require(parent, PM.WRITE | PM.EXECUTE)
        return parent, name

    def _attributes(self, name: str, mode: int | str) -> dict:
        return {"name": name, "owner_uid": self.current_user.uid,
                "group_gid": self.current_user.primary_gid,
                "mode": PM.parse_mode(mode)}

    def _register(self, parent: Directory, name: str, node: Node) -> Node:
        if name in parent.children:
            raise FileSystemError(f"Already exists: {name}")
        self.inodes[node.inode] = node
        parent.children[name] = node.inode
        parent.touch()
        return node

    def mkdir(self, path: str, mode: int | str = 0o755,
              parents: bool = False) -> Directory:
        if parents:
            current = "/"
            result = self.root
            for part in self._parts(path):
                current = posixpath.join(current, part)
                try:
                    node = self.resolve(current)
                    if not isinstance(node, Directory):
                        raise FileSystemError(f"Not a directory: {current}")
                    result = node
                except FileSystemError as exc:
                    if not str(exc).startswith("No such file"):
                        raise
                    result = self.mkdir(current, mode)
            return result
        parent, name = self._parent(path)
        node = Directory(**self._attributes(name, mode))
        return self._register(parent, name, node)  # type: ignore[return-value]

    def create_file(self, path: str, content: str = "",
                    mode: int | str = 0o644) -> File:
        parent, name = self._parent(path)
        node = File(**self._attributes(name, mode), content=content)
        return self._register(parent, name, node)  # type: ignore[return-value]

    def read_file(self, path: str) -> str:
        node = self.resolve(path)
        if not isinstance(node, File):
            raise FileSystemError(f"Not a file: {path}")
        self._require(node, PM.READ)
        return node.content

    def write_file(self, path: str, content: str,
                   append: bool = False) -> File:
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
        children = (self.inodes[inode] for inode in node.children.values())
        return [child.metadata() for child in
                sorted(children, key=lambda item: item.name)]

    def change_directory(self, path: str) -> str:
        node = self.resolve(path)
        if not isinstance(node, Directory):
            raise FileSystemError(f"Not a directory: {path}")
        PM.require(node, self.current_user,
                   self.group_ids(self.current_user), PM.EXECUTE)
        self.cwd = self._absolute(path)
        self.current_dir = node.inode
        return self.cwd

    def _remove_inode_tree(self, inode: str) -> None:
        node = self.inodes[inode]
        if isinstance(node, Directory):
            for child_inode in list(node.children.values()):
                self._remove_inode_tree(child_inode)
        del self.inodes[inode]

    def remove(self, path: str, recursive: bool = False) -> None:
        parent, name = self._parent(path)
        inode = parent.children.get(name)
        if inode is None:
            raise FileSystemError(f"No such file or directory: {path}")
        node = self.inodes[inode]
        if isinstance(node, Directory) and node.children and not recursive:
            raise FileSystemError("Directory is not empty (use recursive removal)")
        absolute = self._absolute(path)
        if self.cwd == absolute or self.cwd.startswith(absolute + "/"):
            self.cwd = "/"
            self.current_dir = self.root_inode
        del parent.children[name]
        self._remove_inode_tree(inode)
        parent.touch()

    def rename(self, source: str, destination: str) -> None:
        src_parent, src_name = self._parent(source)
        inode = src_parent.children.get(src_name)
        if inode is None:
            raise FileSystemError(f"No such file or directory: {source}")
        dst_parent, dst_name = self._parent(destination)
        if dst_name in dst_parent.children:
            raise FileSystemError(f"Already exists: {destination}")
        node = self.inodes[inode]
        src, dst = self._absolute(source), self._absolute(destination)
        if isinstance(node, Directory) and (dst == src or dst.startswith(src + "/")):
            raise FileSystemError("Cannot move a directory into itself")
        del src_parent.children[src_name]
        node.name = dst_name
        node.touch()
        dst_parent.children[dst_name] = inode
        src_parent.touch()
        dst_parent.touch()
        if self.cwd == src or self.cwd.startswith(src + "/"):
            self.cwd = dst + self.cwd[len(src):]

    def _clone_inode_tree(self, source_inode: str, new_name: str) -> Node:
        source = self.inodes[source_inode]
        attributes = {**source.base_dict(), "name": new_name,
                      "owner_uid": self.current_user.uid,
                      "group_gid": self.current_user.primary_gid,
                      "inode": uuid.uuid4().hex[:12]}
        if isinstance(source, File):
            clone: Node = File(**attributes, content=source.content)
        else:
            clone = Directory(**attributes)
            self.inodes[clone.inode] = clone
            for child_name, child_inode in source.children.items():
                child = self._clone_inode_tree(child_inode, child_name)
                clone.children[child_name] = child.inode
        clone.touch()
        self.inodes[clone.inode] = clone
        return clone

    def copy(self, source: str, destination: str) -> Node:
        original = self.resolve(source)
        parent, name = self._parent(destination)
        if name in parent.children:
            raise FileSystemError(f"Already exists: {destination}")
        duplicate = self._clone_inode_tree(original.inode, name)
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

    def chown(self, path: str, username: str,
              groupname: str | None = None) -> None:
        node = self.resolve(path)
        if not self.current_user.is_root:
            raise PermissionDenied("Only root can change ownership")
        if username not in self.users:
            raise FileSystemError(f"Unknown user: {username}")
        if groupname and groupname not in self.groups:
            raise FileSystemError(f"Unknown group: {groupname}")
        node.owner_uid = self.users[username].uid
        if groupname:
            node.group_gid = self.groups[groupname].gid
        node.touch()

    def add_user(self, username: str,
                 groupname: str | None = None) -> User:
        if not self.current_user.is_root:
            raise PermissionDenied("Only root can add users")
        if username in self.users:
            raise FileSystemError(f"User already exists: {username}")
        groupname = groupname or username
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
        if name in self.groups:
            raise FileSystemError(f"Group already exists: {name}")
        group = Group(name, max(item.gid for item in self.groups.values()) + 1)
        self.groups[name] = group
        return group

    def switch_user(self, username: str) -> User:
        if username not in self.users:
            raise FileSystemError(f"Unknown user: {username}")
        self.current_user = self.users[username]
        self.cwd = "/"
        self.current_dir = self.root_inode
        return self.current_user

    def search(self, query: str, path: str = "/",
               content: bool = False) -> list[str]:
        start = self.resolve(path)
        base = self._absolute(path)
        results: list[str] = []

        def walk(node: Node, current_path: str) -> None:
            if not isinstance(node, Directory):
                return
            self._require(node, PM.EXECUTE)
            for name, inode in node.children.items():
                child = self.inodes[inode]
                child_path = posixpath.join(current_path, name)
                if query.casefold() in name.casefold():
                    results.append(child_path)
                if isinstance(child, File) and content:
                    self._require(child, PM.READ)
                    if query.casefold() in child.content.casefold():
                        results.append(child_path)
                if isinstance(child, Directory):
                    walk(child, child_path)

        walk(start, base)
        return sorted(set(results))

    def tree(self, path: str = "/") -> str:
        start = self.resolve(path)
        lines = [self._absolute(path)]

        def walk(directory: Directory, prefix: str) -> None:
            children = [(name, self.inodes[inode])
                        for name, inode in directory.children.items()]
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

    def save(self, path: str | Path | None = None) -> None:
        target = Path(path) if path else self.storage_path
        if target is None:
            raise FileSystemError("No storage path configured")
        payload = {
            "version": self.VERSION,
            "root_inode": self.root_inode,
            "current_dir": self.current_dir,
            "cwd": self.cwd,
            "current_user": self.current_user.username,
            "inodes": {inode: node.to_dict() for inode, node in self.inodes.items()},
            "users": [user.to_dict() for user in self.users.values()],
            "groups": [group.to_dict() for group in self.groups.values()],
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(target)

    @classmethod
    def load(cls, path: str | Path) -> "FileSystem":
        target = Path(path)
        payload = json.loads(target.read_text(encoding="utf-8"))
        if payload.get("version") != cls.VERSION:
            raise FileSystemError("Unsupported filesystem save version")
        fs = cls(target)
        fs.inodes = {inode: node_from_dict(data)
                     for inode, data in payload["inodes"].items()}
        fs.root_inode = payload["root_inode"]
        fs.users = {user["username"]: User.from_dict(user)
                    for user in payload["users"]}
        fs.groups = {group["name"]: Group.from_dict(group)
                     for group in payload["groups"]}
        fs.cwd = payload.get("cwd", "/")
        fs.current_user = fs.users.get(payload.get("current_user", "root"),
                                        fs.users["root"])
        fs.current_dir = payload.get("current_dir", fs.root_inode)
        # Validate persisted references and recover safely from an invalid cwd.
        try:
            resolved = fs.resolve(fs.cwd)
            if not isinstance(resolved, Directory):
                raise FileSystemError("Saved working directory is not a directory")
            fs.current_dir = resolved.inode
        except (FileSystemError, KeyError):
            fs.cwd = "/"
            fs.current_dir = fs.root_inode
        return fs
