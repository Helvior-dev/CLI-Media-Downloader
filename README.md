# CLI-Media-Downloader

A command-line tool for downloading audio and video with `yt-dlp` and FFmpeg.

## Overview

The tool keeps a local download archive and session history, embeds metadata where supported, and can resume interrupted sessions. Playlist cleanup asks for confirmation before removing tracks with recorded IDs that are no longer in the playlist. Files without an ID record are left alone.

## Features

### Audio
- Formats: FLAC, ALAC, WAV, AIFF, MP3 (320/192/128 kbps), AAC (256 kbps), Opus and OGG Vorbis.
- Embeds metadata and artwork where supported.
- Tracks playlist downloads and asks before deleting identified tracks removed from a playlist.
- Checks titles for possible duplicates before downloading.

### Video
- Containers: MP4, MKV and WEBM; codec and resolution options depend on the source.
- Optional subtitles and metadata where available.
- Keeps a temporary backup when adding metadata to MKV files.

### Settings
- Optional download speed limit and Windows desktop notifications.
- Recently used folders and logs for failed downloads.

## Requirements

- Python 3.12 or newer
- FFmpeg (`ffmpeg.exe` in the project root, or `ffmpeg` on `PATH`)

## Quick Start

1. Clone the repository:
   ```bash
   git clone https://github.com/Helvior-dev/CLI-Media-Downloader.git
   cd CLI-Media-Downloader
   ```

2. Create and activate a virtual environment (Windows PowerShell):
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Launch the application:
   ```bash
   python main.py
   ```

## Building a Standalone `.exe`

To build a Windows executable, place `ffmpeg.exe` in the project root if you want it bundled, then run:

```powershell
python build_exe.py
```

The output is `dist/LogovoDushnil/LogovoDushnil.exe`. The build script uses `media/icon.ico` if present and bundles `ffmpeg.exe` only if it is in the project root. The FFmpeg binary is not included in this repository.

## Configuration & Logs

- When running from source, settings and session logs are saved in `./data/`.
- When running the compiled `.exe`, data is saved in `%APPDATA%\LogovoDushnil\`.

## License

[MIT](LICENSE)
