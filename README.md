# AudioSync

AudioSync is a Python CLI application for downloading audio from supported platforms using `yt-dlp`.

Unlike a regular downloader, AudioSync keeps track of downloaded tracks, resumes interrupted sessions, synchronizes playlists and automatically processes metadata.

## Features

- Download single tracks
- Download entire playlists
- Resume interrupted downloads
- Skip already downloaded tracks
- Playlist synchronization
- Download history (archive)
- Automatic metadata fixing
- Album cover processing
- Multiple audio formats
- Cookie support for age-restricted content
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

- Python 3.12+
- FFmpeg

## Installation

Clone the repository:

```bash
git clone https://github.com/Helvior/audio-sync.git
cd audio-sync
```

Create virtual environment:

### Windows

```powershell
python -m venv .venv
```

Activate it:

```powershell
.venv\Scripts\activate
```

### Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run:

```bash
python main.py
```

## Python Dependencies

```
yt-dlp
Pillow
mutagen
rich
```

or

```bash
pip install yt-dlp Pillow mutagen rich
```

## FFmpeg

Download FFmpeg and place `ffmpeg.exe` next to the executable (or ensure it is available in your system PATH).

## License

MIT License