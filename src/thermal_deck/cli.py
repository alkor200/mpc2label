"""CLI: MPC-Autofill order.xml -> Labels auf einem Phomemo M110 (BLE)."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

from pyphomemo import ENV_ADDR, PhomemoPrinter, discover_printer, protocol
from pyphomemo import scan as phomemo_scan
from pyphomemo.imaging import image_to_raster, label_to_px, load_image, text_to_raster

from .images import DEFAULT_CACHE_DIRNAME, ImageFetchError, fetch_image
from .mpcfill import CardEntry, parse_order

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(name: str) -> str:
    return _SAFE_NAME_RE.sub("_", name).strip("_") or "karte"


def _collect_entries(order, include_backs: bool, sort: str) -> list[CardEntry]:
    entries = list(order.fronts)
    if include_backs:
        entries += order.backs
    if sort == "name":
        entries.sort(key=lambda e: e.display_name.lower())
    return entries


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="thermal-deck",
        description="Druckt Labels für alle Karten aus einer MPC-Autofill order.xml auf einem Phomemo M110.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser("scan", help="Sucht per Bluetooth LE nach Phomemo-Druckern.")
    scan_p.add_argument("--timeout", type=float, default=8.0, help="Scan-Dauer in Sekunden (Default: 8).")

    list_p = sub.add_parser("list", help="Listet die Karten der XML auf, ohne zu drucken.")
    list_p.add_argument("xml_file", type=Path)
    list_p.add_argument("--include-backs", action="store_true", help="Individuelle Kartenrückseiten mit auflisten.")
    list_p.add_argument("--sort", choices=["xml", "name"], default="xml")

    print_p = sub.add_parser(
        "print", help="Druckt für jede physische Kartenkopie (Slot) ein Label mit dem Kartenbild."
    )
    print_p.add_argument("xml_file", type=Path)
    print_p.add_argument(
        "--addr",
        default=None,
        help="Bluetooth-MAC des M110 (sonst PHOMEMO_ADDR-Env-Var oder Auto-Scan).",
    )
    print_p.add_argument("--label", default="40x30", help='Labelgröße "BREITExHOEHE" in mm (Default: 40x30).')
    print_p.add_argument(
        "--continuous",
        action="store_true",
        help=(
            "Endlosrolle ohne Lücken/Marken (Media-Modus 'continuous' statt "
            "'label mit Lücken'). Für Endlosrollen nötig, sonst kann der "
            "Drucker falsch vorschieben."
        ),
    )
    print_p.add_argument(
        "--no-fit",
        action="store_true",
        help="Bild nur auf Labelbreite skalieren statt in die volle Labelgröße einzupassen.",
    )
    print_p.add_argument(
        "--threshold",
        type=int,
        default=None,
        help="Fester Schwarz/Weiß-Schwellwert 0-255 statt Floyd-Steinberg-Dithering (Default: Dithering).",
    )
    print_p.add_argument("--font-size", type=int, default=32, help="Nur für Text-Fallback bei fehlgeschlagenem Bild-Download.")
    print_p.add_argument("--align", choices=["left", "center", "right"], default="center")
    print_p.add_argument(
        "--include-backs",
        action="store_true",
        help="Auch individuelle Kartenrückseiten aus <backs> drucken (Standard-Cardback wird ignoriert).",
    )
    print_p.add_argument("--sort", choices=["xml", "name"], default="xml")
    print_p.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help=f"Verzeichnis für heruntergeladene Kartenbilder (Default: <xml-Ordner>/{DEFAULT_CACHE_DIRNAME}).",
    )
    print_p.add_argument(
        "--dry-run",
        type=Path,
        default=None,
        help="Statt zu drucken: PNG-Vorschauen der Labels in dieses Verzeichnis schreiben.",
    )
    print_p.add_argument(
        "--delay",
        type=float,
        default=3.0,
        help="Pause zwischen zwei Labels in Sekunden (Default: 3.0 - der Druckkopf braucht Zeit).",
    )

    return parser


async def cmd_scan(args: argparse.Namespace) -> int:
    results = await phomemo_scan(timeout=args.timeout)
    if not results:
        print("Keine Bluetooth-LE-Geräte gefunden.")
        return 0
    for r in results:
        marker = ""
        if r.is_phomemo:
            marker = f"  <- Phomemo{f' ({r.model})' if r.model else ''}"
        print(f"{r.address}  {r.name}  rssi={r.rssi}{marker}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    order = parse_order(args.xml_file)
    entries = _collect_entries(order, args.include_backs, args.sort)
    for e in entries:
        slots = ",".join(map(str, e.slots)) or "-"
        print(f"[{e.side:5s}] {e.display_name:40s} x{e.quantity:<3} slots={slots}")
    total_slots = sum(e.quantity for e in entries)
    print(f"\n{len(entries)} Kartendesigns, {total_slots} Slots. Stock={order.stock!r} Foil={order.foil}")
    return 0


def _resolve_images(entries: list[CardEntry], cache_dir: Path) -> dict[str, Path | None]:
    """Lädt/cacht das Bild für jedes eindeutige Kartendesign (einmal pro id)."""
    paths: dict[str, Path | None] = {}
    for entry in entries:
        if entry.id in paths:
            continue
        try:
            paths[entry.id] = fetch_image(entry, cache_dir)
        except ImageFetchError as exc:
            print(f"WARNUNG: {exc} -> drucke Textlabel als Fallback.", file=sys.stderr)
            paths[entry.id] = None
    return paths


def _render_job(
    entry: CardEntry,
    image_path: Path | None,
    *,
    width_px: int,
    height_px: int | None,
    fit: bool,
    threshold: int | None,
    font_size: int,
    align: str,
) -> tuple[bytes, int, object]:
    if image_path is not None:
        img = load_image(image_path)
        box_height = height_px if fit else None
        return image_to_raster(img, width=width_px, height=box_height, threshold=threshold)
    return text_to_raster(entry.display_name, width=width_px, font_size=font_size, align=align)


async def _resolve_printer_address(explicit: str | None) -> str | None:
    """Feste Adresse (Arg/Env) übernehmen, sonst einmalig per BLE-Scan suchen."""
    addr = explicit or os.environ.get(ENV_ADDR)
    if addr:
        return addr
    print("Keine Drucker-Adresse angegeben (--addr/PHOMEMO_ADDR), scanne per Bluetooth LE ...")
    found = await discover_printer()
    if found is None:
        return None
    print(f"Gefunden: {found.name} ({found.address})")
    return found.address


async def cmd_print(args: argparse.Namespace) -> int:
    order = parse_order(args.xml_file)
    entries = _collect_entries(order, args.include_backs, args.sort)

    if not entries:
        print("Keine Karten in der XML gefunden.", file=sys.stderr)
        return 1

    jobs = [(entry, slot) for entry in entries for slot in (entry.slots or [0])]
    print(f"{len(entries)} Kartendesigns, {len(jobs)} Labels insgesamt (ein Label pro Kopie/Slot).")

    cache_dir = args.cache_dir or (args.xml_file.parent / DEFAULT_CACHE_DIRNAME)
    image_paths = _resolve_images(entries, cache_dir)

    width_px, height_px = label_to_px(args.label)
    media = protocol.MEDIA_CONTINUOUS if args.continuous else protocol.DEFAULT_MEDIA

    if args.dry_run:
        args.dry_run.mkdir(parents=True, exist_ok=True)
        for i, (entry, slot) in enumerate(jobs, 1):
            _, _, preview = _render_job(
                entry,
                image_paths.get(entry.id),
                width_px=width_px,
                height_px=height_px,
                fit=not args.no_fit,
                threshold=args.threshold,
                font_size=args.font_size,
                align=args.align,
            )
            out_path = args.dry_run / f"{i:03d}_{_safe_filename(entry.display_name)}_slot{slot}.png"
            preview.save(out_path)
            print(f"[{i}/{len(jobs)}] Vorschau: {out_path}")
        return 0

    addr = await _resolve_printer_address(args.addr)
    if addr is None:
        print("Kein Phomemo-Drucker gefunden.", file=sys.stderr)
        return 1

    # Eine Verbindung für den ganzen Batch (das ist der Stand, mit dem das
    # erste Label erfolgreich gedruckt hat). Zwischen zwei Jobs wird bewusst
    # länger gewartet, damit der Druckkopf den vorigen Job mechanisch fertig
    # hat, bevor der nächste Speed/Density/Media/Raster-Block rausgeht.
    try:
        async with PhomemoPrinter(addr) as printer:
            for i, (entry, slot) in enumerate(jobs, 1):
                raster, height, _ = _render_job(
                    entry,
                    image_paths.get(entry.id),
                    width_px=width_px,
                    height_px=height_px,
                    fit=not args.no_fit,
                    threshold=args.threshold,
                    font_size=args.font_size,
                    align=args.align,
                )
                print(f"[{i}/{len(jobs)}] Drucke: {entry.display_name} (slot {slot}) "
                      f"({len(raster)} Bytes, {height} Zeilen)")
                await printer.print_raster(raster, height, width_bytes=width_px // 8, media=media)
                if i < len(jobs):
                    print(f"  warte {args.delay:.1f}s ...")
                    await asyncio.sleep(args.delay)
    except Exception as exc:
        print(f"Druckerfehler bei Label {i}/{len(jobs)} ({entry.display_name}): {exc}", file=sys.stderr)
        return 1

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        return asyncio.run(cmd_scan(args))
    if args.command == "list":
        return cmd_list(args)
    if args.command == "print":
        return asyncio.run(cmd_print(args))

    parser.error("Unbekannter Befehl")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
