import os
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
ICON_PATH = BASE_DIR / "media" / "icon.ico"
MAIN_SCRIPT = BASE_DIR / "main.py"
FFMPEG_PATH = BASE_DIR / "ffmpeg.exe"
DIST_DIR = BASE_DIR / "dist"
BUILD_DIR = BASE_DIR / "build"


def build_executable() -> None:
    print("=" * 60)
    print("  Building LogovoDushnil Standalone Executable (PyInstaller)")
    print("=" * 60)

    if not ICON_PATH.exists():
        print(f"[!] Warning: Icon file not found at {ICON_PATH}")

    if not FFMPEG_PATH.exists():
        print(f"[!] Warning: ffmpeg.exe not found at {FFMPEG_PATH}")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--console",
        f"--name=LogovoDushnil",
    ]

    if ICON_PATH.exists():
        cmd.append(f"--icon={ICON_PATH}")

    if FFMPEG_PATH.exists():
        cmd.append(f"--add-binary={FFMPEG_PATH};.")

    cmd.append(str(MAIN_SCRIPT))

    print(f"\n[+] Executing PyInstaller command: {' '.join(cmd)}\n")
    result = subprocess.run(cmd)

    if result.returncode == 0:
        exe_path = DIST_DIR / "LogovoDushnil" / "LogovoDushnil.exe"
        print("\n" + "=" * 60)
        print("  BUILD SUCCESSFUL!")
        print(f"  Executable location: {exe_path}")
        print("=" * 60 + "\n")
    else:
        print("\n[!] Build failed with exit code:", result.returncode)


if __name__ == "__main__":
    build_executable()
