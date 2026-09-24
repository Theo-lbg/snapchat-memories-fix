"""Command-line entry point. See snapfixer.core for the actual pipeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import core


def _format_result(i: int, total: int, result: core.ItemResult) -> str:
    prefix = f"[{i}/{total}] {result.name}"
    if result.skipped:
        return f"{prefix} -- simulation, ignore : {result.outname}"
    if not result.ok:
        return f"{prefix} -- ECHEC : {result.message}"
    gps_note = "" if result.has_gps else " (pas de correspondance JSON exacte -> date seule, pas d'heure/GPS)"
    return f"{prefix} -> {result.outname} ({result.timestamp:%Y-%m-%d %H:%M})" + gps_note


def _print_progress(i: int, total: int, result: core.ItemResult) -> None:
    if result.skipped:
        print(f"[{i}/{total}] {result.name} -- simulation, serait reparee")
    elif not result.ok:
        print(f"[{i}/{total}] {result.name} -- ECHEC : {result.message}")
    else:
        print(f"[{i}/{total}] {result.name} -- reparee")
    sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recovers timestamps, GPS and overlays for a Snapchat data export.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--source", type=Path, help="Snapchat export zip or extracted folder")
    parser.add_argument("--output", type=Path, help="destination folder for fixed photos/videos")
    parser.add_argument(
        "--repair-folder",
        type=Path,
        help="repair videos in an already-generated output folder, in place (no export needed): "
        "re-encodes full-range videos iCloud rejects to standard yuv420p",
    )
    parser.add_argument("--limit", type=int, default=None, help="only process the first N items (for testing)")
    parser.add_argument("--no-overlay", action="store_true", help="don't merge -overlay.png onto -main files")
    parser.add_argument("--dry-run", action="store_true", help="match and report, but don't write any output")
    parser.add_argument(
        "--only-overlay-videos",
        action="store_true",
        help="only (re)process videos that have an overlay (implies overlay merging); "
        "rewrites them in place in --output, leaving everything else untouched",
    )
    args = parser.parse_args()

    if args.repair_folder:
        try:
            summary = core.repair_folder(args.repair_folder, dry_run=args.dry_run, on_progress=_print_progress)
        except core.SourceError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"\ndone: {summary.ok}/{summary.total} video(s) reparee(s) dans {args.repair_folder}")
        return 1 if summary.failed else 0

    if not args.source or not args.output:
        parser.error("--source and --output are required (or use --repair-folder)")

    options = core.Options(
        merge_overlay=not args.no_overlay,
        dry_run=args.dry_run,
        limit=args.limit,
        only_overlay_videos=args.only_overlay_videos,
    )

    def on_progress(i, total, result):
        print(_format_result(i, total, result))
        if i % 25 == 0 or i == total:
            sys.stdout.flush()

    try:
        summary = core.run(args.source, args.output, options, on_progress=on_progress)
    except core.SourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"\ndone: {summary.ok}/{summary.total} ecrits dans {args.output}")
    if summary.failed:
        print(f"{summary.failed} echec(s) -- voir le journal ci-dessus", file=sys.stderr)
    print(f"note: {summary.fallback_count} item(s) sans correspondance JSON exacte -> date seule, pas d'heure/GPS")
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
