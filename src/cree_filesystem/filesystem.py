"""Filesystem operations, path resolution and JSON persistence."""
from __future__ import annotations
import copy
import json
import posixpath
from pathlib import Path
from .models import Directory, File, Group, Node, User, node_from_dict
from .permissions import PermissionDenied, PermissionManager as PM


class FileSystemError(Exception):
    """Base filesystem operation error."""


class FileSystem:
    def __init__(self, storage_path: str | Path | None = None) -> None:
        self.storage_path = Path(storage_path) if storage_path else None
        self.users = {"root": User("root", 0, 0, True)}
        self.groups = {"root": Group("root", 0, [0])}
        self.root = Directory("/", 0, 0, 0o755)
        self.cwd = "/"
        self.current_user = self.users["root"]

    def group_ids(self, user: User) -> set[int]:
        return {g.gid for g in self.groups.values() if user.uid in g.members} | {user.primary_gid}

    def _absolute(self, path: str) -> str:
        if not path:
            raise FileSystemError("Path cannot be empty")
        return posixpath.normpath(path if path.startswith("/") else posixpath.join(self.cwd, path))

    def _parts(self, path: str) -> list[str]:
        return [part for part in self._absolute(path).split("/") if part not in ("", ".")]

    def resolve(self, path: str, user: User | None = None) -> Node:
        actor = user or self.current_user
        current: Node = self.root
        for part in self._parts(path):
            if not isinstance(current, Directory):
                raise FileSystemError(f"'{current.name}' is not a directory")
            PM.require(current, actor, self.group_ids(actor), PM.EXECUTE)
            if part == "..":
                continue
            if part not in current.children:
                raise FileSystemError(f"No such file or directory: {path}")
            current = current.children[part]
        return current

    def _parent(self, path: str) -> tuple[Directory, str]:
        absolute = self._absolute(path)
        name = posixpath.basename(absolute)
        if absolute == "/" or name in ("", ".", ".."):
            raise FileSystemError("A valid file or directory name is required")
        parent_path = posixpath.dirname(absolute) or "/"
        parent = self.resolve(parent_path)
        if not isinstance(parent, Directory):
            raise FileSystemError(f"Not a directory: {parent_path}")
        PM.require(parent, self.current_user, self.group_ids(self.current_user), PM.WRITE | PM.EXECUTE)
        return parent, name

    def _attributes(self, name: str, mode: int | str) -> dict:
        return {"name": name, "owner_uid": self.current_user.uid,
                "group_gid": self.current_user.primary_gid, "mode": PM.parse_mode(mode)}

    def mkdir(self, path: str, mode: int | str = 0o755, parents: bool = False) -> Directory:
        if parents:
            current = ""
            result = self.root
            for part in self._parts(path):
                current += "/" + part
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
        if name in parent.children:
            raise FileSystemError(f"Already exists: {path}")
        node = Directory(**self._attributes(name, mode))
        parent.children[name] = node
        parent.touch()
        return node

    def create_file(self, path: str, content: str = "", mode: int | str = 0o644) -> File:
        parent, name = self._parent(path)
        if name in parent.children:
            raise FileSystemError(f"Already exists: {path}")
        node = File(**self._attributes(name, mode), content=content)
        parent.children[name] = node
        parent.touch()
        return node

    def read_file(self, path: str) -> str:
        node = self.resolve(path)
        if not isinstance(node, File):
            raise FileSystemError(f"Not a file: {path}")
        PM.require(node, self.current_user, self.group_ids(self.current_user), PM.READ)
        return node.content

    def write_file(self, path: str, content: str, append: bool = False) -> File:
        node = self.resolve(path)
        if not isinstance(node, File):
            raise FileSystemError(f"Not a file: {path}")
        PM.require(node, self.current_user, self.group_ids(self.current_user), PM.WRITE)
        node.content = node.content + content if append else content
        node.touch()
        return node

    def list_dir(self, path: str = ".") -> list[dict]:
        node = self.resolve(path)
        if not isinstance(node, Directory):
            raise FileSystemError(f"Not a directory: {path}")
        PM.require(node, self.current_user, self.group_ids(self.current_user), PM.READ)
        return [n.metadata() for n in sorted(node.children.values(), key=lambda item: item.name)]

    def change_directory(self, path: str) -> str:
        node = self.resolve(path)
        if not isinstance(node, Directory):
            raise FileSystemError(f"Not a directory: {path}")
        PM.require(node, self.current_user, self.group_ids(self.current_user), PM.EXECUTE)
        self.cwd = self._absolute(path)
        return self.cwd

    def remove(self, path: str, recursive: bool = False) -> None:
        parent, name = self._parent(path)
        if name not in parent.children:
            raise FileSystemError(f"No such file or directory: {path}")
        node = parent.children[name]
        if isinstance(node, Directory) and node.children and not recursive:
            raise FileSystemError("Directory is not empty (use recursive removal)")
        del parent.children[name]
        parent.touch()
        absolute = self._absolute(path)
        if self.cwd == absolute or self.cwd.startswith(absolute + "/"):
            self.cwd = "/"

    def rename(self, source: str, destination: str) -> None:
        src_parent, src_name = self._parent(source)
        if src_name not in src_parent.children:
            raise FileSystemError(f"No such file or directory: {source}")
        dst_parent, dst_name = self._parent(destination)
        if dst_name in dst_parent.children:
            raise FileSystemError(f"Already exists: {destination}")
        node = src_parent.children[src_name]
        src, dst = self._absolute(source), self._absolute(destination)
        if isinstance(node, Directory) and dst.startswith(src + "/"):
            raise FileSystemError("Cannot move a directory into itself")
        del src_parent.children[src_name]
        node.name = dst_name
        node.touch()
        dst_parent.children[dst_name] = node
        src_parent.touch()
        dst_parent.touch()

    def copy(self, source: str, destination: str) -> Node:
        original = self.resolve(source)
        parent, name = self._parent(destination)
        if name in parent.children:
            raise FileSystemError(f"Already exists: {destination}")
        duplicate = copy.deepcopy(original)
        duplicate.name = name
        self._reset_ownership(duplicate)
        parent.children[name] = duplicate
        parent.touch()
        return duplicate

    def _reset_ownership(self, node: Node) -> None:
        node.owner_uid, node.group_gid = self.current_user.uid, self.current_user.primary_gid
        if isinstance(node, Directory):
            for child in node.children.values():
                self._reset_ownership(child)

    def move(self, source: str, destination: str) -> None:
        self.rename(source, destination)

    def chmod(self, path: str, mode: int | str) -> None:
        node = self.resolve(path)
        if not self.current_user.is_root and self.current_user.uid != node.owner_uid:
            raise PermissionDenied("Only the owner or root can change permissions")
        node.mode = PM.parse_mode(mode)
        node.touch()

    def chown(self, path: str, username: str, groupname: str | None = None) -> None:
        node = self.resolve(path)
        if not self.current_user.is_root:
            raise PermissionDenied("Only root can change ownership")
        if username not in self.users:
            raise FileSystemError(f"Unknown user: {username}")
        node.owner_uid = self.users[username].uid
        if groupname:
            if groupname not in self.groups:
                raise FileSystemError(f"Unknown group: {groupname}")
            node.group_gid = self.groups[groupname].gid
        node.touch()

    def add_user(self, username: str, groupname: str | None = None) -> User:
        if not self.current_user.is_root:
            raise PermissionDenied("Only root can add users")
        if username in self.users:
            raise FileSystemError(f"User already exists: {username}")
        groupname = groupname or username
        if groupname not in self.groups:
            gid = max(g.gid for g in self.groups.values()) + 1
            self.groups[groupname] = Group(groupname, gid)
        uid = max(u.uid for u in self.users.values()) + 1
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
        group = Group(name, max(g.gid for g in self.groups.values()) + 1)
        self.groups[name] = group
        return group

    def switch_user(self, username: str) -> User:
        if username not in self.users:
            raise FileSystemError(f"Unknown user: {username}")
        self.current_user = self.users[username]
        self.cwd = "/"
        return self.current_user

    def search(self, query: str, path: str = "/", content: bool = False) -> list[str]:
        start = self.resolve(path)
        base = self._absolute(path)
        results: list[str] = []

        def walk(node: Node, current_path: str) -> None:
            if not isinstance(node, Directory):
                return
            PM.require(node, self.current_user, self.group_ids(self.current_user), PM.EXECUTE)
            for child in node.children.values():
                child_path = posixpath.join(current_path, child.name)
                if query.casefold() in child.name.casefold():
                    results.append(child_path)
                if isinstance(child, File) and content:
                    PM.require(child, self.current_user, self.group_ids(self.current_user), PM.READ)
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
            children = sorted(directory.children.values(), key=lambda item: item.name)
            for index, child in enumerate(children):
                last = index == len(children) - 1
                lines.append(prefix + ("└── " if last else "├── ") + child.name)
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
        payload = {"version": 1, "root": self.root.to_dict(), "cwd": self.cwd,
                   "users": [u.to_dict() for u in self.users.values()],
                   "groups": [g.to_dict() for g in self.groups.values()]}
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(target)

    @classmethod
    def load(cls, path: str | Path) -> "FileSystem":
        target = Path(path)
        payload = json.loads(target.read_text(encoding="utf-8"))
        if payload.get("version") != 1:
            raise FileSystemError("Unsupported filesystem save version")
        fs = cls(target)
        fs.root = node_from_dict(payload["root"])
        fs.users = {u["username"]: User.from_dict(u) for u in payload["users"]}
        fs.groups = {g["name"]: Group.from_dict(g) for g in payload["groups"]}
        fs.cwd = payload.get("cwd", "/")
        fs.current_user = fs.users.get("root", next(iter(fs.users.values())))
        return fs
