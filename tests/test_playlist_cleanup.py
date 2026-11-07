"""Tests for playlist cleanup without contacting YouTube or deleting user files."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yt_music_downloader import hidden_path, sync_remove_deleted


TEST_TEMP_DIR = Path(tempfile.gettempdir()) / "opencode"


class PlaylistCleanupTests(unittest.TestCase):
    def test_only_confirmed_removed_track_is_offered_for_deletion(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_DIR) as directory:
            folder = Path(directory)
            archive = hidden_path(folder, "downloaded_archive.txt")
            archive.write_text("youtube removed-id\nyoutube active-id\n", encoding="utf-8")
            removed = folder / "removed.mp3"
            unknown = folder / "personal-recording.mp3"
            active = folder / "active.mp3"
            for path in (removed, unknown, active):
                path.write_bytes(b"test")

            with patch("yt_music_downloader.Confirm.ask", return_value=True) as confirm, \
                 patch("yt_music_downloader.console.print"):
                sync_remove_deleted(
                    folder, "mp3", [{"id": "active-id"}], {},
                    {"removed": "removed-id", "active": "active-id"},
                )

            confirm.assert_called_once()
            self.assertFalse(removed.exists())
            self.assertTrue(unknown.exists())
            self.assertTrue(active.exists())

    def test_missing_id_map_never_offers_deletion(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_DIR) as directory:
            folder = Path(directory)
            hidden_path(folder, "downloaded_archive.txt").write_text("youtube removed-id\n", encoding="utf-8")
            unknown = folder / "personal-recording.mp3"
            unknown.write_bytes(b"test")

            with patch("yt_music_downloader.Confirm.ask") as confirm:
                sync_remove_deleted(folder, "mp3", [{"id": "active-id"}], {}, {})

            confirm.assert_not_called()
            self.assertTrue(unknown.exists())


if __name__ == "__main__":
    unittest.main()
