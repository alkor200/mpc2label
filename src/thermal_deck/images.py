"""Beschafft die Kartenbilder, auf die eine MPC-Autofill-XML verweist.

Google-Drive-Einträge werden per ``gdown`` heruntergeladen (funktioniert nur,
wenn die Datei mit "Jeder mit Link" freigegeben ist – exakt so, wie
MPC-Autofill / DriveThruCards ihre Bild-Repos üblicherweise teilen).
Lokale Einträge (``sourceType == "Local File"``) verweisen direkt auf eine
Datei auf der Festplatte.
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
    """Liefert den lokalen Pfad zum Kartenbild von ``entry`` (lädt bei Bedarf)."""
    if entry.source_type == "Local File":
        path = Path(entry.id).expanduser()
        if not path.is_file():
            raise ImageFetchError(f"Lokale Bilddatei nicht gefunden: {path}")
        return path

    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{entry.id}{_guess_suffix(entry)}"
    if cached.is_file() and cached.stat().st_size > 0:
        return cached

    try:
        import gdown
    except ImportError as exc:  # pragma: no cover - Abhängigkeit fehlt
        raise ImageFetchError(
            "Paket 'gdown' fehlt (für Google-Drive-Downloads benötigt): pip install gdown"
        ) from exc

    try:
        result = gdown.download(id=entry.id, output=str(cached), quiet=True)
    except Exception as exc:  # gdown wirft diverse eigene Exceptions bei ungültiger/gesperrter id
        cached.unlink(missing_ok=True)
        raise ImageFetchError(
            f"Download von Google Drive fehlgeschlagen für id={entry.id} "
            f"({entry.display_name}): {exc}"
        ) from exc

    if result is None or not cached.is_file() or cached.stat().st_size == 0:
        cached.unlink(missing_ok=True)
        raise ImageFetchError(
            f"Download von Google Drive fehlgeschlagen für id={entry.id} "
            f"({entry.display_name}). Ist die Datei mit 'Jeder mit Link' freigegeben?"
        )
    return cached
