# snapchat-memories-fixer

Recovers real capture timestamps, GPS coordinates and text/drawing overlays
for a Snapchat "Download My Data" export, and writes a clean library of
properly-tagged photos and videos (readable by Apple Photos, Google Photos,
Finder, etc.).

## Why

Snapchat's export splits your memories into `memories_history.json`
(timestamp + GPS + media type, but no filename) and a `memories/` folder of
`YYYY-MM-DD_<uuid>-main.{jpg,mp4}` + `-overlay.png` files (filename only
carries the date, not the time or GPS). This tool re-links the two by
grouping both lists by date and pairing them up in order, then writes the
recovered metadata into the output files and optionally merges each overlay
back onto its photo/video.

Handles the messy real-world export shape: one zip containing several nested
zips (`mydata~...-1.zip`, `-2.zip`, ...) for accounts over Snapchat's 5GB
single-download limit, sometimes with a whole chunk duplicated (seen in the
wild: an already-extracted folder *and* its zip, byte-identical). Files are
matched and deduplicated by ID first, then read directly out of the zips one
nested archive at a time, so it never needs to hold the full export
uncompressed on disk at once.

## Download

Grab the latest build from the [Releases page](../../releases):

- **macOS Apple Silicon (M1-M4)** → `Snapchat-Memories-Fixer-macos-arm64.zip`
- **macOS Intel** → `Snapchat-Memories-Fixer-macos-intel.zip`
- **Windows** → `Snapchat-Memories-Fixer-windows.exe`

`ffmpeg` is required for video processing but isn't bundled — install it
separately: `brew install ffmpeg` (macOS) or `winget install ffmpeg`
(Windows). Photos still work without it; the app warns on launch if it's
missing.

The app isn't signed (no paid developer account), so on first launch:
- **macOS**: right-click → *Open* (instead of double-click) to get past
  Gatekeeper.
- **Windows**: SmartScreen will complain → *More info* → *Run anyway*.

## Setup (from source)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg  # if not already installed
```

## Usage

### GUI

```bash
python app.py
```

Pick the export (zip or extracted primary folder) and a destination, then
"Corriger mes souvenirs". Check the estimated size vs. free disk space shown
under the options before running a full export; tick "échantillon de test"
to try it on a handful of files first.

### CLI

Test on a small sample first (recommended before running on a large export):

```bash
python app.py --source ~/Downloads/download.zip --output ~/Downloads/snap_fixed_sample --limit 50
```

Then check the result (dates, GPS in Photos' info panel, overlay rendering)
before running the full export:

```bash
python app.py --source ~/Downloads/download.zip --output ~/Downloads/snap_fixed
```

Options:
- `--limit N` — only process the first N media items (fast sanity check)
- `--no-overlay` — skip merging `-overlay.png` onto `-main` files
- `--dry-run` — print what would be written without touching any files

## How it works

Two passes, because the JSON has no filename to key off of:

1. **List** every `-main.*` file across the whole export (zip directory
   listings only — no extraction) to compute the full match against
   `memories_history.json`: group both lists by date, pair them up in order
   within each (date, photo/video) group. This needs every file's date
   visible at once, which a multi-GB export can't do file-by-file.
2. **Stream**: extract one nested zip at a time, immediately write each
   file's recovered metadata (and merge its overlay, if any) using the match
   from pass 1, then discard that zip's extracted copy before moving to the
   next — so peak extra disk use stays around one nested zip's size, not the
   whole export.

## Accuracy notes

- Exact time-of-day and GPS come from correlating `memories_history.json`
  entries to files by (date, order within that date, media type). This
  matches how the export was generated but isn't a guaranteed 1:1 file ID
  match — Snapchat's JSON doesn't include one. The tool reports how many
  items fell back to date-only (no time/GPS) after each run.
- It's normal for the JSON to have more entries than files — some memories
  are logged but were never actually included in the export (a known
  Snapchat limitation, usually deleted/expired content). Extra files beyond
  a date's JSON entries fall back to date-only.
- Video metadata is written with `-codec copy` (no re-encoding, so no
  quality loss) unless an overlay is merged, in which case the video stream
  is re-encoded to burn the overlay in (dimensions are padded to even
  numbers first — some Snapchat videos have odd pixel dimensions, which
  libx264 otherwise refuses to encode).

## Building a standalone executable

```bash
pip install pyinstaller
pyinstaller snapfixer.spec --noconfirm
```

Official builds (macOS arm64/Intel + Windows) are produced automatically by
[GitHub Actions](.github/workflows/build.yml) on every `vX.Y.Z` tag.

## Licence

Apache 2.0 — see [LICENSE](LICENSE).
