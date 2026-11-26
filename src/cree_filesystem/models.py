"""Core filesystem entities and JSON serialization."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class User:
    username: str
    uid: int
    primary_gid: int
    is_root: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"username": self.username, "uid": self.uid,
                "primary_gid": self.primary_gid, "is_root": self.is_root}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "User":
        return cls(**data)


@dataclass
class Group:
    name: str
    gid: int
    members: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "gid": self.gid, "members": self.members}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Group":
        return cls(**data)


@dataclass
class Node:
    name: str
    owner_uid: int
    group_gid: int
    mode: int
    inode: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = field(default_factory=now)
    modified_at: str = field(default_factory=now)

    @property
    def is_directory(self) -> bool:
        return isinstance(self, Directory)

    def touch(self) -> None:
        self.modified_at = now()

    def metadata(self) -> dict[str, Any]:
        return {"name": self.name, "type": "directory" if self.is_directory else "file",
                "inode": self.inode, "owner_uid": self.owner_uid,
                "group_gid": self.group_gid, "mode": format(self.mode, "04o"),
                "created_at": self.created_at, "modified_at": self.modified_at}

    def base_dict(self) -> dict[str, Any]:
        return {"name": self.name, "owner_uid": self.owner_uid, "group_gid": self.group_gid,
                "mode": self.mode, "inode": self.inode,
                "created_at": self.created_at, "modified_at": self.modified_at}


@dataclass
class File(Node):
    content: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {**self.base_dict(), "kind": "file", "content": self.content}


@dataclass
class Directory(Node):
    children: dict[str, Node] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {**self.base_dict(), "kind": "directory",
                "children": {name: child.to_dict() for name, child in self.children.items()}}


def node_from_dict(data: dict[str, Any]) -> Node:
    keys = ("name", "owner_uid", "group_gid", "mode", "inode", "created_at", "modified_at")
    common = {key: data[key] for key in keys}
    if data["kind"] == "file":
        return File(**common, content=data.get("content", ""))
    if data["kind"] == "directory":
        children = {name: node_from_dict(child)
                    for name, child in data.get("children", {}).items()}
        return Directory(**common, children=children)
    raise ValueError(f"Unknown node kind: {data.get('kind')}")
