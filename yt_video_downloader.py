import ctypes
import difflib
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yt_dlp
from mutagen.mp4 import MP4 as _MP4, MP4Cover
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.prompt import Confirm, Prompt
from rich.table import Table

# ─── Constants & Console Setup ────────────────────────────────────────────────

console = Console()
DOWNLOADS_PATH = Path.home() / "Downloads"
FORBIDDEN_CHARS = r'\/:*?"<>|'

APP_NAME = "LogovoDushnil"

ERROR_REASONS: list[tuple[str, str]] = [
    ("Sign in to confirm your age",  "Age-restricted — account required"),
    ("Video unavailable",            "Video unavailable"),
    ("copyright claim",              "Blocked by copyright claim"),
    ("This video is not available",  "Video not available in your region"),
    ("Private video",                "Private video"),
    ("This video has been removed",  "Video removed by uploader"),
    ("confirm you're not a bot",     "Bot check active"),
]


def friendly_error(raw: str) -> str:
    """Return short human-readable reason from raw yt-dlp error string."""
    for needle, label in ERROR_REASONS:
        if needle.lower() in raw.lower():
            return label
    clean = re.sub(r"\x1b\[[0-9;]*m", "", raw).strip()
    first = re.split(r"[\n.]", clean)[0].strip()
    return first[:120] if first else raw[:120]


def send_windows_notification(title: str, message: str) -> None:
    """Send native Windows Desktop Notification balloon."""
    if sys.platform != "win32":
        return
    try:
        clean_title = title.replace("'", "").replace('"', "")
        clean_msg = message.replace("'", "").replace('"', "")
        ps_script = (
            "[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms');"
            "$n=New-Object System.Windows.Forms.NotifyIcon;"
            "$n.Icon=[System.Drawing.SystemIcons]::Information;"
            "$n.BalloonTipIcon='Info';"
            f"$n.BalloonTipTitle='{clean_title}';"
            f"$n.BalloonTipText='{clean_msg}';"
            "$n.Visible=$True;"
            "$n.ShowBalloonTip(5000);"
        )
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", ps_script],
            creationflags=0x08000000,
        )
    except Exception:
        pass


# ─── Format matrix ────────────────────────────────────────────────────────────

CONTAINERS = {
    "1": "MP4",
    "2": "MKV",
    "3": "WEBM",
}

CODECS: dict[str, dict] = {
    "h264": {
        "label":         "H.264  (AVC)",
        "containers":    {"MP4", "MKV"},
        "vf_codec":      "avc1",
        "ffmpeg_vcodec": "libx264",
        "ffmpeg_acodec": "aac",
        "audio_bitrate": "192k",
        "note":          "maximum compatibility",
    },
    "h265": {
        "label":         "H.265  (HEVC)",
        "containers":    {"MP4", "MKV"},
        "vf_codec":      "hev1",
        "ffmpeg_vcodec": "libx265",
        "ffmpeg_acodec": "aac",
        "audio_bitrate": "192k",
        "note":          "smaller size, heavier encoding",
    },
    "av1_mp4": {
        "label":         "AV1",
        "containers":    {"MP4", "MKV"},
        "vf_codec":      "av01",
        "ffmpeg_vcodec": "copy",
        "ffmpeg_acodec": "aac",
        "audio_bitrate": "192k",
        "note":          "best compression, slow decoder",
    },
    "vp9": {
        "label":         "VP9",
        "containers":    {"WEBM"},
        "vf_codec":      "vp09",
        "ffmpeg_vcodec": "copy",
        "ffmpeg_acodec": "libopus",
        "audio_bitrate": "192k",
        "note":          "native for WEBM, no re-encoding",
    },
    "av1_webm": {
        "label":         "AV1",
        "containers":    {"WEBM"},
        "vf_codec":      "av01",
        "ffmpeg_vcodec": "copy",
        "ffmpeg_acodec": "libopus",
        "audio_bitrate": "192k",
        "note":          "best compression, no re-encoding",
    },
}

QUALITY_OPTIONS = {
    "1": ("4K",    2160),
    "2": ("1080p", 1080),
    "3": ("720p",   720),
    "4": ("480p",   480),
    "5": ("Best",  9999),
}

SUBTITLE_LANG_OPTIONS = {
    "1": ("None", "none"),
    "2": ("English", "en"),
    "3": ("Russian", "ru"),
    "4": ("English & Russian", "en,ru"),
    "5": ("All available languages", "all"),
}

SUBTITLE_MODE_OPTIONS = {
    "1": ("Embed into container (MKV/MP4)", "embed"),
    "2": ("Save as external .srt files", "external"),
    "3": ("Both (Embed + external .srt)", "both"),
}


# ─── Config & Storage Management ──────────────────────────────────────────────

def get_app_data_dir() -> Path:
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
    "default_format": None,
    "default_output": None,
    "recent_folders": [],
    "speed_limit_mb": None,
    "notifications_enabled": True,
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


# ─── File Hiding Helpers ──────────────────────────────────────────────────────

def unhide_file(path: Path) -> None:
    if sys.platform == "win32" and path.exists():
        try:
            ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x80)
        except Exception:
            pass


def hide_file(path: Path) -> None:
    if sys.platform == "win32" and path.exists():
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


# ─── General Helpers ──────────────────────────────────────────────────────────

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


def format_time(s: float) -> str:
    s = int(s)
    if s >= 3600:
        return f"{s // 3600}h {(s % 3600) // 60}m"
    if s >= 60:
        return f"{s // 60}m {s % 60}s"
    return f"{s}s"


def base_ydl_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
    }
    if FFMPEG_PATH:
        opts["ffmpeg_location"] = FFMPEG_PATH
    return opts


def build_format_string(codec_id: str, max_height: int) -> str:
    codec = CODECS[codec_id]
    vf = codec["vf_codec"]
    h = "" if max_height >= 9999 else f"[height<={max_height}]"
    return f"bestvideo[vcodec^={vf}]{h}+bestaudio/bestvideo{h}+bestaudio/best"


def build_postprocessor_args(codec_id: str) -> dict:
    codec = CODECS[codec_id]
    return {
        "ffmpegvideomerger": [
            "-c:v", codec["ffmpeg_vcodec"],
            "-c:a", codec["ffmpeg_acodec"],
            "-b:a", codec["audio_bitrate"],
        ],
    }


def _read_archive_ids(archive_path: Path) -> set[str]:
    if not archive_path.exists():
        return set()
    try:
        lines = archive_path.read_text(encoding="utf-8").splitlines()
        return {ln.split()[1] for ln in lines if ln.strip().startswith("youtube ")}
    except Exception:
        return set()


# ─── Metadata & Poster Embedding ──────────────────────────────────────────────

def embed_metadata(path: Path, info: dict, container: str) -> None:
    try:
        if container in ("mp4", "mkv", "webm", "m4v"):
            _embed_via_mutagen(path, info, container)
    except Exception:
        pass


def _clean(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value).strip()


def _upload_date_iso(raw: str) -> str:
    raw = raw.strip()
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw


def _embed_via_mutagen(path: Path, info: dict, container: str) -> None:
    title = _clean(info.get("title"))
    uploader = _clean(info.get("uploader") or info.get("channel"))
    date_raw = _clean(info.get("upload_date"))
    date = _upload_date_iso(date_raw) if date_raw else ""
    description = _clean(info.get("description"))
    tags_list = info.get("tags") or []
    tags_str = ", ".join(_clean(t) for t in tags_list if t)

    if container == "mp4":
        _embed_mp4(path, title, uploader, date, description, tags_str)
    elif container in ("mkv", "webm"):
        _embed_mkv(path, title, uploader, date, description, tags_str)


def _embed_mp4(
    path: Path,
    title: str,
    uploader: str,
    date: str,
    description: str,
    tags: str,
) -> None:
    audio = _MP4(path)
    if title:
        audio["\xa9nam"] = [title]
    if uploader:
        audio["\xa9ART"] = [uploader]
    if date:
        audio["\xa9day"] = [date]
    if description:
        audio["desc"] = [description[:255]]
        audio["ldes"] = [description]
    if tags:
        audio["\xa9cmt"] = [tags]
        audio["keyw"] = [tags]

    jpg_path = path.with_suffix(".jpg")
    png_path = path.with_suffix(".png")
    cover_file = jpg_path if jpg_path.exists() else (png_path if png_path.exists() else None)
    if cover_file:
        try:
            with open(cover_file, "rb") as f:
                cover_data = f.read()
            img_format = MP4Cover.FORMAT_JPEG if cover_file.suffix.lower() in (".jpg", ".jpeg") else MP4Cover.FORMAT_PNG
            audio["covr"] = [MP4Cover(cover_data, imageformat=img_format)]
        except Exception:
            pass

    audio.save()


def _embed_mkv(
    path: Path,
    title: str,
    uploader: str,
    date: str,
    description: str,
    tags: str,
) -> None:
    import shutil
    import subprocess
    import tempfile

    ffmpeg = FFMPEG_PATH or shutil.which("ffmpeg")
    if not ffmpeg:
        return

    meta: dict[str, str] = {}
    if title:
        meta["title"] = title
    if uploader:
        meta["artist"] = uploader
    if date:
        meta["date"] = date
    if description:
        meta["description"] = description
    if tags:
        meta["comment"] = tags

    if not meta:
        return

    meta_args: list[str] = []
    for k, v in meta.items():
        meta_args += ["-metadata", f"{k}={v}"]

    bak_path = path.with_suffix(path.suffix + ".bak")
    with tempfile.NamedTemporaryFile(suffix=path.suffix, delete=False, dir=path.parent) as tmp:
        tmp_path = Path(tmp.name)

    try:
        shutil.copy2(path, bak_path)

        result = subprocess.run(
            [ffmpeg, "-y", "-i", str(path), "-c", "copy"] + meta_args + [str(tmp_path)],
            capture_output=True,
        )

        if result.returncode == 0 and tmp_path.exists() and tmp_path.stat().st_size > 0:
            path.unlink(missing_ok=True)
            tmp_path.rename(path)
            bak_path.unlink(missing_ok=True)
        else:
            tmp_path.unlink(missing_ok=True)
            if bak_path.exists():
                bak_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        if bak_path.exists():
            try:
                bak_path.replace(path)
            except Exception:
                pass


# ─── URL Inspection ───────────────────────────────────────────────────────────

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


# ─── Error Logger ─────────────────────────────────────────────────────────────

class ErrorLogger:
    def __init__(self, failed_log: Path, output_dir: Path | None = None):
        self._log = failed_log
        self.output_dir = output_dir
        self.current_info: dict = {}
        self.recorded_failures: list[dict] = []

    def debug(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        pass

    def error(self, msg: str) -> None:
        if not msg or msg.startswith("WARNING"):
            return

        title = self.current_info.get("title") or "Unknown title"
        artist = self.current_info.get("uploader") or self.current_info.get("channel") or "Unknown uploader"
        url = self.current_info.get("webpage_url") or ""
        vid_id = self.current_info.get("id") or ""

        if not vid_id and "ERROR:" in msg:
            m = re.search(r"YouTube said:.*?([a-zA-Z0-9_-]{11})", msg)
            if m:
                vid_id = m.group(1)

        reason = friendly_error(msg)

        failure_entry = {
            "title": title,
            "artist": artist,
            "url": url,
            "id": vid_id,
            "reason": reason,
            "raw_msg": msg,
        }
        self.recorded_failures.append(failure_entry)

        text = f"{artist} — {title}\n"
        if url:
            text += f"URL: {url}\n"
        text += f"Reason: {reason}\nRaw: {msg}\n\n"

        unhide_file(self._log)
        with open(self._log, "a", encoding="utf-8") as f:
            f.write(text)
        hide_file(self._log)


# ─── Downloader ───────────────────────────────────────────────────────────────

class Downloader:
    def __init__(
        self,
        output_dir: Path,
        container: str,
        codec_id: str,
        max_height: int,
        single: bool = False,
        total_tracks: int | None = None,
        playlist_title: str | None = None,
        playlist_entries: list | None = None,
        is_continuation: bool = False,
        cfg: dict | None = None,
        subtitles_lang: str | None = None,
        subtitles_mode: str | None = None,
    ):
        self.output_dir = output_dir
        self.container = container.lower()
        self.codec_id = codec_id
        self.max_height = max_height
        self.single = single
        self.total_tracks = total_tracks
        self.playlist_title = playlist_title
        self.playlist_entries = playlist_entries or []
        self.is_continuation = is_continuation
        self.cfg = cfg or {}
        self.subtitles_lang = subtitles_lang or "none"
        self.subtitles_mode = subtitles_mode or "embed"

        self.new_count = 0
        self.skipped_count = 0
        self.last_title: str = ""
        self._abort = False
        self._progress: Progress | None = None
        self._task_id = None
        self._current_track = 0
        self._download_order: list[str] = []
        self._pending_meta: dict[str, dict] = {}

        self._failed_log = hidden_path(output_dir, "failed_downloads.txt")
        self._session_file = hidden_path(output_dir, "session_progress.json")
        self._vid_map_file = hidden_path(output_dir, "stem_vid_map.json")
        self._archive_file = hidden_path(output_dir, "downloaded_archive.txt")

        self._error_logger = ErrorLogger(self._failed_log, output_dir=output_dir)

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame) -> None:
        if self._abort:
            console.print("\n[bold red]Force exit.[/]")
            sys.exit(1)
        self._abort = True
        console.print("\n[bold yellow]⚠  Stopping after current video... (Ctrl+C again to force quit)[/]")

    def _track_label(self, name: str) -> str:
        if self.single or self.total_tracks is None:
            return name
        return f"[{self._current_track}/{self.total_tracks}] {name}"

    def _on_progress(self, d: dict) -> None:
        status = d["status"]
        if info := d.get("info_dict"):
            self._error_logger.current_info = info

        if status == "downloading":
            downloaded = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            name = Path(d.get("filename", "")).stem[:35]

            if self._progress and self._task_id is not None:
                if total > 0:
                    self._progress.update(
                        self._task_id,
                        completed=downloaded,
                        total=total,
                        description=f"[cyan]{self._track_label(name)}[/]",
                    )

        elif status == "finished":
            self._current_track += 1
            self.new_count += 1
            info = d.get("info_dict") or {}
            self.last_title = info.get("title") or Path(d.get("filename", "")).stem
            stem = Path(d.get("filename", "")).stem

            if stem:
                self._download_order.append(stem)
                self._pending_meta[stem] = {
                    "title": info.get("title") or "",
                    "uploader": info.get("uploader") or info.get("channel") or "",
                    "upload_date": info.get("upload_date") or "",
                    "description": info.get("description") or "",
                    "tags": info.get("tags") or [],
                }
            if self._progress and self._task_id is not None:
                self._progress.update(self._task_id, completed=0)
            console.print(f"  [bold green]✔[/] [white]{self.last_title}[/] [dim]— processing...[/]")

        elif status == "already_downloaded":
            self._current_track += 1
            self.skipped_count += 1
            console.print("  [dim]⏭  Skipped (already downloaded)[/]")

        elif status == "error":
            console.print("  [bold red]✘[/] [dim]Failed — see logs[/]")

        if self._abort and status in ("finished", "already_downloaded"):
            raise yt_dlp.utils.DownloadCancelled("Safe exit")

    def _build_ydl_opts(self) -> dict:
        fmt = build_format_string(self.codec_id, self.max_height)
        pp_args = build_postprocessor_args(self.codec_id)

        postprocessors = [
            {"key": "FFmpegVideoRemuxer", "preferedformat": self.container},
            {"key": "FFmpegThumbnailsConvertor", "format": "jpg"},
            {"key": "EmbedThumbnail"},
        ]

        opts = {
            "format": fmt,
            "merge_output_format": self.container,
            "outtmpl": str(self.output_dir / "%(title)s.%(ext)s"),
            "writethumbnail": True,
            "postprocessors": postprocessors,
            "postprocessor_args": pp_args,
            "progress_hooks": [self._on_progress],
            "logger": self._error_logger,
            "ignoreerrors": True,
            "noplaylist": self.single,
            "no_warnings": True,
            "quiet": True,
            "retries": 15,
            "fragment_retries": 15,
            "retry_sleep_functions": {"http": lambda n: min(4 * 2 ** n, 60)},
            "socket_timeout": 30,
        }

        if speed_mb := self.cfg.get("speed_limit_mb"):
            try:
                opts["ratelimit"] = int(float(speed_mb) * 1024 * 1024)
            except ValueError:
                pass

        if self.subtitles_lang and self.subtitles_lang != "none":
            opts["writesubtitles"] = True
            opts["writeautomaticsub"] = True
            opts["subtitlesformat"] = "srt/vtt/best"
            if self.subtitles_lang == "all":
                opts["subtitleslangs"] = ["all"]
            elif "," in self.subtitles_lang:
                opts["subtitleslangs"] = [s.strip() for s in self.subtitles_lang.split(",") if s.strip()]
            else:
                opts["subtitleslangs"] = [self.subtitles_lang]

            if self.subtitles_mode in ("embed", "both"):
                opts["embedsubtitles"] = True
                opts["postprocessors"].append({"key": "FFmpegEmbedSubtitle"})

        if not self.single:
            opts["download_archive"] = str(self._archive_file)
        if FFMPEG_PATH:
            opts["ffmpeg_location"] = FFMPEG_PATH
        return opts

    def _print_archive_status(self) -> None:
        if self._archive_file.exists():
            count = len(_read_archive_ids(self._archive_file))
            console.print(Panel(
                f"[green]Archive found:[/] [bold]{count}[/] videos recorded — existing videos will be skipped.",
                border_style="green", box=box.ROUNDED,
            ))
        else:
            console.print(Panel(
                "[yellow]No archive found[/] — first run, downloading selected videos.",
                border_style="yellow", box=box.ROUNDED,
            ))

    def _embed_all_metadata(self) -> None:
        if not self._pending_meta:
            return

        ext = self.container
        all_files = list(self.output_dir.rglob(f"*.{ext}"))
        targets = [f for f in all_files if f.stem in self._pending_meta]

        if not targets:
            return

        with console.status("[bold cyan]Embedding video metadata & poster...[/]", spinner="dots"):
            for path in targets:
                info = self._pending_meta.get(path.stem, {})
                embed_metadata(path, info, ext)

    def _fix_file_order(self) -> None:
        all_files = list(self.output_dir.rglob(f"*.{self.container}"))
        if len(all_files) <= 1:
            return

        if self._download_order:
            order_index = {stem: i for i, stem in enumerate(self._download_order)}
            sorted_files = sorted(
                all_files,
                key=lambda p: (order_index.get(p.stem, len(self._download_order)), p.stat().st_ctime),
            )
        else:
            sorted_files = sorted(all_files, key=lambda p: p.stat().st_ctime)

        base_time = time.time()
        for i, path in enumerate(sorted_files):
            try:
                os.utime(path, (base_time + i, base_time + i))
            except Exception:
                pass

        write_hidden(
            hidden_path(self.output_dir, "playlist_order.txt"),
            "\n".join(p.name for p in sorted_files),
        )

    def _count_failed_log(self) -> int:
        if not self._failed_log.exists():
            return 0
        try:
            text = self._failed_log.read_text(encoding="utf-8")
            return sum(1 for block in text.strip().split("\n\n") if block.strip())
        except Exception:
            return 0

    def _log_session_to_file(self, elapsed: float, video_files: list[Path]) -> None:
        folder_size = sum(f.stat().st_size for f in video_files if f.is_file())
        failed_count = self._count_failed_log()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = [
            f"[{now_str}] VIDEO SESSION",
            f"Folder: {self.output_dir}",
            f"Container: {self.container.upper()} | Codec: {CODECS[self.codec_id]['label']}",
            f"Downloaded: {self.new_count}",
            f"Skipped: {self.skipped_count}",
            f"Failed: {failed_count}",
            f"Duration: {format_time(elapsed)}",
            f"Total Files: {len(video_files)} ({format_size(folder_size)})",
        ]

        if self._error_logger.recorded_failures:
            lines.append("Failed videos details:")
            for f_item in self._error_logger.recorded_failures:
                lines.append(f"  ✘ {f_item['artist']} — {f_item['title']} :: {f_item['reason']}")

        block = "\n".join(lines) + "\n\n"
        try:
            with open(SESSIONS_LOG_PATH, "a", encoding="utf-8") as sf:
                sf.write(block)
        except Exception:
            pass

    def _retry_failed(self) -> None:
        if not self._failed_log.exists():
            return
        text = self._failed_log.read_text(encoding="utf-8").strip()
        if not text:
            return

        blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
        if not blocks:
            return

        urls_to_retry: list[str] = []
        for b in blocks:
            for line in b.splitlines():
                if line.startswith("URL:"):
                    urls_to_retry.append(line.replace("URL:", "").strip())

        if not urls_to_retry:
            return

        console.print()
        if not Confirm.ask(f"[bold yellow]Retry {len(urls_to_retry)} failed video(s) now?[/]", default=True):
            return

        unhide_file(self._failed_log)
        self._failed_log.unlink(missing_ok=True)
        self.new_count = 0
        self.skipped_count = 0

        console.print("\n[bold cyan]Starting retries...[/]")
        opts = self._build_ydl_opts()
        with yt_dlp.YoutubeDL(opts) as ydl:
            for url in urls_to_retry:
                try:
                    ydl.download([url])
                except Exception:
                    pass

    def _print_summary(self, elapsed: float) -> None:
        video_files = list(self.output_dir.rglob(f"*.{self.container}"))
        folder_size = sum(f.stat().st_size for f in video_files if f.is_file())
        failed_count = self._count_failed_log()

        codec_label = CODECS[self.codec_id]["label"]
        quality_label = next(
            (v[0] for v in QUALITY_OPTIONS.values() if v[1] == self.max_height), "Best"
        )

        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        table.add_column(style="dim white")
        table.add_column(style="bold white")

        if self.single and self.last_title:
            table.add_row("Video", self.last_title)
        else:
            table.add_row("Downloaded", f"[bold green]{self.new_count}[/] video(s)")
            if self.skipped_count:
                table.add_row("Skipped", f"[dim]{self.skipped_count}[/] video(s)")
            if failed_count:
                table.add_row("Failed", f"[bold red]{failed_count}[/] video(s)")

        table.add_row("Format", f"{self.container.upper()}  ·  {codec_label}  ·  {quality_label}")
        table.add_row("Subtitles", self.subtitles_lang.upper() if self.subtitles_lang != "none" else "Disabled")
        table.add_row("Metadata & Poster", "Embedded in video file")
        table.add_row("Time elapsed", format_time(elapsed))
        table.add_row("File size" if self.single else "Folder size", format_size(folder_size))
        table.add_row("Saved to", str(self.output_dir))

        if not self.single and self._archive_file.exists():
            total = len(_read_archive_ids(self._archive_file))
            table.add_row("Total in archive", f"{total} video(s)")

        console.print()
        console.print(Panel(table, title="[bold cyan]Session Summary[/]", border_style="cyan", box=box.ROUNDED))

        self._log_session_to_file(elapsed, video_files)

        if self.cfg.get("notifications_enabled", True):
            send_windows_notification("LogovoDushnil", f"Downloaded {self.new_count} video(s) to {self.output_dir.name}")

        if failed_count:
            console.print(f"[bold red]  ✘  {failed_count} video(s) failed.[/]")
            self._retry_failed()
        else:
            console.print("[bold green]  ✔  Done.[/]")

    def download(self, url: str) -> bool:
        if self._failed_log.exists():
            unhide_file(self._failed_log)
            self._failed_log.unlink(missing_ok=True)

        if not self.single:
            self._print_archive_status()

        self._progress = Progress(
            SpinnerColumn(style="cyan"),
            TextColumn("[cyan]{task.description}"),
            BarColumn(bar_width=30, style="cyan", complete_style="bold green"),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
        )
        self._task_id = self._progress.add_task("Downloading...", total=None)

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
            console.print("[bold yellow]Safe exit: finishing up...[/]")

        if self.new_count > 0:
            self._embed_all_metadata()
            with console.status("[bold cyan]Fixing file order...[/]", spinner="dots"):
                self._fix_file_order()

        self._print_summary(time.time() - start)

        if self._archive_file.exists():
            hide_file(self._archive_file)

        return self._count_failed_log() == 0


# ─── UI Helpers ───────────────────────────────────────────────────────────────

def ask(prompt: str, choices: list[str], default: str) -> str:
    return Prompt.ask(f"[bold cyan]  {prompt}[/]", choices=choices, default=default)


def prompt_folder(prompt_text: str, must_exist: bool = True) -> Path:
    while True:
        raw = Prompt.ask(f"[bold cyan]  {prompt_text}[/]").strip().strip('"')
        if not raw:
            continue
        p = Path(raw)
        if must_exist and not p.exists():
            console.print(f"[bold red]Folder not found:[/] {p}")
            continue
        return p


def pick_recent_folder(cfg: dict) -> Path | None:
    recent = [r for r in cfg.get("recent_folders", []) if Path(r["path"]).exists()]
    if not recent:
        return None

    lines = [
        f"[bold white]{i}[/]  {r.get('title', Path(r['path']).name)}  [dim]({r['path']})[/]"
        for i, r in enumerate(recent, 1)
    ]
    lines.append(f"[bold white]{len(recent) + 1}[/]  [dim]Enter another folder path...[/]")

    console.print(Panel(
        "\n".join(lines),
        title="[bold cyan]Recent folders[/]", border_style="cyan", box=box.ROUNDED, width=65,
    ))
    choices = [str(i) for i in range(1, len(recent) + 2)]
    idx = int(ask("Select folder", choices, "1")) - 1

    if idx < len(recent):
        return Path(recent[idx]["path"])
    return None


def resolve_single_output_dir() -> Path:
    console.print(Panel(
        "[bold white]1[/]  Downloads  [dim](~/Downloads)[/]\n"
        "[bold white]2[/]  Specify custom folder",
        title="[bold cyan]Save to[/]", border_style="cyan", box=box.ROUNDED, width=40,
    ))
    dest = ask("Select", ["1", "2"], "1")
    console.print()
    if dest == "1":
        return DOWNLOADS_PATH
    return prompt_folder("Path to folder", must_exist=False)


def resolve_playlist_output_dir(playlist_title: str, cfg: dict) -> tuple[Path, bool]:
    has_recent = any(Path(r["path"]).exists() for r in cfg.get("recent_folders", []))
    lines = [
        "[bold white]1[/]  New download        [dim](create folder automatically)[/]",
        "[bold white]2[/]  Continue existing   [dim](choose folder path)[/]",
        "[bold white]3[/]  Custom folder       [dim](specify exact path)[/]",
    ]
    console.print(Panel("\n".join(lines), title="[bold cyan]Mode[/]", border_style="cyan", box=box.ROUNDED, width=50))
    mode = ask("Select", ["1", "2", "3"], "1")
    console.print()

    if mode == "2":
        path = pick_recent_folder(cfg) if has_recent else prompt_folder("Path to playlist folder", must_exist=True)
        if path is None:
            path = prompt_folder("Path to playlist folder", must_exist=True)
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


def select_container() -> str:
    body = (
        "[bold white]1[/]  MP4   [dim]universal, widest compatibility[/]\n"
        "[bold white]2[/]  MKV   [dim]preserves all tracks and subtitles[/]\n"
        "[bold white]3[/]  WEBM  [dim]VP9/AV1 without re-encoding, smaller size[/]"
    )
    console.print(Panel(body, title="[bold cyan]Container[/]", border_style="cyan", box=box.ROUNDED, width=55))
    choice = ask("Select", ["1", "2", "3"], "1")
    console.print()
    return CONTAINERS[choice]


def select_codec(container: str) -> str:
    available = {k: v for k, v in CODECS.items() if container in v["containers"]}
    keys = list(available.keys())
    lines = [
        f"[bold white]{i}[/]  {info['label']}  [dim]{info['note']}[/]"
        for i, (_, info) in enumerate(available.items(), 1)
    ]
    console.print(Panel(
        "\n".join(lines),
        title="[bold cyan]Video codec[/]", border_style="cyan", box=box.ROUNDED, width=55,
    ))
    nums = [str(i) for i in range(1, len(keys) + 1)]
    choice = ask("Select", nums, "1")
    console.print()
    return keys[int(choice) - 1]


def select_quality() -> int:
    lines = [f"[bold white]{k}[/]  {v[0]}" for k, v in QUALITY_OPTIONS.items()]
    console.print(Panel(
        "\n".join(lines),
        title="[bold cyan]Quality[/]", border_style="cyan", box=box.ROUNDED, width=30,
    ))
    choice = ask("Select", list(QUALITY_OPTIONS.keys()), "2")
    console.print()
    return QUALITY_OPTIONS[choice][1]


def select_subtitles() -> tuple[str, str]:
    lines = [f"[bold white]{k}[/]  {v[0]}" for k, v in SUBTITLE_LANG_OPTIONS.items()]
    console.print(Panel(
        "\n".join(lines),
        title="[bold cyan]Subtitles / Closed Captions[/]", border_style="cyan", box=box.ROUNDED, width=45,
    ))
    choice = ask("Select language", list(SUBTITLE_LANG_OPTIONS.keys()), "1")
    console.print()

    sub_lang = SUBTITLE_LANG_OPTIONS[choice][1]
    if sub_lang == "none":
        return "none", "embed"

    mode_lines = [f"[bold white]{k}[/]  {v[0]}" for k, v in SUBTITLE_MODE_OPTIONS.items()]
    console.print(Panel(
        "\n".join(mode_lines),
        title="[bold cyan]Subtitle Format & Mode[/]", border_style="cyan", box=box.ROUNDED, width=45,
    ))
    mode_choice = ask("Select mode", list(SUBTITLE_MODE_OPTIONS.keys()), "1")
    console.print()

    return sub_lang, SUBTITLE_MODE_OPTIONS[mode_choice][1]


# ─── Single Download Session ──────────────────────────────────────────────────

def run_video_download(cfg: dict | None = None) -> bool:
    if cfg is None:
        cfg = load_config()

    url = Prompt.ask("[bold cyan]  YouTube Video / Playlist URL[/]").strip()
    if not url:
        console.print("[red]No URL provided.[/]")
        return False

    with console.status("[bold cyan]Checking URL...[/]", spinner="dots"):
        meta = inspect_url(url)

    single, title, total_tracks, playlist_entries = meta["single"], meta["title"], meta["count"], meta["entries"]

    if single:
        console.print(Panel(f"[bold white]Single video:[/] {title}", border_style="cyan", box=box.ROUNDED))
    else:
        count_str = f"  [dim]{total_tracks} videos[/]" if total_tracks else ""
        console.print(Panel(f"[bold white]Playlist:[/] {title}{count_str}", border_style="cyan", box=box.ROUNDED))
    console.print()

    container = select_container()
    codec_id = select_codec(container)
    max_height = select_quality()
    sub_lang, sub_mode = select_subtitles()

    is_continuation = False
    if single:
        output_dir = resolve_single_output_dir()
    else:
        output_dir, is_continuation = resolve_playlist_output_dir(title, cfg)

    codec_label = CODECS[codec_id]["label"]
    quality_label = QUALITY_OPTIONS[
        next(k for k, v in QUALITY_OPTIONS.items() if v[1] == max_height)
    ][0]

    sub_label = sub_lang.upper() if sub_lang != "none" else "Disabled"

    console.print(Panel(
        f"[bold white]Container:[/] {container}   "
        f"[bold white]Codec:[/] {codec_label}   "
        f"[bold white]Quality:[/] {quality_label}   "
        f"[bold white]Subtitles:[/] {sub_label}",
        border_style="cyan", box=box.ROUNDED,
    ))
    console.print()

    return Downloader(
        output_dir, container, codec_id, max_height,
        single=single, total_tracks=total_tracks,
        playlist_title=title if not single else None,
        playlist_entries=playlist_entries, is_continuation=is_continuation,
        cfg=cfg, subtitles_lang=sub_lang, subtitles_mode=sub_mode,
    ).download(url)


# ─── Entry Point ──────────────────────────────────────────────────────────────

def main() -> None:
    console.clear()
    console.print(Panel(
        "[bold cyan]LOGOVO[/] [bold white]DUSHNIL[/]",
        border_style="cyan", box=box.DOUBLE, expand=False,
    ), justify="center")
    console.print("  YT Video Downloader by Helvior  ·  v1.5", style="dim white", justify="center")
    console.print()

    cfg = load_config()
    run_video_download(cfg)


if __name__ == "__main__":
    main()
