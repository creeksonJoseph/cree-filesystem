"""Unix-style owner/group/other permission checks."""
from .models import Node, User


class PermissionDenied(PermissionError):
    """Raised when a user lacks the required filesystem permission."""


class PermissionManager:
    READ, WRITE, EXECUTE = 4, 2, 1

    @staticmethod
    def allowed(node: Node, user: User, groups: set[int], requested: int) -> bool:
        if user.is_root:
            return True
        if user.uid == node.owner_uid:
            granted = (node.mode >> 6) & 7
        elif node.group_gid in groups:
            granted = (node.mode >> 3) & 7
        else:
            granted = node.mode & 7
        return (granted & requested) == requested

    @classmethod
    def require(cls, node: Node, user: User, groups: set[int], requested: int) -> None:
        if not cls.allowed(node, user, groups, requested):
            names = [(cls.READ, "read"), (cls.WRITE, "write"), (cls.EXECUTE, "execute")]
            needed = "+".join(name for bit, name in names if requested & bit)
            raise PermissionDenied(f"Permission denied: {needed} access to '{node.name}'")

    @staticmethod
    def parse_mode(mode: int | str) -> int:
        try:
            value = int(mode, 8) if isinstance(mode, str) else int(mode)
        except (TypeError, ValueError) as exc:
            raise ValueError("Mode must be octal, for example 755 or 644") from exc
        if not 0 <= value <= 0o777:
            raise ValueError("Mode must be between 000 and 777")
        return value
