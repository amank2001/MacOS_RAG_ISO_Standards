"""Per-launch API token authentication for the Indexer."""

from __future__ import annotations

import platform
import secrets
from pathlib import Path

from fastapi import HTTPException, Request

# Module-level storage for the active token.
_current_token: str | None = None


def _get_token_dir() -> Path:
    """Return the application support directory for token storage."""
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "ISOStandardsKB"
    # Fallback for non-macOS systems
    return Path.home() / ".isostandardskb"


def token_path() -> Path:
    """Return the full path to the API token file."""
    return _get_token_dir() / "api_token"


def generate_token() -> str:
    """Generate a random 32-byte hex token and write it to the app support directory.

    Sets the module-level ``_current_token`` so that ``verify_token`` can
    validate incoming requests against it.

    Returns the generated token string.
    """
    global _current_token  # noqa: PLW0603

    token = secrets.token_hex(32)

    token_file = token_path()
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(token, encoding="utf-8")

    _current_token = token
    return token


async def verify_token(request: Request) -> None:
    """FastAPI dependency that validates the Bearer token on each request.

    Raises ``HTTPException(401)`` when the token is missing or invalid.
    """
    auth_header = request.headers.get("Authorization")

    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = auth_header[len("Bearer "):]

    if token != _current_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
