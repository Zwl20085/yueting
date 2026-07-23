"""Tests for runtime configuration."""
from pathlib import Path
from unittest.mock import patch

from yueting import config


class TestDataDir:
    def test_respects_yueting_home_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("YUETING_HOME", str(tmp_path / "custom"))
        assert config.data_dir() == tmp_path / "custom"
        assert (tmp_path / "custom").is_dir()  # 自动创建

    def test_db_path_inside_data_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("YUETING_HOME", str(tmp_path))
        assert config.db_path() == tmp_path / "library.db"


class TestFindMpv:
    def test_prefers_path_lookup(self):
        with patch("yueting.config.shutil.which", return_value="C:/tools/mpv.exe"):
            assert config.find_mpv() == "C:/tools/mpv.exe"

    def test_falls_back_to_known_locations(self, tmp_path):
        fake_mpv = tmp_path / "mpv.exe"
        fake_mpv.write_bytes(b"")
        with (
            patch("yueting.config.shutil.which", return_value=None),
            patch("yueting.config._WINDOWS_MPV_CANDIDATES", (fake_mpv,)),
        ):
            assert config.find_mpv() == str(fake_mpv)

    def test_returns_none_when_absent(self):
        with (
            patch("yueting.config.shutil.which", return_value=None),
            patch("yueting.config._WINDOWS_MPV_CANDIDATES", (Path("Z:/nope/mpv.exe"),)),
        ):
            assert config.find_mpv() is None
