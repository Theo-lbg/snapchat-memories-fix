"""Merges the separate -overlay.png (captions, drawings, stickers) back onto
its -main photo or video, the way it looked in Snapchat."""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image


def merge_image_overlay(main_path: Path, overlay_path: Path, out_path: Path) -> None:
    base = Image.open(main_path).convert("RGBA")
    overlay = Image.open(overlay_path).convert("RGBA")
    if overlay.size != base.size:
        overlay = overlay.resize(base.size)
    merged = Image.alpha_composite(base, overlay)
    merged.convert("RGB").save(out_path, quality=95)


def merge_video_overlay(
    main_path: Path,
    overlay_path: Path,
    out_path: Path,
    timestamp: Optional[datetime] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> None:
    """Burns overlay.png onto every frame of the video via ffmpeg's overlay
    filter (re-encoding the video stream, audio passed through), writing the
    recovered timestamp/GPS metadata in the same pass."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(main_path),
        "-i", str(overlay_path),
        # libx264 requires even width/height; some Snapchat exports have odd
        # dimensions (e.g. 1170x2079), so pad up to the next even size after
        # compositing the overlay.
        # Many Snapchat captures are full-range yuvj420p; libx264 would keep
        # that flag (color_range=pc), which iCloud/Photos reject as an
        # unsupported file. Convert to the standard limited-range yuv420p
        # BT.709 that iPhones produce.
        "-filter_complex",
        "[0:v][1:v]scale2ref[base][ovr];[base][ovr]overlay=0:0,pad=ceil(iw/2)*2:ceil(ih/2)*2,"
        "scale=out_range=tv:out_color_matrix=bt709,format=yuv420p",
        "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-profile:v", "high",
        "-pix_fmt", "yuv420p",
        "-x264-params", "colorprim=bt709:transfer=bt709:colormatrix=bt709:fullrange=off",
        "-movflags", "+faststart",
        "-map_metadata", "0",
        "-c:a", "copy",
    ]
    if timestamp is not None:
        cmd += ["-metadata", f"creation_time={timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')}"]
    if lat is not None and lon is not None:
        iso6709 = f"{lat:+.4f}{lon:+.4f}/"
        cmd += ["-metadata", f"location={iso6709}", "-metadata", f"com.apple.quicktime.location.ISO={iso6709}"]
    cmd.append(str(out_path))
    subprocess.run(cmd, check=True)
