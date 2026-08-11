# CLI-Media-Downloader

A lightweight terminal media downloader built with Python, `yt-dlp`, and `FFmpeg`.

> **Note:** This is a fan-made hobby project built with the assistance of AI (Google Antigravity / Claude) to create a clean, all-in-one downloader for personal music and video collections.

---

## Overview

CLI-Media-Downloader is a CLI tool designed to download audio tracks and videos without cluttering your folders. It keeps track of what you've already downloaded, hides service files from your file manager, embeds artwork and metadata, and handles interrupted sessions gracefully.

---

## Features

### 🎵 Audio Downloader
- **Formats**: FLAC, ALAC, WAV, AIFF, MP3 (320/192/128 kbps), AAC (256 kbps), Opus, and OGG Vorbis.
- **Metadata & Covers**: Automatically crops and embeds cover art directly into ID3/M4A tags.
- **Playlist Sync**: Detects tracks removed from YouTube playlists and offers to clean up local copies.
- **Fuzzy Duplicate Check**: Flags potential duplicate tracks (remasters, live versions) before downloading.

### 🎬 Video Downloader
- **Containers & Codecs**: MP4, MKV, WEBM with support for H.264, H.265, AV1, and VP9.
- **Resolutions**: 4K, 1080p, 720p, 480p, or best available.
- **Subtitles**: Download embedded or external `.srt` subtitles in English, Russian, dual, or all languages.
- **Posters**: Embeds high-res video thumbnails into the file tags.
- **Safe Remuxing**: Creates temporary `.bak` backups before modifying files with FFmpeg, preventing corrupted outputs.

### ⚙️ Utilities & Settings
- **Clean Folders**: Keeps download folders free of service text files by applying OS-level hidden attributes (`SetFileAttributesW` on Windows).
- **Speed Limiter**: Restrict download speeds (5 MB/s, 10 MB/s, custom) to prevent network congestion.
- **Desktop Notifications**: Windows notifications when long download sessions complete.
- **Folder History**: Quickly resume downloads in previously used folders.
- **Error Handling**: Converts raw `yt-dlp` logs into human-readable error reasons and offers one-click retries.

---

## Requirements

- Python 3.12 or newer
- FFmpeg (`ffmpeg.exe` placed in the project root directory, or installed on system PATH)

---

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

---

## Building a Standalone `.exe`

To compile the application into a standalone folder containing `LogovoDushnil.exe`:

```powershell
python build_exe.py
```

The output executable will be generated at `dist/LogovoDushnil/LogovoDushnil.exe` bundled with `ffmpeg.exe` and `media/icon.ico`.

---

## Configuration & Logs

- When running from source, settings and session logs are saved in `./data/`.
- When running the compiled `.exe`, data is saved in `%APPDATA%\LogovoDushnil\`.

---

## License

[MIT](LICENSE)