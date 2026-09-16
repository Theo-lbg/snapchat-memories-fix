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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recovers timestamps, GPS and overlays for a Snapchat data export.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--source", required=True, type=Path, help="Snapchat export zip or extracted folder")
    parser.add_argument("--output", required=True, type=Path, help="destination folder for fixed photos/videos")
    parser.add_argument("--limit", type=int, default=None, help="only process the first N items (for testing)")
    parser.add_argument("--no-overlay", action="store_true", help="don't merge -overlay.png onto -main files")
    parser.add_argument("--dry-run", action="store_true", help="match and report, but don't write any output")
    args = parser.parse_args()

    options = core.Options(merge_overlay=not args.no_overlay, dry_run=args.dry_run, limit=args.limit)

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
