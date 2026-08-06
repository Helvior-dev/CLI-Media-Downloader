import sys
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from yt_music_downloader import load_config, save_config, run_once as run_music_download, show_folder_stats
from yt_video_downloader import run_video_download, send_windows_notification

console = Console()

SPEED_LIMITS = {
    "1": ("Unlimited (Default)", None),
    "2": ("5 MB/s", 5),
    "3": ("10 MB/s", 10),
    "4": ("20 MB/s", 20),
    "5": ("50 MB/s", 50),
    "6": ("Custom MB/s limit...", "custom"),
}


def ask(prompt: str, choices: list[str], default: str) -> str:
    return Prompt.ask(f"[bold cyan]  {prompt}[/]", choices=choices, default=default)


def configure_speed_limit(cfg: dict) -> None:
    current = f"{cfg.get('speed_limit_mb')} MB/s" if cfg.get("speed_limit_mb") else "Unlimited"
    lines = [f"[bold white]{k}[/]  {v[0]}" for k, v in SPEED_LIMITS.items()]
    console.print(Panel(
        "\n".join(lines) + f"\n\n[dim]Current speed limit:[/] [bold cyan]{current}[/]",
        title="[bold cyan]Bandwidth & Speed Limit[/]",
        border_style="cyan", box=box.ROUNDED, width=60,
    ))
    choice = ask("Select speed limit", list(SPEED_LIMITS.keys()), "1")
    val = SPEED_LIMITS[choice][1]

    if val == "custom":
        custom_val = Prompt.ask("[bold cyan]  Enter limit in MB/s (e.g. 15)[/]").strip()
        try:
            val = float(custom_val)
        except ValueError:
            val = None

    cfg["speed_limit_mb"] = val
    save_config(cfg)
    label = f"{val} MB/s" if val else "Unlimited"
    console.print(f"[bold green]  ✔  Speed limit set to:[/] [bold]{label}[/]\n")


def toggle_notifications(cfg: dict) -> None:
    current = cfg.get("notifications_enabled", True)
    new_val = not current
    cfg["notifications_enabled"] = new_val
    save_config(cfg)
    status = "[bold green]Enabled[/]" if new_val else "[bold yellow]Disabled[/]"
    console.print(f"[bold green]  ✔  Windows Desktop Notifications:[/] {status}\n")
    if new_val:
        send_windows_notification("LogovoDushnil", "Desktop notifications enabled!")


def show_settings_menu(cfg: dict) -> None:
    while True:
        speed_str = f"{cfg.get('speed_limit_mb')} MB/s" if cfg.get("speed_limit_mb") else "Unlimited"
        notify_str = "ON" if cfg.get("notifications_enabled", True) else "OFF"

        console.print(Panel(
            f"[bold white]1[/]  Speed Limit           [dim](limit download bandwidth · Current: {speed_str})[/]\n"
            f"[bold white]2[/]  Desktop Notifications [dim](Windows balloon popups · Current: {notify_str})[/]\n"
            f"[bold white]3[/]  Back to Main Menu",
            title="[bold cyan]Settings & Configuration[/]", border_style="cyan", box=box.ROUNDED, width=72,
        ))
        choice = ask("Select setting", ["1", "2", "3"], "3")
        console.print()

        if choice == "3":
            break
        if choice == "1":
            configure_speed_limit(cfg)
        elif choice == "2":
            toggle_notifications(cfg)


def main() -> None:
    console.clear()
    console.print(Panel(
        "[bold cyan]LOGOVO[/] [bold white]DUSHNIL[/]\n[dim white]Media Downloader Suite v2.0[/]",
        border_style="cyan", box=box.DOUBLE, expand=False,
    ), justify="center")
    console.print("  YT Audio & Video Sync Engine by Helvior", style="dim white", justify="center")
    console.print()

    cfg = load_config()

    while True:
        console.print(Panel(
            "[bold white]1[/]  Download music  [dim](FLAC / ALAC / WAV / MP3 / AAC / Opus)[/]\n"
            "[bold white]2[/]  Download video  [dim](MP4 / MKV / WEBM · Subtitles · Posters · 1080p / 4K)[/]\n"
            "[bold white]3[/]  Folder stats / History  [dim](check sync status & session logs)[/]\n"
            "[bold white]4[/]  Settings  [dim](Bandwidth Limits · Desktop Notifications)[/]\n"
            "[bold white]5[/]  Exit",
            title="[bold cyan]Main Menu[/]", border_style="cyan", box=box.ROUNDED, width=72,
        ))
        choice = ask("Select action", ["1", "2", "3", "4", "5"], "1")
        console.print()

        if choice == "5":
            console.print("[dim]  Goodbye![/]")
            break

        if choice == "4":
            show_settings_menu(cfg)
            console.print()
            continue

        if choice == "3":
            show_folder_stats(cfg)
            console.print()
            continue

        if choice == "1":
            console.print("[bold cyan]─── Download Music ──────────────────────────────────────────[/]\n")
            success = run_music_download(cfg)
            console.print()
            if success:
                console.print("[bold green]  ✔  Successfully completed.[/] [dim]Back at the main menu.[/]")
            else:
                console.print("[bold yellow]  ⚠  Finished with errors.[/] [dim]Back at the main menu.[/]")
            console.print()
            continue

        if choice == "2":
            console.print("[bold cyan]─── Download Video ──────────────────────────────────────────[/]\n")
            success = run_video_download(cfg)
            console.print()
            if success:
                console.print("[bold green]  ✔  Successfully completed.[/] [dim]Back at the main menu.[/]")
            else:
                console.print("[bold yellow]  ⚠  Finished with errors.[/] [dim]Back at the main menu.[/]")
            console.print()
            continue


if __name__ == "__main__":
    main()
