"""Tests for version checking utilities."""

import pytest

from galangal.core.version_check import (
    VersionInfo,
    compare_versions,
    get_update_command,
    parse_version,
)


class TestParseVersion:
    """Tests for parse_version function."""

    def test_simple_version(self):
        assert parse_version("1.2.3") == (1, 2, 3)

    def test_two_part_version(self):
        assert parse_version("1.2") == (1, 2)

    def test_four_part_version(self):
        assert parse_version("1.2.3.4") == (1, 2, 3, 4)

    def test_version_with_prerelease(self):
        # Should extract numeric portion only
        assert parse_version("1.2.3rc1") == (1, 2, 3)
        assert parse_version("1.2.3beta2") == (1, 2, 3)
        assert parse_version("1.2.3.dev1") == (1, 2, 3)

    def test_zero_version(self):
        assert parse_version("0.0.0") == (0, 0, 0)

    def test_large_version(self):
        assert parse_version("0.13.0") == (0, 13, 0)
        assert parse_version("10.20.30") == (10, 20, 30)


class TestCompareVersions:
    """Tests for compare_versions function."""

    def test_equal_versions(self):
        assert compare_versions("1.2.3", "1.2.3") == 0
        assert compare_versions("0.13.0", "0.13.0") == 0

    def test_current_older(self):
        assert compare_versions("1.2.3", "1.2.4") == -1
        assert compare_versions("1.2.3", "1.3.0") == -1
        assert compare_versions("1.2.3", "2.0.0") == -1
        assert compare_versions("0.12.0", "0.13.0") == -1

    def test_current_newer(self):
        assert compare_versions("1.2.4", "1.2.3") == 1
        assert compare_versions("1.3.0", "1.2.3") == 1
        assert compare_versions("2.0.0", "1.2.3") == 1
        assert compare_versions("0.14.0", "0.13.0") == 1

    def test_different_length_versions(self):
        # 1.2 should be same as 1.2.0
        assert compare_versions("1.2", "1.2.0") == 0
        assert compare_versions("1.2.0", "1.2") == 0

        # 1.2 should be less than 1.2.1
        assert compare_versions("1.2", "1.2.1") == -1
        assert compare_versions("1.2.1", "1.2") == 1


class TestVersionInfo:
    """Tests for VersionInfo named tuple."""

    def test_no_update_needed(self):
        info = VersionInfo(
            current="1.0.0",
            latest="1.0.0",
            update_available=False,
        )
        assert not info.update_available
        assert info.error is None

    def test_update_available(self):
        info = VersionInfo(
            current="1.0.0",
            latest="1.1.0",
            update_available=True,
        )
        assert info.update_available

    def test_with_error(self):
        info = VersionInfo(
            current="1.0.0",
            latest=None,
            update_available=False,
            error="Network error",
        )
        assert info.error == "Network error"
        assert info.latest is None


class TestGetUpdateCommand:
    """Tests for get_update_command function."""

    def test_returns_pip_command(self):
        cmd = get_update_command()
        assert "pip install" in cmd
        assert "--upgrade" in cmd
        assert "galangal-orchestrate" in cmd
