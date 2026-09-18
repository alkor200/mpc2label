"""CLI: MPC-Autofill order.xml -> labels on a Phomemo M110 (BLE)."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

from pyphomemo import ENV_ADDR, PhomemoPrinter, discover_printer, protocol
from pyphomemo import scan as phomemo_scan
from pyphomemo.imaging import image_to_raster, load_image, text_to_raster

from .images import DEFAULT_CACHE_DIRNAME, ImageFetchError, fetch_image
from .mpcfill import CardEntry, parse_order

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(name: str) -> str:
    return _SAFE_NAME_RE.sub("_", name).strip("_") or "card"


def _collect_entries(order, include_backs: bool, sort: str) -> list[CardEntry]:
    entries = list(order.fronts)
    if include_backs:
        entries += order.backs
    if sort == "name":
        entries.sort(key=lambda e: e.display_name.lower())
    return entries


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mpc2label",
        description="Prints labels for every card in an MPC-Autofill order.xml on a Phomemo M110.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser("scan", help="Scan for Phomemo printers over Bluetooth LE.")
    scan_p.add_argument("--timeout", type=float, default=8.0, help="Scan duration in seconds (default: 8).")

    list_p = sub.add_parser("list", help="List the cards in the XML without printing.")
    list_p.add_argument("xml_file", type=Path)
    list_p.add_argument("--include-backs", action="store_true", help="Also list individual card backs.")
    list_p.add_argument("--sort", choices=["xml", "name"], default="xml")

    print_p = sub.add_parser(
        "print", help="Print one label with the card image for every physical card copy (slot)."
    )
    print_p.add_argument("xml_file", type=Path)
    print_p.add_argument(
        "--addr",
        default=None,
        help="Bluetooth MAC of the M110 (otherwise the PHOMEMO_ADDR env var or auto-scan).",
    )
    print_p.add_argument(
        "--crop-pct",
        type=float,
        default=8.0,
        help=(
            "Percent of width/height to crop off every edge of the card "
            "image before scaling (removes the black card frame, default: "
            "8; 0 = no crop)."
        ),
    )
    print_p.add_argument(
        "--threshold",
        type=int,
        default=None,
        help="Fixed black/white threshold instead of Floyd-Steinberg dithering (default: dithering).",
    )
    print_p.add_argument("--font-size", type=int, default=32, help="Only used for the text fallback.")
    print_p.add_argument("--align", choices=["left", "center", "right"], default="center")
    print_p.add_argument(
        "--include-backs",
        action="store_true",
        help="Also print labels for individual card backs from <backs> (the generic <cardback> is ignored).",
    )
    print_p.add_argument("--sort", choices=["xml", "name"], default="xml")
    print_p.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help=f"Directory for downloaded card images (default: <xml-dir>/{DEFAULT_CACHE_DIRNAME}).",
    )
    print_p.add_argument(
        "--dry-run",
        type=Path,
        default=None,
        help="Instead of printing: write PNG previews of the labels to this directory.",
    )
    print_p.add_argument(
        "--delay",
        type=float,
        default=5.0,
        help=(
            "Pause after every label (including the last) in seconds, "
            "before the next job is sent or the connection is closed - the "
            "print head needs this time to mechanically finish printing "
            "(default: 5.0)."
        ),
    )

    return parser


async def cmd_scan(args: argparse.Namespace) -> int:
    results = await phomemo_scan(timeout=args.timeout)
    if not results:
        print("No Bluetooth LE devices found.")
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
    print(f"\n{len(entries)} card designs, {total_slots} slots. Stock={order.stock!r} Foil={order.foil}")
    return 0


def _resolve_images(entries: list[CardEntry], cache_dir: Path) -> dict[str, Path | None]:
    """Downloads/caches the image for every distinct card design (once per id)."""
    paths: dict[str, Path | None] = {}
    for entry in entries:
        if entry.id in paths:
            continue
        try:
            paths[entry.id] = fetch_image(entry, cache_dir)
        except ImageFetchError as exc:
            print(f"WARNING: {exc} -> printing a text label as fallback.", file=sys.stderr)
            paths[entry.id] = None
    return paths


def _crop_margin(img, pct: float):
    """Crops ``pct`` percent of width/height off every edge.

    MPC-Autofill card images have the black card frame all the way around
    (~6-9% per edge, measured on Sol Ring/Black Lotus) - on a 48mm label that
    wastes space the name/art could use instead.
    """
    if pct <= 0:
        return img
    w, h = img.size
    dx = int(w * pct / 100)
    dy = int(h * pct / 100)
    return img.crop((dx, dy, w - dx, h - dy))


def _render_job(
    entry: CardEntry,
    image_path: Path | None,
    *,
    width_px: int,
    threshold: int | None,
    font_size: int,
    align: str,
    crop_pct: float = 0.0,
) -> tuple[bytes, int, object]:
    """Renders one label at the full printer width, height follows the image."""
    if image_path is not None:
        img = _crop_margin(load_image(image_path), crop_pct)
        return image_to_raster(img, width=width_px, threshold=threshold)
    return text_to_raster(entry.display_name, width=width_px, font_size=font_size, align=align)


async def _resolve_printer_address(explicit: str | None) -> str | None:
    """Uses a fixed address (arg/env) if given, otherwise scans over BLE once."""
    addr = explicit or os.environ.get(ENV_ADDR)
    if addr:
        return addr
    print("No printer address given (--addr/PHOMEMO_ADDR), scanning over Bluetooth LE ...")
    found = await discover_printer()
    if found is None:
        return None
    print(f"Found: {found.name} ({found.address})")
    return found.address


async def cmd_print(args: argparse.Namespace) -> int:
    order = parse_order(args.xml_file)
    entries = _collect_entries(order, args.include_backs, args.sort)

    if not entries:
        print("No cards found in the XML.", file=sys.stderr)
        return 1

    jobs = [(entry, slot) for entry in entries for slot in (entry.slots or [0])]
    print(f"{len(entries)} card designs, {len(jobs)} labels total (one label per copy/slot).")

    cache_dir = args.cache_dir or (args.xml_file.parent / DEFAULT_CACHE_DIRNAME)
    image_paths = _resolve_images(entries, cache_dir)

    # Always the full printer width (48mm/384 dots), height follows the card image.
    width_px = protocol.PRINTER_WIDTH_PX
    # Always continuous-roll mode: our M110 has a genuine continuous roll
    # with no gaps/marks, the gap-sensor mode is never right here.
    media = protocol.MEDIA_CONTINUOUS

    if args.dry_run:
        args.dry_run.mkdir(parents=True, exist_ok=True)
        for i, (entry, slot) in enumerate(jobs, 1):
            _, _, preview = _render_job(
                entry,
                image_paths.get(entry.id),
                width_px=width_px,
                threshold=args.threshold,
                font_size=args.font_size,
                align=args.align,
                crop_pct=args.crop_pct,
            )
            out_path = args.dry_run / f"{i:03d}_{_safe_filename(entry.display_name)}_slot{slot}.png"
            preview.save(out_path)
            print(f"[{i}/{len(jobs)}] Preview: {out_path}")
        return 0

    addr = await _resolve_printer_address(args.addr)
    if addr is None:
        print("No Phomemo printer found.", file=sys.stderr)
        return 1

    # One connection for the whole batch (this is the setup that reliably
    # prints the first label). We deliberately wait longer between jobs so
    # the print head has mechanically finished the previous job before the
    # next speed/density/media/raster block goes out.
    try:
        async with PhomemoPrinter(addr) as printer:
            for i, (entry, slot) in enumerate(jobs, 1):
                raster, height, _ = _render_job(
                    entry,
                    image_paths.get(entry.id),
                    width_px=width_px,
                    threshold=args.threshold,
                    font_size=args.font_size,
                    align=args.align,
                    crop_pct=args.crop_pct,
                )
                print(f"[{i}/{len(jobs)}] Printing: {entry.display_name} (slot {slot}) "
                      f"({len(raster)} bytes, {height} lines)")
                await printer.print_raster(raster, height, width_bytes=width_px // 8, media=media)
                # Wait after the last job too, not just between jobs:
                # print_raster() returns as soon as the bytes are sent, the
                # head still needs time afterwards to mechanically finish
                # printing/ejecting. If `async with` closes the connection
                # while that's happening, the physical print aborts (short
                # paper feed, no image, no exception) - that was the bug.
                print(f"  waiting {args.delay:.1f}s ...")
                await asyncio.sleep(args.delay)
    except Exception as exc:
        print(f"Printer error on label {i}/{len(jobs)} ({entry.display_name}): {exc}", file=sys.stderr)
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

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
