"""Walks a Snapchat export (one outer zip full of nested zips, a single zip,
or an already-extracted folder) and yields media files without ever fully
extracting everything to disk at once.

Snapchat's "Download My Data" export ships as a primary folder (json/, html/,
memories/) plus, for large accounts, extra zips named -1, -2, ... containing
only more memories/. Some export tools then bundle all of those into one big
zip. This module normalizes all of those shapes into a single stream of
(main_path, overlay_path_or_None, extracted_from) tuples, extracting nested
zips one at a time into a scratch dir and cleaning up as it goes so disk
usage never exceeds ~1 nested zip's worth of data at a time.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

MEMORIES_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<uuid>[0-9a-fA-F-]+)-(?P<kind>main|overlay)\.(?P<ext>\w+)$"
)

# Matches a `memories/` path component whether it's at the zip root
# (nested exports: "memories/2022-...") or nested under a parent dir
# (primary export: "snap/mydata~.../memories/2022-..."). A plain
# "/memories/" substring check misses the root case.
IN_MEMORIES_DIR_RE = re.compile(r"(?:^|/)memories/")


@dataclass
class MediaItem:
    date: str  # YYYY-MM-DD, from the filename
    uuid: str
    main_path: Path
    overlay_path: Optional[Path]


def _classify(files: dict[str, Path]) -> Iterator[MediaItem]:
    """Pairs up *-main.* and *-overlay.png files found in one directory."""
    mains: dict[str, tuple[str, Path]] = {}
    overlays: dict[str, Path] = {}
    for name, path in files.items():
        m = MEMORIES_RE.match(name)
        if not m:
            continue
        if m.group("kind") == "main":
            mains[m.group("uuid")] = (m.group("date"), path)
        else:
            overlays[m.group("uuid")] = path
    for uuid, (date, path) in mains.items():
        yield MediaItem(date=date, uuid=uuid, main_path=path, overlay_path=overlays.get(uuid))


def _find_json(root: Path) -> Optional[Path]:
    candidates = list(root.rglob("memories_history.json"))
    return candidates[0] if candidates else None


def _uuid_kind_of(name: str) -> Optional[tuple[str, str]]:
    m = MEMORIES_RE.match(name.rsplit("/", 1)[-1])
    return (m.group("uuid"), m.group("kind")) if m else None


@dataclass(frozen=True)
class _NestedZip:
    """A zip to pull memories from lazily, one at a time.

    `entry` is None when `outer` is itself a standalone .zip file already
    sitting on disk (e.g. a Snapchat "-N.zip" chunk found loose inside a
    folder source, never extracted). Otherwise `outer` is the zip that
    embeds this one, and `entry` is its name inside it."""

    outer: Path
    entry: Optional[str] = None


class ExportSource:
    """Context manager exposing .memories_json and .iter_media() for a Snapchat export.

    `path` may be the big outer zip, a single Snapchat zip, or an already
    extracted "mydata~..." folder. Nested zips are extracted lazily into a
    temp dir that is cleaned up on __exit__ (or immediately after each nested
    zip is fully consumed, when iterating lazily via iter_media()).
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._tmp = tempfile.mkdtemp(prefix="snapfixer_")
        self.memories_json: Optional[Path] = None
        self._primary_dir: Optional[Path] = None
        # One entry per nested zip (standalone file or embedded in another
        # zip), extracted lazily one at a time in iter_media() so we never
        # hold more than one nested zip's worth of extra disk space at once.
        self._nested_entries: list[_NestedZip] = []
        # Snapchat/export-tool zips can genuinely duplicate a whole chunk
        # (seen in the wild: both an already-extracted "-13" folder and a
        # "-13.zip" with the identical files). Track uuids already claimed
        # for extraction so a later duplicate is skipped before we ever pay
        # to extract or re-encode it.
        self._seen: set[tuple[str, str]] = set()  # (uuid, kind) already claimed for extraction
        # uuids that have a -overlay.png, filled in by list_main_refs()
        self.overlay_uuids: set[str] = set()

    def _filter_new(self, names: list[str]) -> list[str]:
        kept = []
        for n in names:
            uuid_kind = _uuid_kind_of(n)
            if uuid_kind is None:
                kept.append(n)  # not a memories file (e.g. index.html) -- keep as-is
                continue
            if uuid_kind in self._seen:
                continue
            self._seen.add(uuid_kind)
            kept.append(n)
        return kept

    def _filter_new_paths(self, paths: list[Path]) -> list[Path]:
        kept = []
        for p in paths:
            uuid_kind = _uuid_kind_of(p.name)
            if uuid_kind is None:
                continue
            if uuid_kind in self._seen:
                continue
            self._seen.add(uuid_kind)
            kept.append(p)
        return kept

    def __enter__(self) -> "ExportSource":
        if self.path.is_dir():
            self._primary_dir = self.path
            self.memories_json = _find_json(self.path)
            # A folder source can itself contain loose "-N.zip" chunks that
            # were never extracted (e.g. the user dumped Snapchat's several
            # downloaded zips into one folder without unzipping them) -- an
            # already-extracted "memories" folder alone isn't the whole story.
            self._nested_entries = [_NestedZip(outer=p) for p in self.path.rglob("*.zip")]
        elif zipfile.is_zipfile(self.path):
            self._open_outer_zip(self.path)
        else:
            raise ValueError(f"{self.path} is neither a directory nor a zip file")
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _open_outer_zip(self, zip_path: Path) -> None:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            has_primary_content = any(
                n.endswith("json/memories_history.json") or IN_MEMORIES_DIR_RE.search(n) for n in names
            )
            nested_zips = [n for n in names if n.lower().endswith(".zip")]

            if has_primary_content:
                extract_dir = Path(self._tmp) / "primary"
                members = self._filter_new([n for n in names if not n.lower().endswith(".zip")])
                zf.extractall(extract_dir, members=members)
                self._primary_dir = extract_dir
                self.memories_json = _find_json(extract_dir)

            self._nested_entries = [_NestedZip(outer=zip_path, entry=n) for n in nested_zips]

        if self.memories_json is None and self._nested_entries:
            # Rare shape: the primary folder itself is one of the "nested" zips.
            for nz in list(self._nested_entries):
                tmp_copy = Path(self._tmp) / "peek.zip"
                with zipfile.ZipFile(nz.outer) as zf, zf.open(nz.entry) as src, open(tmp_copy, "wb") as out:
                    shutil.copyfileobj(src, out)
                if zipfile.is_zipfile(tmp_copy):
                    with zipfile.ZipFile(tmp_copy) as zf2:
                        if any(name.endswith("json/memories_history.json") for name in zf2.namelist()):
                            extract_dir = Path(self._tmp) / "primary"
                            zf2.extractall(extract_dir)
                            self._primary_dir = extract_dir
                            self.memories_json = _find_json(extract_dir)
                            self._nested_entries.remove(nz)
                            tmp_copy.unlink(missing_ok=True)
                            break
                tmp_copy.unlink(missing_ok=True)

    def list_main_refs(self) -> list[tuple[str, str, str]]:
        """Lists every (date, uuid, ext) for *-main.* files across the whole
        export -- primary dir plus every nested zip -- without extracting
        anything. Nested zip entries in the wild are stored uncompressed, so
        their central directory can be read straight off the open stream
        with no temp file; this falls back to a temp copy if a given zip
        isn't seekable that way.

        Used to precompute the full JSON <-> file match (which needs every
        item's date visible before it can group by date) before the actual
        streaming extraction in iter_media() begins -- so the real pass
        never has to hold the full item list in memory with paths into
        directories that get cleaned up as it goes.

        Applies the same (uuid, kind) dedup as iter_media(), using its own
        local `seen` set so it doesn't disturb iter_media()'s extraction-time
        dedup state.
        """
        seen: set[tuple[str, str]] = set()
        refs: list[tuple[str, str, str]] = []

        def consume(names: list[str]) -> None:
            for n in names:
                if not IN_MEMORIES_DIR_RE.search(n) or n.endswith("/"):
                    continue
                m = MEMORIES_RE.match(n.rsplit("/", 1)[-1])
                if not m:
                    continue
                key = (m.group("uuid"), m.group("kind"))
                if key in seen:
                    continue
                seen.add(key)
                if m.group("kind") == "main":
                    refs.append((m.group("date"), m.group("uuid"), m.group("ext")))
                else:
                    self.overlay_uuids.add(m.group("uuid"))

        self.overlay_uuids = set()
        if self._primary_dir is not None:
            for memories_dir in self._primary_dir.rglob("memories"):
                if memories_dir.is_dir():
                    consume([f"memories/{p.name}" for p in memories_dir.iterdir() if p.is_file()])

        for nz in self._nested_entries:
            if nz.entry is None:
                # Standalone zip file already on disk -- list it directly.
                with zipfile.ZipFile(nz.outer) as zf:
                    consume(zf.namelist())
                continue

            with zipfile.ZipFile(nz.outer) as zf:
                with zf.open(nz.entry) as stream:
                    if stream.seekable():
                        with zipfile.ZipFile(stream) as zf2:
                            consume(zf2.namelist())
                        continue
                tmp_copy = Path(self._tmp) / "list_peek.zip"
                with zipfile.ZipFile(nz.outer) as zf3, zf3.open(nz.entry) as src, open(tmp_copy, "wb") as out:
                    shutil.copyfileobj(src, out)
                with zipfile.ZipFile(tmp_copy) as zf2:
                    consume(zf2.namelist())
                tmp_copy.unlink(missing_ok=True)

        return refs

    def iter_media(self) -> Iterator[MediaItem]:
        """Yields every MediaItem, extracting nested zips one at a time and
        deleting each one's temp copy right after it has been fully walked.

        Callers must finish using a MediaItem's paths before requesting the
        next one (e.g. process-then-write per item, as the CLI does) since
        the underlying files are deleted once their source zip is drained.
        """
        if self._primary_dir is not None:
            for memories_dir in self._primary_dir.rglob("memories"):
                if memories_dir.is_dir():
                    kept = self._filter_new_paths([p for p in memories_dir.iterdir() if p.is_file()])
                    files = {p.name: p for p in kept}
                    yield from _classify(files)

        for nz in self._nested_entries:
            extract_dir = Path(self._tmp) / "extract_nested"

            if nz.entry is None:
                # Standalone zip file already on disk -- open it directly,
                # no temp copy needed (and never delete the user's own file).
                with zipfile.ZipFile(nz.outer) as zf:
                    members = self._filter_new(
                        [n for n in zf.namelist() if IN_MEMORIES_DIR_RE.search(n) and not n.endswith("/")]
                    )
                    zf.extractall(extract_dir, members=members)
            else:
                nested_copy = Path(self._tmp) / "nested.zip"
                with zipfile.ZipFile(nz.outer) as zf, zf.open(nz.entry) as src, open(nested_copy, "wb") as out:
                    shutil.copyfileobj(src, out)
                with zipfile.ZipFile(nested_copy) as zf:
                    members = self._filter_new(
                        [n for n in zf.namelist() if IN_MEMORIES_DIR_RE.search(n) and not n.endswith("/")]
                    )
                    zf.extractall(extract_dir, members=members)
                nested_copy.unlink(missing_ok=True)

            memories_dirs = list(extract_dir.rglob("memories"))
            for memories_dir in memories_dirs:
                if memories_dir.is_dir():
                    files = {p.name: p for p in memories_dir.iterdir() if p.is_file()}
                    yield from _classify(files)
            shutil.rmtree(extract_dir, ignore_errors=True)
