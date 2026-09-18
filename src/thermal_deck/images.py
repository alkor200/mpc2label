"""Fetches the card images referenced by an MPC-Autofill XML.

Google Drive entries are downloaded via ``gdown`` (only works if the file is
shared "Anyone with the link" - exactly how MPC-Autofill / DriveThruCards
usually share their image repos). Local entries
(``sourceType == "Local File"``) point directly to a file on disk.
"""

from __future__ import annotations

from pathlib import Path

from .mpcfill import CardEntry

DEFAULT_CACHE_DIRNAME = ".thermal-deck-cache"


class ImageFetchError(RuntimeError):
    pass


def _guess_suffix(entry: CardEntry) -> str:
    suffix = Path(entry.name or "").suffix
    return suffix if suffix else ".png"


def fetch_image(entry: CardEntry, cache_dir: Path) -> Path:
    """Returns the local path to ``entry``'s card image (downloading it if needed)."""
    if entry.source_type == "Local File":
        path = Path(entry.id).expanduser()
        if not path.is_file():
            raise ImageFetchError(f"Local image file not found: {path}")
        return path

    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{entry.id}{_guess_suffix(entry)}"
    if cached.is_file() and cached.stat().st_size > 0:
        return cached

    try:
        import gdown
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise ImageFetchError(
            "Package 'gdown' is missing (needed for Google Drive downloads): pip install gdown"
        ) from exc

    try:
        result = gdown.download(id=entry.id, output=str(cached), quiet=True)
    except Exception as exc:  # gdown raises various exceptions for invalid/locked ids
        cached.unlink(missing_ok=True)
        raise ImageFetchError(
            f"Google Drive download failed for id={entry.id} "
            f"({entry.display_name}): {exc}"
        ) from exc

    if result is None or not cached.is_file() or cached.stat().st_size == 0:
        cached.unlink(missing_ok=True)
        raise ImageFetchError(
            f"Google Drive download failed for id={entry.id} "
            f"({entry.display_name}). Is the file shared 'Anyone with the link'?"
        )
    return cached
