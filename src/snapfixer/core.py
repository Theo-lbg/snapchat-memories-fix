"""Processing pipeline shared by the CLI and the GUI.

Two-pass design, required by how Snapchat's export is shaped: the JSON has
no filename, only (date, GPS, media type) in upload order, so recovering the
exact time/GPS for a file means grouping every file for a given date
together and pairing them up in order -- which needs every file's date
visible before any pairing can happen. But the export itself can be tens of
GB spread across a dozen nested zips, too big to extract all at once
alongside the output. So:

  1. list_main_refs() -- cheap, listing-only, no extraction -- to compute
     the full JSON <-> uuid match up front.
  2. iter_media() -- the real streaming extraction, one nested zip at a
     time, immediately processed and written to `output` before moving on,
     using the match computed in step 1.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import metadata, overlay
from .matcher import build_match_index, load_json_entries
from .zip_source import ExportSource, MediaItem


class SourceError(Exception):
    pass


@dataclass
class Options:
    merge_overlay: bool = True
    dry_run: bool = False
    limit: Optional[int] = None


@dataclass
class ItemResult:
    name: str
    ok: bool = True
    outname: str = ""
    message: str = ""
    timestamp: Optional[datetime] = None
    has_gps: bool = False
    skipped: bool = False


@dataclass
class RunSummary:
    total: int = 0
    ok: int = 0
    failed: int = 0
    fallback_count: int = 0  # matched to a date but not an exact JSON entry (no time/GPS)


def build_output_path(output_dir: Path, uuid: str, ext: str, timestamp: datetime) -> Path:
    year_dir = output_dir / f"{timestamp.year:04d}"
    name = f"{timestamp:%Y-%m-%d_%H-%M-%S}_{uuid[:8]}{ext}"
    return year_dir / name


def _process_one(item: MediaItem, timestamp: datetime, lat, lon, out_path: Path, merge_overlays: bool) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    is_video = out_path.suffix.lower() in (".mp4", ".mov")

    if is_video:
        if merge_overlays and item.overlay_path:
            overlay.merge_video_overlay(
                item.main_path, item.overlay_path, out_path,
                timestamp=timestamp, lat=lat, lon=lon,
            )
        else:
            tmp = metadata.write_video_metadata(item.main_path, timestamp, lat, lon)
            shutil.move(str(tmp), str(out_path))
    else:
        if merge_overlays and item.overlay_path:
            overlay.merge_image_overlay(item.main_path, item.overlay_path, out_path)
        else:
            shutil.copy2(item.main_path, out_path)
        metadata.write_image_metadata(out_path, timestamp, lat, lon)

    metadata.set_filesystem_dates(out_path, timestamp)


def estimate_source_bytes(source: Path) -> int:
    """Rough size estimate for a preflight disk-space check. Media inside
    the export is already compressed (jpg/mp4), so the zip's own size (or a
    folder's total size) is a reasonable proxy for how much output it'll
    produce -- not exact (html/json overhead, overlay re-encodes change
    size a bit) but good enough to warn on "the disk is clearly too small"."""
    source = Path(source)
    if source.is_file():
        return source.stat().st_size
    return sum(p.stat().st_size for p in source.rglob("*") if p.is_file())


def run(source: Path, output: Path, options: Options, on_progress: Optional[Callable[[int, int, ItemResult], None]] = None) -> RunSummary:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)

    with ExportSource(source) as src:
        if src.memories_json is None:
            raise SourceError(
                "memories_history.json introuvable. Choisissez le zip ou dossier "
                "primaire de l'export Snapchat (celui qui contient json/ et html/), "
                "pas un des dossiers -1/-2/... additionnels."
            )

        json_entries = load_json_entries(src.memories_json)
        refs = src.list_main_refs()
        if options.limit:
            refs = refs[: options.limit]
        total = len(refs)
        wanted_uuids = {uuid for _date, uuid, _ext in refs}
        index = build_match_index(refs, json_entries)

        summary = RunSummary(total=total)
        processed = 0

        if total == 0:
            return summary

        for item in src.iter_media():
            if item.uuid not in wanted_uuids:
                continue
            timestamp, lat, lon = index[item.uuid]
            if lat is None:
                summary.fallback_count += 1

            out_path = build_output_path(output, item.uuid, item.main_path.suffix, timestamp)
            processed += 1
            result = ItemResult(name=item.main_path.name, timestamp=timestamp, has_gps=lat is not None)

            if options.dry_run:
                result.skipped = True
                result.outname = str(out_path)
            else:
                try:
                    _process_one(item, timestamp, lat, lon, out_path, options.merge_overlay)
                    result.outname = out_path.name
                    summary.ok += 1
                except Exception as exc:  # noqa: BLE001 - surface any failure per-item, keep going
                    result.ok = False
                    result.message = str(exc)
                    summary.failed += 1

            if on_progress:
                on_progress(processed, total, result)

            if processed >= total:
                break

        return summary
