"""Writes recovered timestamp + GPS metadata into output media files."""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

import piexif

_HAS_SETFILE = shutil.which("SetFile") is not None


def _deg_to_dms_rational(deg: float) -> tuple:
    deg = abs(deg)
    d = int(deg)
    m_float = (deg - d) * 60
    m = int(m_float)
    s = round((m_float - m) * 60 * 100)
    return ((d, 1), (m, 1), (s, 100))


def write_image_metadata(path: Path, timestamp: datetime, lat: Optional[float], lon: Optional[float]) -> None:
    date_str = timestamp.strftime("%Y:%m:%d %H:%M:%S")
    try:
        exif_dict = piexif.load(str(path))
    except Exception:
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

    exif_dict["0th"][piexif.ImageIFD.DateTime] = date_str
    exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = date_str
    exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = date_str

    if lat is not None and lon is not None:
        exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = "N" if lat >= 0 else "S"
        exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = _deg_to_dms_rational(lat)
        exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = "E" if lon >= 0 else "W"
        exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = _deg_to_dms_rational(lon)

    exif_bytes = piexif.dump(exif_dict)
    piexif.insert(exif_bytes, str(path))


def write_video_metadata(path: Path, timestamp: datetime, lat: Optional[float], lon: Optional[float]) -> Path:
    """ffmpeg can't edit metadata in place, so this writes a sibling temp
    file with -codec copy (no re-encoding) and returns its path; the caller
    is responsible for swapping it in for `path`."""
    creation_time = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    out_path = path.with_name(path.stem + ".tmp" + path.suffix)

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(path),
        "-map_metadata", "0",
        "-metadata", f"creation_time={creation_time}",
        "-codec", "copy",
    ]
    if lat is not None and lon is not None:
        iso6709 = f"{lat:+.4f}{lon:+.4f}/"
        cmd += ["-metadata", f"location={iso6709}", "-metadata", f"com.apple.quicktime.location.ISO={iso6709}"]
    cmd.append(str(out_path))

    subprocess.run(cmd, check=True)
    return out_path


def set_filesystem_dates(path: Path, timestamp: datetime) -> None:
    """Sets the file's mtime (and, on macOS, its Finder "date created") to
    the recovered capture date -- otherwise Finder just shows today, since
    that's only when this tool wrote the file, not when the memory was
    captured."""
    ts = timestamp.timestamp()
    os.utime(path, (ts, ts))
    if _HAS_SETFILE:
        subprocess.run(
            ["SetFile", "-d", timestamp.strftime("%m/%d/%Y %H:%M:%S"), str(path)],
            check=False,
        )
