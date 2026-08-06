# AudioSync — Logovo Dushnil YTMusic Downloader

AudioSync is a Python CLI application for downloading audio from supported
platforms using `yt-dlp`.

Unlike a regular downloader, AudioSync keeps track of downloaded tracks,
resumes interrupted sessions, synchronizes playlists, remembers where you've
downloaded before, and automatically processes metadata and cover art.

## Features

- Download single tracks or entire playlists
- Resume interrupted downloads (safe Ctrl+C, picks up where it left off)
- Skip already downloaded tracks (per-folder download archive)
- Playlist synchronization — detects tracks removed from the source playlist
  and offers to delete the corresponding local files
- Fuzzy duplicate detection — flags likely duplicates (e.g. a live or
  remastered version of a track you already have) and asks before downloading
- Recent-folders history — jump back into a playlist folder without retyping
  the path, including a one-step "Quick continue" mode
- Folder stats — check a folder's last sync date, tracks downloaded since
  last time, total tracks, and recent failures without starting a download
- Session log — every session (downloaded/skipped/failed counts and failure
  reasons) is appended to a persistent log, not just shown once in the console
- Estimated time remaining during playlist downloads, based on the actual
  speed of the first few tracks
- Automatic metadata fixing (artist, track number, album) and square-cropped
  embedded cover art
- Multiple audio formats, lossless and lossy
- Human-readable failure reasons (age-restricted, unavailable, removed, etc.)
  shown directly in the console — no need to open a log file
- Rich terminal interface

## Supported Platforms

Any platform supported by `yt-dlp`, including:

- YouTube
- YouTube Music
- SoundCloud
- Bandcamp
- Vimeo
- and many others

## Requirements

- Python 3.12+ (a standard, non-free-threaded build — see note below)
- FFmpeg

> **Note on Python versions:** avoid the free-threaded build of Python (the
> one labeled `3.1Xt`, e.g. `3.14t`). Several packaging tools (like
> `auto-py-to-exe`) can't yet install cleanly on it without a full C++
> compiler toolchain. Use a regular build — `py -3.12`, `py -3.13`, etc.

## Installation

Clone the repository:

```bash
git clone https://github.com/Helvior-dev/audio-sync.git
cd audio-sync
```

Create a virtual environment:

### Windows

```powershell
py -3.12 -m venv venv
venv\Scripts\Activate.ps1
```

### Linux / macOS

```bash
python3 -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run:

```bash
python yt_music_downloader.py
```

## Python Dependencies

```
yt-dlp
Pillow
mutagen
rich
```

## FFmpeg

The app looks for `ffmpeg.exe` in the same folder as the script (or the built
`.exe`). If it's not there, `yt-dlp` will fall back to `ffmpeg` on your system
PATH.

- **Windows:** `winget install --id Gyan.FFmpeg -e`, or download a build and
  place `ffmpeg.exe` next to `yt_music_downloader.py`.
- **macOS:** `brew install ffmpeg`
- **Linux:** `sudo apt install ffmpeg` (or your distro's equivalent)

## Where data is stored

- **Running from source:** a local `data/` folder next to the script
  (`config.json`, `sessions_log.txt`) — kept out of the project root.
- **Running as a built `.exe`:** `%APPDATA%\LogovoDushnil\` on Windows, so it
  works regardless of where the app is installed and doesn't need write
  access to the install folder. Old files sitting next to the script/exe from
  an earlier version are migrated automatically on first run.

Per-playlist files (download archive, failed-track log, playlist order) are
stored inside each playlist's own folder, alongside the downloaded tracks.

## Building a standalone .exe

The app can be packaged into a standalone Windows executable with
[PyInstaller](https://pyinstaller.org/) (directly, or via the
[auto-py-to-exe](https://github.com/brentvollebregt/auto-py-to-exe) GUI).

```powershell
pip install pyinstaller
pyinstaller --noconfirm --onedir --console --icon "media/icon.ico" --add-data "ffmpeg.exe;." yt_music_downloader.py
```

- **One Directory**, not One File — starts faster and triggers far fewer
  antivirus false positives than a self-extracting single-file build.
- **Console Based** — this is a terminal UI (built with `rich`), not a GUI
  app; the console window is required.
- Add `ffmpeg.exe` as an additional file (destination `.`) if you want the
  app to work out of the box on a machine without FFmpeg installed.

The result is a folder (e.g. `dist/yt_music_downloader/`) containing the
`.exe` and all dependencies. Zip the whole folder to share it — it runs on
any Windows machine without installing Python.

## License

MIT License