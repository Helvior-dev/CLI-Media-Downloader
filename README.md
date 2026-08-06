# Logovo-Downloads — Logovo Dushnil Media Suite

**Logovo-Downloads** is a Python CLI application and standalone Media Suite for downloading audio and video from YouTube and other supported platforms using `yt-dlp` and `FFmpeg`.

Unlike basic downloaders, Logovo-Downloads features a unified interactive menu, tracks downloaded files, resumes interrupted sessions, synchronizes playlists, embeds metadata and high-res poster artwork, and hides service files so your media folders stay clean.

---

## 🌟 Key Features

### 🎵 Audio Downloader Module
- **Multiple Audio Formats**: Lossless (FLAC, ALAC, WAV, AIFF) and Lossy (MP3 320/192/128kbps, AAC 256kbps, Opus 160kbps, OGG Vorbis).
- **Embedded Cover Art**: Square-cropped high-res cover art embedded directly into ID3 / MP4 tags.
- **Playlist Sync**: Detects tracks removed from the source playlist and offers cleanup.
- **Fuzzy Duplicate Detection**: Identifies potential duplicate tracks (e.g., live or remastered versions).

### 🎬 Video Downloader Module
- **Video Containers & Codecs**: 
  - Containers: `MP4`, `MKV`, `WEBM`
  - Codecs: `H.264 (AVC)`, `H.265 (HEVC)`, `AV1`, `VP9`
  - Resolutions: `1080p`, `4K`, `720p`, `480p`, `Best available`
- **Subtitles & Closed Captions**: Choice of languages (English, Russian, dual, or all) with options to embed into container (`MKV/MP4`) or save as external `.srt` files.
- **Poster Artwork Embedding**: Injects high-definition video thumbnails into video tags (`covr` atom for MP4).
- **Safe Metadata Remuxing**: Creates a temporary `.bak` backup before `FFmpeg` processing and restores original files automatically if any remuxing error occurs.

### ⚙️ Suite & System Features
- **Clean Folder Protection**: All service files (`downloaded_archive.txt`, `failed_downloads.txt`, `session_progress.json`, `playlist_order.txt`) are automatically hidden using OS file attributes (`hidden_path`).
- **Windows Desktop Notifications**: Native Windows balloon popups notify you when download sessions finish (can be toggled in Settings).
- **Bandwidth & Speed Limiter**: Restrict download speed (e.g., `5 MB/s`, `10 MB/s`, `20 MB/s`) so downloads won't saturate your internet connection.
- **Recent Folders History**: Jump back into a playlist folder instantly without retyping paths.
- **Human-Readable Error Logging**: Converts raw stack traces into friendly descriptions (*Age-restricted*, *Bot check*, *Copyright claim*, *Region lock*, etc.) and offers 1-click retries (`_retry_failed`).
- **Rich Terminal UI**: Live progress bars displaying completion percentage, transfer speed (`MB/s`), and estimated time remaining (`ETA`).

---

## 🛠 Supported Platforms

Any platform supported by `yt-dlp`, including:
- YouTube / YouTube Music
- SoundCloud
- Bandcamp
- Vimeo
- and many others

---

## 📋 Requirements

- **Python 3.12+** (standard non-free-threaded build)
- **FFmpeg** (`ffmpeg.exe`)

> **FFmpeg setup:** The application looks for `ffmpeg.exe` in the project root directory (or alongside the built `.exe`). If missing, it falls back to system `PATH`.

---

## 🚀 Installation & Running

### 1. Clone the repository
```bash
git clone https://github.com/Helvior-dev/Logovo-Downloads.git
cd Logovo-Downloads
```

### 2. Create a virtual environment
#### Windows (PowerShell):
```powershell
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
```

#### Linux / macOS:
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the Media Suite
```bash
python main.py
```

---

## 📦 Building Standalone Executable (.exe)

You can package the application into a standalone Windows executable using PyInstaller.

Run the built-in build script:
```powershell
python build_exe.py
```

The compiled standalone executable will be created in:
`dist/LogovoDushnil/LogovoDushnil.exe`

- Bundles `ffmpeg.exe` and `media/icon.ico`.
- Runs on any Windows machine without requiring Python.

---

## 📁 Data Storage & Configuration

- **Running from Source**: Configuration (`config.json`) and session logs (`sessions_log.txt`) are stored in `data/`.
- **Running as Built `.exe`**: Data is stored centrally in `%APPDATA%\LogovoDushnil\`.
- **Per-Playlist Files**: Archive files and failure logs inside download folders are automatically hidden.

---

## 📄 License

MIT License