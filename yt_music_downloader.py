import ctypes
import difflib
import io
import json
import os
import re
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import yt_dlp
from PIL import Image
from mutagen.flac import FLAC
from mutagen.id3 import APIC, ID3, TPE1, TRCK, TALB
from mutagen.mp4 import MP4
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table

# ─── Constants ────────────────────────────────────────────────────────────────

console = Console()
DOWNLOADS_PATH = Path.home() / "Downloads"
FORBIDDEN_CHARS = r'\/:*?"<>|'

# Human-readable error reason mapping
ERROR_REASONS: list[tuple[str, str]] = [
    ("Sign in to confirm your age",  "Age-restricted — cookies required"),
    ("Video unavailable",            "Video unavailable"),
    ("copyright claim",              "Blocked by copyright claim"),
    ("This video is not available",  "Video not available in your region"),
    ("Private video",                "Private video"),
    ("This video has been removed",  "Video removed by uploader"),
    ("confirm you're not a bot",     "Bot check — try adding cookies"),
]


def friendly_error(raw: str) -> str:
    """Return short human-readable reason from raw yt-dlp error string."""
    for needle, label in ERROR_REASONS:
        if needle.lower() in raw.lower():
            return label
    clean = re.sub(r"\x1b\[[0-9;]*m", "", raw).strip()
    first = re.split(r"[\n.]", clean)[0].strip()
    return first[:120] if first else raw[:120]


# ─── Audio format definitions ─────────────────────────────────────────────────

AUDIO_FORMATS = {
    "1":  {"codec": "flac",   "quality": None,  "ext": "flac", "label": "FLAC",          "note": "lossless · ~40-50 MB/track",               "mb_per_track": 45},
    "2":  {"codec": "alac",   "quality": None,  "ext": "m4a",  "label": "ALAC",          "note": "lossless · Apple format · ~40-50 MB/track", "mb_per_track": 45},
    "3":  {"codec": "wav",    "quality": None,  "ext": "wav",  "label": "WAV",           "note": "lossless · uncompressed · ~150 MB/track",   "mb_per_track": 150},
    "4":  {"codec": "aiff",   "quality": None,  "ext": "aiff", "label": "AIFF",          "note": "lossless · Apple WAV · ~150 MB/track",      "mb_per_track": 150},
    "5":  {"codec": "mp3",    "quality": "320", "ext": "mp3",  "label": "MP3 320kbps",   "note": "lossy · widest compatibility · ~8 MB/track", "mb_per_track": 8},
    "6":  {"codec": "mp3",    "quality": "192", "ext": "mp3",  "label": "MP3 192kbps",   "note": "lossy · good quality · ~5 MB/track",        "mb_per_track": 5},
    "7":  {"codec": "mp3",    "quality": "128", "ext": "mp3",  "label": "MP3 128kbps",   "note": "lossy · compact · ~3 MB/track",             "mb_per_track": 3},
    "8":  {"codec": "aac",    "quality": "256", "ext": "m4a",  "label": "AAC 256kbps",   "note": "lossy · Apple/streaming · ~6 MB/track",     "mb_per_track": 6},
    "9":  {"codec": "opus",   "quality": "160", "ext": "opus", "label": "Opus 160kbps",  "note": "lossy · best efficiency · ~4 MB/track",     "mb_per_track": 4},
    "10": {"codec": "vorbis", "quality": "5",   "ext": "ogg",  "label": "OGG Vorbis q5", "note": "lossy · open format · ~4 MB/track",         "mb_per_track": 4},
}

# ─── Config ───────────────────────────────────────────────────────────────────

APP_NAME = "LogovoDushnil"


def get_app_data_dir() -> Path:
    """
    Where config.json / sessions_log.txt live.
    - Frozen (exe, built with PyInstaller/auto-py-to-exe): %APPDATA%\\LogovoDushnil
      so it works regardless of where the exe is installed, doesn't need write
      access to the install folder, and survives reinstalls/updates.
    - Running from source (development): a local "data" folder next to the
      script, kept out of the project root.
    One-time migration: if this is the first run in the new location and the
    old files (config.json / sessions_log.txt sitting next to the script/exe
    from earlier versions) exist, move them in rather than starting fresh.
    """
    if getattr(sys, "frozen", False):
        base = Path(os.getenv("APPDATA") or Path.home())
        target = base / APP_NAME
    else:
        target = Path(__file__).parent / "data"
    target.mkdir(parents=True, exist_ok=True)

    old_base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    for name in ("config.json", "sessions_log.txt"):
        old_file, new_file = old_base / name, target / name
        if old_file.exists() and not new_file.exists():
            try:
                new_file.write_text(old_file.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception:
                pass
    return target


APP_DATA_DIR = get_app_data_dir()
CONFIG_PATH = APP_DATA_DIR / "config.json"
SESSIONS_LOG_PATH = APP_DATA_DIR / "sessions_log.txt"
MAX_RECENT_FOLDERS = 10

DEFAULT_CONFIG: dict = {
    "default_format":  None,  # key from AUDIO_FORMATS
    "default_output":  None,  # default output folder
    "recent_folders":  [],    # list of {"path": str, "title": str, "last_used": iso-str}
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return {**DEFAULT_CONFIG, **data}
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def remember_folder(cfg: dict, path: Path, title: str) -> None:
    """Add/update a folder in the recent-folders list (most recent first, capped at MAX_RECENT_FOLDERS)."""
    entries = [e for e in cfg.get("recent_folders", []) if e.get("path") != str(path)]
    entries.insert(0, {"path": str(path), "title": title, "last_used": datetime.now().isoformat(timespec="seconds")})
    cfg["recent_folders"] = entries[:MAX_RECENT_FOLDERS]
    save_config(cfg)


def format_recent_date(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%d %b %Y, %H:%M")
    except Exception:
        return iso_str


def parse_folder_sessions(folder: Path, limit: int = 5) -> list[dict]:
    """
    Parse sessions_log.txt and return up to `limit` most recent session records
    for the given folder (most recent first). Each record: timestamp, downloaded,
    skipped, failed count, and list of (header, reason) failed tracks.
    """
    if not SESSIONS_LOG_PATH.exists():
        return []
    target = str(folder)
    blocks = SESSIONS_LOG_PATH.read_text(encoding="utf-8").split("\n\n")
    records: list[dict] = []
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        header_match = re.match(r"\[(.+?)\]", lines[0])
        if not header_match:
            continue
        folder_line = next((ln for ln in lines if ln.strip().startswith("Folder:")), "")
        if folder_line.split("Folder:", 1)[-1].strip() != target:
            continue
        rec = {
            "timestamp": header_match.group(1),
            "downloaded": 0, "skipped": 0, "failed": 0,
            "failed_tracks": [],
        }
        for ln in lines[1:]:
            s = ln.strip()
            if s.startswith("Downloaded:"):
                rec["downloaded"] = int(re.search(r"\d+", s).group())
            elif s.startswith("Skipped:"):
                rec["skipped"] = int(re.search(r"\d+", s).group())
            elif s.startswith("Failed:"):
                rec["failed"] = int(re.search(r"\d+", s).group())
            elif s.startswith("✘"):
                rest = s[1:].strip()
                if " :: " in rest:
                    h, r = rest.split(" :: ", 1)
                    rec["failed_tracks"].append((h.strip(), r.strip()))
        records.append(rec)
    records.sort(key=lambda r: r["timestamp"], reverse=True)
    return records[:limit]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def get_ffmpeg_path() -> str | None:
    ffmpeg = get_base_dir() / "ffmpeg.exe"
    return str(ffmpeg) if ffmpeg.exists() else None


FFMPEG_PATH = get_ffmpeg_path()


def sanitize_filename(name: str) -> str:
    for ch in FORBIDDEN_CHARS:
        name = name.replace(ch, "_")
    return name.strip()


def format_size(b: int) -> str:
    if b >= 1024 ** 3:
        return f"{b / 1024 ** 3:.2f} GB"
    if b >= 1024 ** 2:
        return f"{b / 1024 ** 2:.1f} MB"
    return f"{b / 1024:.1f} KB"


def format_size_mb(mb: float) -> str:
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb:.0f} MB"


def format_time(s: float) -> str:
    s = int(s)
    if s >= 3600:
        return f"{s // 3600}h {(s % 3600) // 60}m"
    if s >= 60:
        return f"{s // 60}m {s % 60}s"
    return f"{s}s"


def crop_to_square(img: Image.Image) -> Image.Image:
    w, h = img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    resample = getattr(Image, "Resampling", Image).LANCZOS
    return img.crop((left, top, left + side, top + side)).resize((1000, 1000), resample)


def base_ydl_opts() -> dict:
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True}
    if FFMPEG_PATH:
        opts["ffmpeg_location"] = FFMPEG_PATH
    return opts


def extract_artist(info: dict) -> str:
    for field in ("artist", "creator", "uploader", "channel", "uploader_id"):
        val = (info.get(field) or "").strip()
        if val and val.lower() not in ("unknown", "unknown artist"):
            return val
    return ""


def unhide_file(path: Path) -> None:
    if sys.platform == "win32" and path.exists():
        try:
            ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x80)
        except Exception:
            pass


def hide_file(path: Path) -> None:
    if sys.platform == "win32":
        try:
            ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02)
        except Exception:
            pass


def hidden_path(directory: Path, name: str) -> Path:
    return directory / name if sys.platform == "win32" else directory / f".{name}"


def write_hidden(path: Path, text: str) -> None:
    unhide_file(path)
    path.write_text(text, encoding="utf-8")
    hide_file(path)


# ─── URL inspection ───────────────────────────────────────────────────────────

def inspect_url(url: str) -> dict:
    try:
        with yt_dlp.YoutubeDL(base_ydl_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
            if "entries" not in info:
                return {"single": True, "title": info.get("title") or "Unknown", "count": None, "entries": []}
            entries = list(info.get("entries") or [])
            title = info.get("title") or info.get("playlist_title") or "Playlist"
            return {"single": False, "title": sanitize_filename(title), "count": len(entries), "entries": entries}
    except Exception:
        return {"single": False, "title": "Playlist", "count": None, "entries": []}


# ─── Error logger ─────────────────────────────────────────────────────────────

class ErrorLogger:
    """
    FIX v2.0:
    - current_info is updated on every progress hook call (including first
      'downloading' event), so title/artist are always present in the log.
    - Errors are formatted with friendly_error() for human-readable reasons.
    FIX v2.3:
    - Age-restricted / unavailable errors fire BEFORE the first progress hook
      call, so current_info is still empty at that point. As a fallback, the
      video ID is pulled out of yt-dlp's own error text and matched against
      entries_by_id (built from the playlist's flat listing, which is known
      up front) so title/artist are still resolved correctly.
    """

    def __init__(self, failed_log: Path, entries_by_id: dict[str, dict] | None = None):
        self._log = failed_log
        self.current_info: dict = {}
        self._entries_by_id = entries_by_id or {}

    def debug(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        pass

    def _resolve_from_error_text(self, msg: str) -> dict:
        """Try to find the failing entry's known metadata via the video ID in the error text."""
        clean = re.sub(r"\x1b\[[0-9;]*m", "", msg)
        m = re.search(r"\[youtube\]\s*([A-Za-z0-9_-]{11})", clean)
        if not m:
            m = re.search(r"([A-Za-z0-9_-]{11})", clean)
        vid = m.group(1) if m else ""
        return self._entries_by_id.get(vid, {})

    def error(self, msg: str) -> None:
        if not msg or msg.startswith("WARNING"):
            return
        info = self.current_info
        if not info.get("title"):
            info = self._resolve_from_error_text(msg) or info
        title  = info.get("title")    or "Unknown title"
        artist = extract_artist(info)  or "Unknown artist"
        url    = info.get("webpage_url") or info.get("url") or ""
        reason = friendly_error(msg)
        with open(self._log, "a", encoding="utf-8") as f:
            f.write(f"{artist} — {title}\n")
            if url:
                f.write(f"URL:    {url}\n")
            f.write(f"Reason: {reason}\n\n")


# ─── Post-processing ──────────────────────────────────────────────────────────

def fix_flac_cover(path: Path) -> None:
    audio = FLAC(path)
    pictures = audio.pictures
    if not pictures:
        return
    changed = False
    for pic in pictures:
        img = Image.open(io.BytesIO(pic.data))
        if img.width == img.height:
            continue
        buf = io.BytesIO()
        crop_to_square(img).save(buf, format="JPEG", quality=95)
        pic.data, pic.mime = buf.getvalue(), "image/jpeg"
        pic.width, pic.height, pic.depth = 1000, 1000, 24
        changed = True
    if changed:
        audio.clear_pictures()
        for pic in pictures:
            audio.add_picture(pic)
        audio.save()


def fix_mp3_cover(path: Path) -> None:
    tags = ID3(path)
    apic_keys = [k for k in tags if k.startswith("APIC")]
    if not apic_keys:
        return
    changed = False
    for key in apic_keys:
        apic = tags[key]
        img = Image.open(io.BytesIO(apic.data))
        if img.width == img.height:
            continue
        buf = io.BytesIO()
        crop_to_square(img).save(buf, format="JPEG", quality=95)
        tags[key] = APIC(encoding=apic.encoding, mime="image/jpeg", type=apic.type, desc=apic.desc, data=buf.getvalue())
        changed = True
    if changed:
        tags.save(v2_version=3)


def fix_flac_tags(path: Path, track_num: int | None = None, total_tracks: int | None = None, album: str | None = None) -> None:
    audio  = FLAC(path)
    artist = (
        audio.get("artist",      [""])[0].strip()
        or audio.get("albumartist", [""])[0].strip()
        or audio.get("uploader",    [""])[0].strip()
    )
    if artist:
        audio["artist"] = [artist]
    if track_num is not None:
        audio["tracknumber"] = [f"{track_num}/{total_tracks}" if total_tracks else str(track_num)]
    if album and not audio.get("album", [""])[0].strip():
        audio["album"] = [album]
    audio.save()


def fix_mp3_tags(path: Path, track_num: int | None = None, total_tracks: int | None = None, album: str | None = None) -> None:
    tags   = ID3(path)
    artist = str(tags["TPE1"]).strip() if "TPE1" in tags else ""
    if artist:
        tags["TPE1"] = TPE1(text=[artist])
    if track_num is not None:
        tags["TRCK"] = TRCK(text=[f"{track_num}/{total_tracks}" if total_tracks else str(track_num)])
    if album and not (str(tags["TALB"]).strip() if "TALB" in tags else ""):
        tags["TALB"] = TALB(text=[album])
    tags.save(v2_version=3)


def fix_m4a_tags(path: Path, track_num: int | None = None, total_tracks: int | None = None, album: str | None = None) -> None:
    try:
        audio = MP4(path)
    except Exception:
        return
    if track_num is not None:
        audio["trkn"] = [(track_num, total_tracks or 0)]
    if album and not (audio.get("\xa9alb") or [""])[0]:
        audio["\xa9alb"] = [album]
    audio.save()


def write_playlist_order(output_dir: Path, audio_files: list[Path]) -> None:
    write_hidden(hidden_path(output_dir, "playlist_order.txt"), "\n".join(p.name for p in audio_files))


def restore_dates_from_order(output_dir: Path) -> None:
    order_file = hidden_path(output_dir, "playlist_order.txt")
    if not order_file.exists():
        return
    names = [ln.strip() for ln in order_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not names:
        return
    base_time = time.time()
    restored  = 0
    for i, name in enumerate(names):
        p = output_dir / name
        if p.exists():
            try:
                os.utime(p, (base_time + i, base_time + i))
                restored += 1
            except Exception:
                pass
    if restored:
        console.print(Panel(
            f"[green]Restored file order[/] from [bold]playlist_order.txt[/] — [bold]{restored}[/] track(s) re-stamped.",
            border_style="green", box=box.ROUNDED,
        ))


def postprocess_files(
    output_dir: Path,
    fmt: dict,
    stem_to_index: dict[str, int] | None = None,
    playlist_title: str | None = None,
    total_tracks: int | None = None,
) -> None:
    ext, is_flac, is_mp3, is_m4a = fmt["ext"], fmt["codec"] == "flac", fmt["codec"] == "mp3", fmt["ext"] == "m4a"
    fix_cover = fix_flac_cover if is_flac else (fix_mp3_cover if is_mp3 else None)
    all_files = list(output_dir.rglob(f"*.{ext}"))
    if not all_files:
        return
    if stem_to_index:
        audio_files = sorted(all_files, key=lambda p: (stem_to_index.get(p.stem, 10**9), p.stat().st_ctime))
    else:
        audio_files = sorted(all_files, key=lambda p: p.stat().st_ctime)
    if fix_cover:
        with console.status("[bold cyan]Fixing covers...[/]", spinner="dots"):
            for path in audio_files:
                try:
                    fix_cover(path)
                except Exception:
                    pass
    with console.status("[bold cyan]Writing tags...[/]", spinner="dots"):
        for path in audio_files:
            yt_idx = stem_to_index.get(path.stem) if stem_to_index else None
            tnum   = (total_tracks - yt_idx + 1) if (yt_idx is not None and total_tracks) else yt_idx
            try:
                if is_flac:  fix_flac_tags(path, tnum, total_tracks, playlist_title)
                elif is_mp3: fix_mp3_tags(path, tnum, total_tracks, playlist_title)
                elif is_m4a: fix_m4a_tags(path, tnum, total_tracks, playlist_title)
            except Exception:
                pass
    if len(audio_files) > 1:
        base = time.time()
        for i, path in enumerate(audio_files):
            try:
                os.utime(path, (base + i, base + i))
            except Exception:
                pass
    write_playlist_order(output_dir, audio_files)


# ─── Sync ─────────────────────────────────────────────────────────────────────

def _read_archive_ids(archive_path: Path) -> set[str]:
    ids: set[str] = set()
    if not archive_path.exists():
        return ids
    for line in archive_path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            ids.add(parts[1])
    return ids


def _extract_entry_id(entry: dict) -> str:
    vid = entry.get("id") or entry.get("url") or ""
    return vid.split("v=")[-1].split("&")[0].strip()


def _normalize_title(title: str) -> str:
    """Strip common noise (remaster tags, years, brackets) so fuzzy matching compares the core title."""
    t = title.lower()
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", t)                  # drop bracketed content
    t = re.sub(r"\b(remaster(ed)?|live|acoustic|mono|stereo|version|edit|remix|explicit|clean|\d{4})\b", " ", t)
    t = re.sub(r"[^\w\s]", " ", t)                          # drop punctuation
    return re.sub(r"\s+", " ", t).strip()


def check_title_duplicates(output_dir: Path, ext: str, playlist_entries: list) -> None:
    """
    For playlist entries not yet in the archive, fuzzy-match their title against
    already-downloaded files in the folder. On a likely duplicate (e.g. a live/remaster
    version of a track already present), ask the user whether to download it anyway
    or skip it (skipping adds its ID to the archive so yt-dlp won't fetch it).
    """
    if not playlist_entries:
        return
    archive_path = hidden_path(output_dir, "downloaded_archive.txt")
    archived_ids = _read_archive_ids(archive_path)
    existing_titles = [(_normalize_title(f.stem), f.stem) for f in output_dir.glob(f"*.{ext}")]
    if not existing_titles:
        return
    to_skip: list[str] = []
    for entry in playlist_entries:
        if not entry:
            continue
        vid = _extract_entry_id(entry)
        if not vid or vid in archived_ids:
            continue
        title = entry.get("title") or ""
        if not title:
            continue
        norm = _normalize_title(title)
        if not norm:
            continue
        best_ratio, best_match = 0.0, ""
        for existing_norm, existing_name in existing_titles:
            ratio = difflib.SequenceMatcher(None, norm, existing_norm).ratio()
            if ratio > best_ratio:
                best_ratio, best_match = ratio, existing_name
        if best_ratio >= 0.8:
            console.print(Panel(
                f"[white]New:[/]      {title}\n"
                f"[white]Existing:[/] {best_match}\n"
                f"[dim]Similarity: {best_ratio:.0%}[/]",
                title="[yellow]Possible duplicate[/]", border_style="yellow", box=box.ROUNDED,
            ))
            if not Confirm.ask("[bold cyan]  Download it anyway?[/]", default=False):
                to_skip.append(vid)
                console.print("[dim]  Skipped.[/]\n")
            else:
                console.print()
    if to_skip:
        try:
            unhide_file(archive_path)
            with open(archive_path, "a", encoding="utf-8") as f:
                for vid in to_skip:
                    f.write(f"youtube {vid}\n")
            hide_file(archive_path)
        except Exception:
            pass


def _parse_failed_reasons(failed_log: Path) -> dict[str, str]:
    """Parse failed_downloads.txt into {title: reason} for cross-referencing during sync."""
    reasons: dict[str, str] = {}
    if not failed_log.exists():
        return reasons
    for block in failed_log.read_text(encoding="utf-8").strip().split("\n\n"):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        header = lines[0]
        reason_line = next((ln for ln in lines if ln.startswith("Reason:")), None)
        if reason_line:
            reasons[header.strip()] = reason_line[len("Reason:"):].strip()
    return reasons


def sync_remove_deleted(output_dir: Path, ext: str, playlist_entries: list, stem_to_index: dict[str, int]) -> None:
    if not playlist_entries:
        return
    playlist_ids = {_extract_entry_id(e) for e in playlist_entries if e} - {""}
    orphan_ids   = _read_archive_ids(hidden_path(output_dir, "downloaded_archive.txt")) - playlist_ids
    if not orphan_ids:
        return
    known_stems  = set(stem_to_index.keys())
    orphan_files = [f for f in output_dir.glob(f"*.{ext}") if f.stem not in known_stems]
    if not orphan_files:
        return
    failed_reasons = _parse_failed_reasons(output_dir / "failed_downloads.txt")
    console.print()
    console.print(Panel(
        f"[yellow]{len(orphan_files)} file(s) no longer in the playlist[/] "
        "[dim](removed from the playlist, or unavailable on YouTube):[/]",
        border_style="yellow", box=box.ROUNDED,
    ))
    for f in orphan_files:
        reason = None
        for header, r in failed_reasons.items():
            if f.stem.startswith(header.split(" — ")[-1]) or header.split(" — ")[-1] in f.stem:
                reason = r
                break
        if reason:
            console.print(f"  [dim]• {f.name}[/]  [red]({reason})[/]")
        else:
            console.print(f"  [dim]• {f.name}[/]  [dim](no longer present in playlist — likely removed manually)[/]")
    if Confirm.ask("\n[bold cyan]  Delete these files?[/]", default=False):
        for f in orphan_files:
            try:
                f.unlink()
                console.print(f"  [red]✘[/] Deleted: [dim]{f.name}[/]")
            except Exception as e:
                console.print(f"  [red]Error:[/] {e}")
    else:
        console.print("[dim]  Skipped.[/]")


# ─── Retry failed ─────────────────────────────────────────────────────────────

def parse_failed_urls(failed_log: Path) -> list[str]:
    if not failed_log.exists():
        return []
    return [
        line[4:].strip()
        for line in failed_log.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("URL:") and line[4:].strip()
    ]


# ─── Downloader ───────────────────────────────────────────────────────────────

class Downloader:
    def __init__(
        self,
        output_dir: Path,
        fmt: dict,
        cfg: dict,
        single: bool = False,
        total_tracks: int | None = None,
        playlist_title: str | None = None,
        playlist_entries: list | None = None,
        is_continuation: bool = False,
    ):
        self.output_dir       = output_dir
        self.fmt              = fmt
        self.cfg              = cfg
        self.single           = single
        self.total_tracks     = total_tracks
        self.playlist_title   = playlist_title
        self.playlist_entries = playlist_entries or []
        self.is_continuation  = is_continuation
        self.new_count        = 0
        self.skipped_count    = 0
        self.failed_count     = 0
        self.last_title: str  = ""
        self._abort           = False
        self._progress: Progress | None = None
        self._task_id         = None
        self._current_track   = 0
        self._track_durations: list[float] = []
        self._current_track_start: float | None = None
        self._current_track_name: str = ""
        self._stem_to_index: dict[str, int] = {}
        self._stem_to_vid:   dict[str, str] = {}
        self._download_order: list[str]     = []
        self._failed_log   = output_dir / "failed_downloads.txt"
        self._session_file = hidden_path(output_dir, "session_progress.json")
        self._vid_map_file = hidden_path(output_dir, "stem_vid_map.json")
        entries_by_id = {
            _extract_entry_id(e): e for e in self.playlist_entries if e and _extract_entry_id(e)
        }
        self._error_logger = ErrorLogger(self._failed_log, entries_by_id)
        signal.signal(signal.SIGINT,  self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    # ── Signal ────────────────────────────────────────────────────────────────

    def _handle_signal(self, signum, frame) -> None:
        if self._abort:
            console.print("\n[bold red]Force exit.[/]")
            sys.exit(1)
        self._abort = True
        console.print("\n[bold yellow]Stopping after current track... (Ctrl+C again to force quit)[/]")

    # ── Session ───────────────────────────────────────────────────────────────

    def _load_session(self) -> dict:
        if self._session_file.exists():
            try:
                data = json.loads(self._session_file.read_text(encoding="utf-8"))
                return {
                    "downloaded":    data.get("downloaded", []),
                    "stem_to_index": data.get("stem_to_index", {}),
                    "stem_to_vid":   data.get("stem_to_vid", {}),
                }
            except Exception:
                pass
        return {"downloaded": [], "stem_to_index": {}, "stem_to_vid": {}}

    def _save_session(self) -> None:
        try:
            write_hidden(self._session_file, json.dumps(
                {"downloaded": self._download_order, "stem_to_index": self._stem_to_index, "stem_to_vid": self._stem_to_vid},
                ensure_ascii=False, indent=2,
            ))
        except Exception:
            pass

    def _clear_session(self) -> None:
        if self._session_file.exists():
            try:
                unhide_file(self._session_file)
                self._session_file.unlink()
            except Exception:
                pass

    # ── Playlist ID map ───────────────────────────────────────────────────────

    def _build_full_stem_index(self) -> None:
        self._playlist_id_to_index: dict[str, int] = {}
        for entry in self.playlist_entries:
            if not entry:
                continue
            vid = _extract_entry_id(entry)
            idx = entry.get("playlist_index") or entry.get("index")
            if vid and idx is not None:
                self._playlist_id_to_index[vid] = int(idx)

    def _reconcile_full_stem_index(self) -> None:
        playlist_ids  = {_extract_entry_id(e) for e in self.playlist_entries if e} - {""}
        ext           = self.fmt["ext"]
        unknown_stems = {f.stem for f in self.output_dir.glob(f"*.{ext}")} - set(self._stem_to_index.keys())
        full_map      = self._load_vid_map()
        full_map.update(self._stem_to_vid)
        self._save_vid_map(full_map)
        self._stem_to_vid = full_map
        orphans, safe, unknown = [], [], []
        for stem in unknown_stems:
            vid = full_map.get(stem)
            if not vid:               unknown.append(stem)
            elif vid in playlist_ids: safe.append(stem)
            else:                     orphans.append(stem)
        for stem in safe:
            self._stem_to_index[stem] = 0
        if unknown:
            archived_ids    = _read_archive_ids(hidden_path(self.output_dir, "downloaded_archive.txt"))
            orphan_id_count = len(archived_ids - playlist_ids)
            if orphan_id_count == 0 or len(unknown) > orphan_id_count - len(orphans):
                for stem in unknown:
                    self._stem_to_index[stem] = 0
                if orphan_id_count > 0:
                    console.print(Panel(
                        f"[yellow]Note:[/] {orphan_id_count} removed from playlist, but {len(unknown)} local files have no ID record.\n"
                        "Please review the folder manually.",
                        border_style="yellow", box=box.ROUNDED,
                    ))

    # ── Progress hook ─────────────────────────────────────────────────────────

    def _track_label(self, name: str) -> str:
        if self.single or self.total_tracks is None:
            return name
        return f"[{self._current_track}/{self.total_tracks}] {name}"

    def _eta_suffix(self) -> str:
        """Estimated time remaining, based on the average duration of completed tracks so far."""
        if self.single or not self.total_tracks or not self._track_durations:
            return ""
        remaining = max(self.total_tracks - self._current_track, 0)
        if remaining == 0:
            return ""
        avg = sum(self._track_durations) / len(self._track_durations)
        return f"  [dim]· ~{format_time(avg * remaining)} left[/]"

    def _on_progress(self, d: dict) -> None:
        status = d["status"]

        # FIX v2.0: update current_info on EVERY hook call so ErrorLogger has fresh data
        # even when the track fails before/during the first download chunk.
        if info := d.get("info_dict"):
            self._error_logger.current_info = info

        if status == "downloading":
            try:
                pct = float(d.get("_percent_str", "0").replace("%", "").strip())
            except ValueError:
                pct = 0.0
            name = Path(d.get("filename", "")).stem[:45]
            if name != self._current_track_name:
                self._current_track_name  = name
                self._current_track_start = time.time()
            if self._progress and self._task_id is not None:
                label = f"[cyan]{self._track_label(name)}[/]{self._eta_suffix()}"
                self._progress.update(self._task_id, completed=pct, description=label)

        elif status == "finished":
            self._current_track += 1
            self.new_count += 1
            if self._current_track_start is not None:
                # Only track real download durations (skip near-zero, likely from a cache hit).
                dur = time.time() - self._current_track_start
                if dur > 0.5 and len(self._track_durations) < 5:
                    self._track_durations.append(dur)
            self._current_track_start = None
            info = d.get("info_dict") or {}
            self.last_title = info.get("title") or Path(d.get("filename", "")).stem
            stem = Path(d.get("filename", "")).stem
            if stem:
                self._download_order.append(stem)
                self._stem_to_index[stem] = info.get("playlist_index") or self._current_track
                vid = info.get("id") or info.get("webpage_url_basename") or ""
                if vid:
                    self._stem_to_vid[stem] = vid
                    m = self._load_vid_map(); m[stem] = vid; self._save_vid_map(m)
            self._save_session()
            if self._progress and self._task_id is not None:
                self._progress.update(self._task_id, completed=0)
            console.print(f"  [bold green]✔[/] [white]{self.last_title}[/] [dim]- converting...[/]")

        elif status == "already_downloaded":
            self._current_track += 1
            self.skipped_count += 1
            console.print("  [dim]Skipped (already in archive)[/]")

        elif status == "error":
            self.failed_count += 1
            console.print("  [bold red]✘[/] [dim]Failed - see failed_downloads.txt[/]")

        if self._abort and status in ("finished", "already_downloaded"):
            raise yt_dlp.utils.DownloadCancelled("Safe exit")

    # ── yt-dlp options ────────────────────────────────────────────────────────

    def _build_ydl_opts(self, single_override: bool | None = None) -> dict:
        codec, quality = self.fmt["codec"], self.fmt["quality"]
        post_audio: dict = {"key": "FFmpegExtractAudio", "preferredcodec": codec}
        if quality is not None:
            post_audio["preferredquality"] = quality
        archive_path = hidden_path(self.output_dir, "downloaded_archive.txt")
        is_single    = single_override if single_override is not None else self.single
        opts: dict = {
            "format":            "bestaudio/best",
            "outtmpl":           str(self.output_dir / "%(title)s - %(artist,uploader,creator,channel)s.%(ext)s"),
            "writethumbnail":    True,
            "convertthumbnails": "jpg",
            "addmetadata":       True,
            "embedthumbnail":    True,
            "postprocessors":    [post_audio, {"key": "FFmpegMetadata"}, {"key": "EmbedThumbnail"}],
            "parse_metadata":    ["%(artist,uploader,creator,channel)s:%(meta_artist)s"],
            "progress_hooks":    [self._on_progress],
            "logger":            self._error_logger,
            "ignoreerrors":      True,
            "noplaylist":        is_single,
            "no_warnings":       True,
            "quiet":             True,
            "retries":           15,
            "fragment_retries":  15,
            "retry_sleep_functions": {"http": lambda n: min(4 * 2 ** n, 60)},
            "socket_timeout":    30,
        }
        if not is_single:
            opts["download_archive"] = str(archive_path)
        if FFMPEG_PATH:
            opts["ffmpeg_location"] = FFMPEG_PATH
        return opts

    # ── Archive / session status ──────────────────────────────────────────────

    def _print_archive_status(self) -> None:
        archive = hidden_path(self.output_dir, "downloaded_archive.txt")
        session = self._load_session()
        lines: list[str] = []
        if archive.exists():
            count = sum(1 for l in archive.read_text(encoding="utf-8").splitlines() if l.strip())
            lines.append(f"[green]Archive:[/] [bold]{count}[/] tracks already downloaded - they will be skipped.")
        else:
            lines.append("[yellow]No archive found[/] - first run, downloading everything.")
        if session["downloaded"]:
            prev = session["downloaded"]
            lines.append(f"[cyan]Paused session:[/] [bold]{len(prev)}[/] tracks from last time. Resuming...")
            self._download_order = list(prev)
            self._stem_to_index  = dict(session["stem_to_index"])
            self._stem_to_vid    = dict(session["stem_to_vid"])
        console.print(Panel("\n".join(lines), border_style="cyan", box=box.ROUNDED))

    def _load_vid_map(self) -> dict[str, str]:
        if self._vid_map_file.exists():
            try:
                unhide_file(self._vid_map_file)
                data = json.loads(self._vid_map_file.read_text(encoding="utf-8"))
                hide_file(self._vid_map_file)
                return data
            except Exception:
                pass
        return {}

    def _save_vid_map(self, vid_map: dict[str, str]) -> None:
        try:
            write_hidden(self._vid_map_file, json.dumps(vid_map, ensure_ascii=False, indent=2))
        except Exception:
            pass

    def _hide_service_files(self) -> None:
        for p in [hidden_path(self.output_dir, "downloaded_archive.txt"), self._failed_log, self._vid_map_file]:
            if p.exists():
                hide_file(p)

    def _count_failed_log(self) -> int:
        if not self._failed_log.exists():
            return 0
        return sum(1 for block in self._failed_log.read_text(encoding="utf-8").strip().split("\n\n") if block.strip())

    def _read_failed_entries(self) -> list[tuple[str, str]]:
        """Parse failed_downloads.txt into [(header, reason), ...] for console display."""
        entries: list[tuple[str, str]] = []
        if not self._failed_log.exists():
            return entries
        for block in self._failed_log.read_text(encoding="utf-8").strip().split("\n\n"):
            lines = [ln for ln in block.splitlines() if ln.strip()]
            if not lines:
                continue
            header = lines[0].strip()
            reason_line = next((ln for ln in lines if ln.startswith("Reason:")), None)
            reason = reason_line[len("Reason:"):].strip() if reason_line else "Unknown error"
            entries.append((header, reason))
        return entries

    def _write_session_log(self, elapsed: float, failed_count: int) -> None:
        """Append a record of this session to the global sessions log (accumulates, never overwritten)."""
        try:
            failed_entries = self._read_failed_entries() if failed_count else []
            lines = [f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"]
            target = self.playlist_title or self.last_title or str(self.output_dir)
            lines.append(f"  Target:      {target}")
            lines.append(f"  Folder:      {self.output_dir}")
            lines.append(f"  Format:      {self.fmt['label']}")
            lines.append(f"  Downloaded:  {self.new_count} track(s)")
            if self.skipped_count:
                lines.append(f"  Skipped:     {self.skipped_count} track(s)")
            lines.append(f"  Failed:      {failed_count} track(s)")
            lines.append(f"  Elapsed:     {format_time(elapsed)}")
            for header, reason in failed_entries:
                lines.append(f"    ✘ {header} :: {reason}")
            lines.append("")
            with open(SESSIONS_LOG_PATH, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception:
            pass

    def _print_summary(self, elapsed: float) -> None:
        ext          = self.fmt["ext"]
        folder_size  = sum(f.stat().st_size for f in self.output_dir.rglob(f"*.{ext}") if f.is_file())
        failed_count = self._count_failed_log()
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        table.add_column(style="dim white"); table.add_column(style="bold white")
        if self.single and self.last_title:
            table.add_row("Track", self.last_title)
        else:
            table.add_row("Downloaded", f"[bold green]{self.new_count}[/] track(s)")
            if self.skipped_count: table.add_row("Skipped", f"[dim]{self.skipped_count}[/] track(s)")
            if failed_count:       table.add_row("Failed",  f"[bold red]{failed_count}[/] track(s)")
        table.add_row("Format",       self.fmt["label"])
        table.add_row("Time elapsed", format_time(elapsed))
        table.add_row("File size" if self.single else "Folder size", format_size(folder_size))
        table.add_row("Saved to",     str(self.output_dir))
        if not self.single:
            archive = hidden_path(self.output_dir, "downloaded_archive.txt")
            if archive.exists():
                total = sum(1 for l in archive.read_text(encoding="utf-8").splitlines() if l.strip())
                table.add_row("Total in archive", f"{total} track(s)")
        console.print()
        console.print(Panel(table, title="[bold cyan]Session Summary[/]", border_style="cyan", box=box.ROUNDED))
        if failed_count:
            failed_entries = self._read_failed_entries()
            lines = [f"[white]{header}[/]\n  [red]→ {reason}[/]" for header, reason in failed_entries]
            console.print(Panel(
                "\n".join(lines) if lines else "[dim]No details available.[/]",
                title=f"[bold red]Failed — {failed_count} track(s)[/]",
                border_style="red", box=box.ROUNDED,
            ))
        else:
            console.print("[bold green]  ✔  Done.[/]")
        self._write_session_log(elapsed, failed_count)

    # ── Retry failed ──────────────────────────────────────────────────────────

    def _retry_failed(self) -> None:
        urls = parse_failed_urls(self._failed_log)
        if not urls:
            return
        console.print()
        console.print(Panel(f"[yellow]Retrying {len(urls)} failed track(s)...[/]", border_style="yellow", box=box.ROUNDED))
        self._failed_log.unlink(missing_ok=True)
        opts = self._build_ydl_opts(single_override=True)
        with yt_dlp.YoutubeDL(opts) as ydl:
            for url in urls:
                try:
                    ydl.download([url])
                except Exception:
                    pass

    # ── Main download ─────────────────────────────────────────────────────────

    def download(self, url: str) -> bool:
        """Runs the download session. Returns True if it completed with no failed tracks."""
        if self._failed_log.exists():
            self._failed_log.unlink()
        if not self.single:
            self._print_archive_status()
            self._build_full_stem_index()
            if self.is_continuation:
                check_title_duplicates(self.output_dir, self.fmt["ext"], self.playlist_entries)
        self._progress = Progress(
            SpinnerColumn(style="cyan"),
            TextColumn("[cyan]{task.description}"),
            BarColumn(bar_width=35, style="cyan", complete_style="bold green"),
            TextColumn("[bold white]{task.percentage:>5.1f}%"),
            console=console,
        )
        self._task_id = self._progress.add_task("Starting...", total=100)
        start = time.time()
        console.print()
        with self._progress:
            try:
                with yt_dlp.YoutubeDL(self._build_ydl_opts()) as ydl:
                    ydl.download([url])
            except (yt_dlp.utils.DownloadCancelled, KeyboardInterrupt):
                pass
            except Exception as e:
                console.print(f"[bold red]Fatal Error:[/] {e}")
        if self._abort:
            console.print("[bold yellow]Safe exit: progress saved, run again to resume.[/]")
        else:
            self._retry_failed()
            self._clear_session()
        if self.new_count > 0:
            postprocess_files(self.output_dir, self.fmt, self._stem_to_index or None, self.playlist_title, self.total_tracks)
        if self.is_continuation and not self.single and self.playlist_entries:
            self._reconcile_full_stem_index()
            sync_remove_deleted(self.output_dir, self.fmt["ext"], self.playlist_entries, self._stem_to_index)
        self._hide_service_files()
        self._print_summary(time.time() - start)
        return self._count_failed_log() == 0 and not self._abort


# ─── UI helpers ───────────────────────────────────────────────────────────────

def ask(prompt: str, choices: list[str], default: str) -> str:
    return Prompt.ask(f"[bold cyan]  {prompt}[/]", choices=choices, default=default)


def prompt_folder(label: str, must_exist: bool = True) -> Path:
    folder = Prompt.ask(f"[bold cyan]  {label}[/]").strip().strip('"')
    path   = Path(folder)
    if must_exist and not path.exists():
        console.print(f"[bold red]Folder not found:[/] {path}")
        sys.exit(1)
    return path


def resolve_single_output_dir() -> Path:
    console.print(Panel(
        "[bold white]1[/]  Downloads       [dim](~/Downloads)[/]\n"
        "[bold white]2[/]  Existing folder [dim](specify path)[/]\n"
        "[bold white]3[/]  Custom path     [dim](any folder, created if needed)[/]",
        title="[bold cyan]Save to[/]", border_style="cyan", box=box.ROUNDED, width=54,
    ))
    dest = ask("Select", ["1", "2", "3"], "1")
    console.print()
    if dest == "1":
        return DOWNLOADS_PATH
    if dest == "2":
        return prompt_folder("Path to existing folder", must_exist=True)
    path = prompt_folder("Custom folder path", must_exist=False)
    path.mkdir(parents=True, exist_ok=True)
    return path


def pick_recent_folder(cfg: dict) -> Path | None:
    """Show the recent-folders list and let the user pick one, or type a new path. Returns None if list is empty."""
    recent = cfg.get("recent_folders", [])
    if not recent:
        return None
    lines = [
        f"[bold white]{i+1:>2}[/]  {e['title']:<30} [dim]{format_recent_date(e.get('last_used', ''))}[/]"
        for i, e in enumerate(recent)
    ]
    lines.append(f"[bold white] 0[/]  Type a different path")
    console.print(Panel("\n".join(lines), title="[bold cyan]Recent folders[/]", border_style="cyan", box=box.ROUNDED, width=64))
    choices = [str(i) for i in range(len(recent) + 1)]
    idx = int(ask("Select", choices, "1"))
    console.print()
    if idx == 0:
        return None
    return Path(recent[idx - 1]["path"])


def show_folder_stats(cfg: dict) -> None:
    """Pick a folder from history and show its sync status: last sync date, tracks since
    then, total tracks, and recent failures pulled from the sessions log."""
    recent = cfg.get("recent_folders", [])
    if not recent:
        console.print("[yellow]  No folders in history yet — download something first.[/]")
        return
    path = pick_recent_folder(cfg)
    if path is None:
        console.print("[dim]  Cancelled.[/]")
        return
    if not path.exists():
        console.print(f"[bold red]Folder not found:[/] {path}")
        return

    entry = next((e for e in recent if e.get("path") == str(path)), None)
    title = entry["title"] if entry else path.name

    archive = hidden_path(path, "downloaded_archive.txt")
    total = len(_read_archive_ids(archive)) if archive.exists() else 0

    sessions = parse_folder_sessions(path, limit=5)

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column(style="dim white"); table.add_column(style="bold white")
    table.add_row("Playlist", title)
    table.add_row("Folder", str(path))
    table.add_row("Total tracks", f"{total}")
    if sessions:
        last = sessions[0]
        table.add_row("Last sync", format_recent_date(last["timestamp"].replace(" ", "T")))
        table.add_row("Downloaded last time", f"{last['downloaded']} track(s)")
        if last["skipped"]:
            table.add_row("Skipped last time", f"{last['skipped']} track(s)")
    else:
        table.add_row("Last sync", "[dim]No session history found[/]")
    console.print()
    console.print(Panel(table, title="[bold cyan]Folder Stats[/]", border_style="cyan", box=box.ROUNDED))

    failed_all: list[tuple[str, str, str]] = []  # (timestamp, header, reason)
    for rec in sessions:
        for header, reason in rec["failed_tracks"]:
            failed_all.append((rec["timestamp"], header, reason))
    if failed_all:
        lines = [f"[white]{header}[/]  [dim]({ts})[/]\n  [red]→ {reason}[/]" for ts, header, reason in failed_all]
        console.print(Panel(
            "\n".join(lines),
            title=f"[bold red]Failed tracks — last {len(sessions)} session(s)[/]",
            border_style="red", box=box.ROUNDED,
        ))
    else:
        console.print("[dim]  No failed tracks in recent history.[/]")


def resolve_playlist_output_dir(playlist_title: str, cfg: dict) -> tuple[Path, bool]:
    """Returns (output_dir, is_continuation)."""
    console.print(Panel(
        "[bold white]1[/]  New download       [dim](auto-create folder in ~/Downloads)[/]\n"
        "[bold white]2[/]  Continue existing  [dim](specify existing folder path)[/]\n"
        "[bold white]3[/]  Custom path        [dim](any folder, created if needed)[/]\n"
        "[bold white]4[/]  Quick continue     [dim](pick from recent, skip the questions)[/]",
        title="[bold cyan]Mode[/]", border_style="cyan", box=box.ROUNDED, width=58,
    ))
    mode = ask("Select", ["1", "2", "3", "4"], "1")
    console.print()
    if mode == "4":
        recent = cfg.get("recent_folders", [])
        if not recent:
            console.print("[yellow]  No recent folders yet — falling back to manual path.[/]")
            path = prompt_folder("Path to playlist folder", must_exist=True)
        else:
            path = Path(recent[0]["path"])
            if not path.exists():
                console.print(f"[bold red]Folder not found:[/] {path}")
                sys.exit(1)
            console.print(f"[green]  Quick continue:[/] [bold]{path}[/]")
        restore_dates_from_order(path)
        remember_folder(cfg, path, playlist_title)
        return path, True
    if mode == "2":
        path = pick_recent_folder(cfg)
        if path is None:
            path = prompt_folder("Path to playlist folder", must_exist=True)
        elif not path.exists():
            console.print(f"[bold red]Folder not found:[/] {path}")
            sys.exit(1)
        restore_dates_from_order(path)
        console.print(f"[green]  Continuing in:[/] {path}")
        remember_folder(cfg, path, playlist_title)
        return path, True
    if mode == "3":
        path = prompt_folder("Custom folder path", must_exist=False)
        path.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]  Saving to:[/] [bold]{path}[/]")
        remember_folder(cfg, path, playlist_title)
        return path, False
    path = DOWNLOADS_PATH / playlist_title
    path.mkdir(parents=True, exist_ok=True)
    console.print(f"[green]  Playlist folder:[/] [bold]{path}[/]")
    remember_folder(cfg, path, playlist_title)
    return path, False


def select_format() -> dict:
    lossless = [k for k, v in AUDIO_FORMATS.items() if v["quality"] is None]
    lossy    = [k for k, v in AUDIO_FORMATS.items() if v["quality"] is not None]
    lines    = ["[dim]── Lossless ────────────────────────────────────────[/]"]
    for k in lossless:
        v = AUDIO_FORMATS[k]
        lines.append(f"[bold white]{k:>2}[/]  {v['label']:<14} [dim]{v['note']}[/]")
    lines.append("[dim]── Lossy ──────────────────────────────────────────[/]")
    for k in lossy:
        v = AUDIO_FORMATS[k]
        lines.append(f"[bold white]{k:>2}[/]  {v['label']:<14} [dim]{v['note']}[/]")
    console.print(Panel("\n".join(lines), title="[bold cyan]Format[/]", border_style="cyan", box=box.ROUNDED, width=62))
    choice = ask("Select", list(AUDIO_FORMATS.keys()), "1")
    console.print()
    return AUDIO_FORMATS[choice]


def print_size_estimate(count: int, fmt: dict) -> None:
    mb = count * fmt.get("mb_per_track", 10)
    console.print(Panel(
        f"[cyan]Estimated size:[/] [bold]{count} tracks × ~{fmt['mb_per_track']} MB = ~{format_size_mb(mb)}[/]  [dim]({fmt['label']})[/]",
        border_style="dim", box=box.ROUNDED,
    ))
    console.print()


def count_already_archived(output_dir: Path, playlist_entries: list) -> int:
    """Count how many of the playlist's entries are already present in this folder's archive."""
    archive_ids = _read_archive_ids(hidden_path(output_dir, "downloaded_archive.txt"))
    if not archive_ids or not playlist_entries:
        return 0
    playlist_ids = {_extract_entry_id(e) for e in playlist_entries if e} - {""}
    return len(archive_ids & playlist_ids)


# ─── Single download session ──────────────────────────────────────────────────

def run_once(cfg: dict) -> bool:
    """Runs one download session. Returns True on success (no failed tracks)."""
    url = Prompt.ask("[bold cyan]  YouTube Music URL[/]").strip()
    if not url:
        console.print("[red]No URL provided.[/]")
        return False
    with console.status("[bold cyan]Checking URL...[/]", spinner="dots"):
        meta = inspect_url(url)
    single, title, total_tracks, playlist_entries = meta["single"], meta["title"], meta["count"], meta["entries"]
    if single:
        console.print(Panel(f"[bold white]Single track:[/] {title}", border_style="cyan", box=box.ROUNDED))
    else:
        count_str = f"  [dim]{total_tracks} tracks[/]" if total_tracks else ""
        console.print(Panel(f"[bold white]Playlist:[/] {title}{count_str}", border_style="cyan", box=box.ROUNDED))
    console.print()
    fmt = select_format()
    is_continuation = False
    if single:
        output_dir = resolve_single_output_dir()
        if total_tracks:
            print_size_estimate(total_tracks, fmt)
    else:
        output_dir, is_continuation = resolve_playlist_output_dir(title, cfg)
        if total_tracks:
            already = count_already_archived(output_dir, playlist_entries) if is_continuation else 0
            remaining = max(total_tracks - already, 0)
            if already:
                print_size_estimate(remaining, fmt)
                console.print(Panel(
                    f"[dim]{already} of {total_tracks} tracks already downloaded — {remaining} remaining.[/]",
                    border_style="dim", box=box.ROUNDED,
                ))
                console.print()
            else:
                print_size_estimate(total_tracks, fmt)
    return Downloader(
        output_dir, fmt, cfg=cfg, single=single, total_tracks=total_tracks,
        playlist_title=title if not single else None,
        playlist_entries=playlist_entries, is_continuation=is_continuation,
    ).download(url)


# ─── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    console.clear()
    console.print(Panel(
        "[bold cyan]LOGOVO[/] [bold white]DUSHNIL[/]",
        border_style="cyan", box=box.DOUBLE, expand=False,
    ), justify="center")
    console.print("  YTMusic Downloader by Helvior  v2.0", style="dim white", justify="center")
    console.print()
    cfg = load_config()

    while True:
        console.print(Panel(
            "[bold white]1[/]  Download track / playlist\n"
            "[bold white]2[/]  Folder stats  [dim](check sync status, no download)[/]\n"
            "[bold white]3[/]  Exit",
            title="[bold cyan]Menu[/]", border_style="cyan", box=box.ROUNDED, width=54,
        ))
        choice = ask("Select", ["1", "2", "3"], "1")
        console.print()

        if choice == "3":
            console.print("[dim]  Goodbye![/]")
            break

        if choice == "2":
            show_folder_stats(cfg)
            console.print()
            continue

        success = run_once(cfg)
        console.print()
        if success:
            console.print("[bold green]  ✔  Success.[/] [dim]Back at the main menu.[/]")
        else:
            console.print("[bold yellow]  ⚠  Finished with errors.[/] [dim]Back at the main menu.[/]")
        console.print()


if __name__ == "__main__":
    main()