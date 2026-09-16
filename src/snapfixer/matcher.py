"""Correlates memories_history.json entries with media files.

Snapchat's JSON has no filename or media ID -- just Date / Location / Media
Type, in the same relative order the files themselves were produced in. Media
filenames carry the date (from the export) but not the time or GPS. So the
only way to recover exact time + GPS is: group both lists by date, and pair
them up in order within each date group.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .zip_source import MediaItem

LOCATION_RE = re.compile(r"Latitude,\s*Longitude:\s*(-?[\d.]+),\s*(-?[\d.]+)")


@dataclass
class JsonEntry:
    date: datetime
    lat: Optional[float]
    lon: Optional[float]
    media_type: str  # "Image" or "Video"


@dataclass
class MatchedMemory:
    item: MediaItem
    timestamp: Optional[datetime]  # None if no JSON entry could be matched
    lat: Optional[float]
    lon: Optional[float]


def load_json_entries(memories_json: Path) -> list[JsonEntry]:
    data = json.loads(memories_json.read_text())
    raw = data.get("Saved Media", [])
    entries = []
    for r in raw:
        dt = datetime.strptime(r["Date"], "%Y-%m-%d %H:%M:%S %Z").replace(tzinfo=timezone.utc)
        lat = lon = None
        loc = r.get("Location") or ""
        m = LOCATION_RE.search(loc)
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
        media_type = "Video" if r.get("Media Type", "").lower().startswith("v") else "Image"
        entries.append(JsonEntry(date=dt, lat=lat, lon=lon, media_type=media_type))
    return entries


def _kind_of_ext(ext: str) -> str:
    return "Video" if ext.lower() in ("mp4", "mov") else "Image"


MatchInfo = tuple[datetime, Optional[float], Optional[float]]  # (timestamp, lat, lon)


def build_match_index(refs: list[tuple[str, str, str]], json_entries: list[JsonEntry]) -> dict[str, MatchInfo]:
    """refs: (date, uuid, ext) for every *-main.* file in the export (see
    ExportSource.list_main_refs -- this is a listing operation, no file
    bytes needed). Groups both lists by date, pairs them up in order within
    each (date, Media Type) group, and falls back to date-only (no
    time/GPS) for any file beyond its date's JSON entries.

    Returns {uuid: (timestamp, lat, lon)} covering every ref exactly once --
    this is the whole point of doing this as a separate pass before
    extraction even starts: the JSON has no filename, so pairing by date
    only works once every file's date for that day is visible at once, but
    a real Snapchat export is too big to hold every file's bytes in memory
    or on disk at the same time.
    """
    by_date_json: dict[str, list[JsonEntry]] = defaultdict(list)
    for e in json_entries:
        by_date_json[e.date.strftime("%Y-%m-%d")].append(e)

    by_date_refs: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for date, uuid, ext in refs:
        by_date_refs[date].append((uuid, ext))

    index: dict[str, MatchInfo] = {}
    for date, day_refs in by_date_refs.items():
        day_json = list(by_date_json.get(date, []))
        # Images and videos are matched to JSON entries of the corresponding
        # Media Type separately, in original order, so a mixed day doesn't
        # pair a photo with a video's GPS point.
        for kind in ("Image", "Video"):
            kind_refs = [(uuid, ext) for uuid, ext in day_refs if _kind_of_ext(ext) == kind]
            kind_json = [e for e in day_json if e.media_type == kind]
            for i, (uuid, _ext) in enumerate(kind_refs):
                if i < len(kind_json):
                    e = kind_json[i]
                    index[uuid] = (e.date, e.lat, e.lon)
                else:
                    fallback_dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    index[uuid] = (fallback_dt, None, None)
    return index


def match(items: list[MediaItem], json_entries: list[JsonEntry]) -> list[MatchedMemory]:
    """Convenience wrapper around build_match_index() for callers that
    already hold the full MediaItem list in memory (e.g. tests, or a small
    already-extracted folder) -- the real CLI/GUI pipeline uses
    build_match_index() directly against list_main_refs() instead, so it
    never needs to keep extracted files around past a single streaming pass."""
    refs = [(it.date, it.uuid, it.main_path.suffix.lstrip(".")) for it in items]
    index = build_match_index(refs, json_entries)
    results = []
    for it in items:
        timestamp, lat, lon = index[it.uuid]
        results.append(MatchedMemory(item=it, timestamp=timestamp, lat=lat, lon=lon))
    return results
