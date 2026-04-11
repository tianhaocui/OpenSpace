"""Tests for cloud/cli/skillpull_sync.py — Git-based skill sync."""

from __future__ import annotations
import json
from pathlib import Path
import pytest
from openspace.cloud.cli.skillpull_sync import (
    SIDECAR_FILES, SKILLPULL_MANIFEST, SkillpullResult, _read_manifest, get_target_dir,
)


class TestSkillpullResult:

    def test_ok_when_zero(self):
        assert SkillpullResult(returncode=0, stdout="done", stderr="").ok is True

    def test_not_ok_when_nonzero(self):
        assert SkillpullResult(returncode=1, stdout="", stderr="error").ok is False


class TestGetTargetDir:

    def test_uses_host_skill_dirs_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        d = tmp_path / "host_skills"
        d.mkdir()
        monkeypatch.setenv("OPENSPACE_HOST_SKILL_DIRS", str(d))
        assert get_target_dir() == d

    def test_uses_first_dir_from_csv(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        d1 = tmp_path / "first"
        d1.mkdir()
        d2 = tmp_path / "second"
        d2.mkdir()
        monkeypatch.setenv("OPENSPACE_HOST_SKILL_DIRS", f"{d1},{d2}")
        assert get_target_dir() == d1

    def test_falls_back_to_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("OPENSPACE_HOST_SKILL_DIRS", raising=False)
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)
        assert get_target_dir() == tmp_path / ".openspace" / "skills"


class TestReadManifest:

    def test_reads_valid_manifest(self, tmp_path: Path):
        (tmp_path / SKILLPULL_MANIFEST).write_text(json.dumps({"skills": {"s": {}}}))
        assert _read_manifest(tmp_path) == {"skills": {"s": {}}}

    def test_returns_empty_when_missing(self, tmp_path: Path):
        assert _read_manifest(tmp_path) == {}

    def test_returns_empty_on_invalid_json(self, tmp_path: Path):
        (tmp_path / SKILLPULL_MANIFEST).write_text("not json{{{")
        assert _read_manifest(tmp_path) == {}


class TestSidecarFiles:

    def test_sidecar_constants(self):
        assert ".skill_id" in SIDECAR_FILES
        assert ".upload_meta.json" in SIDECAR_FILES
