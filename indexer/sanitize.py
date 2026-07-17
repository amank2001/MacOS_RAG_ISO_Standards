"""Path sanitization utilities for API responses.

Ensures no absolute file system paths are exposed in API responses.
Paths are made relative to the library root, or reduced to basename as fallback.
"""

from __future__ import annotations

import os
import re

# Matches Windows drive letter patterns like C:\ or D:/
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[/\\]")


def is_absolute_path(path: str) -> bool:
    """Check if a path is absolute (Unix or Windows)."""
    if not path:
        return False
    if path.startswith("/"):
        return True
    if _WINDOWS_DRIVE_RE.match(path):
        return True
    return False


def sanitize_path(path: str, library_root: str | None = None) -> str:
    """Sanitize a file path to ensure it is relative.

    Args:
        path: The file path to sanitize.
        library_root: Optional library root directory. If provided and path
            starts with this prefix, the prefix is stripped to produce a
            relative path.

    Returns:
        A relative path that never starts with "/" or a Windows drive letter.
    """
    if not path:
        return path

    # Already relative — return as-is
    if not is_absolute_path(path):
        return path

    # If library_root is provided, try to strip it
    if library_root:
        # Normalize separators for comparison
        norm_path = path.replace("\\", "/")
        norm_root = library_root.replace("\\", "/").rstrip("/") + "/"

        if norm_path.startswith(norm_root):
            return norm_path[len(norm_root):]

        # Also try case-insensitive match for Windows paths
        if norm_path.lower().startswith(norm_root.lower()):
            return norm_path[len(norm_root):]

    # Fallback: return basename only
    return os.path.basename(path)
