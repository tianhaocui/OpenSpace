"""Tests for openspace/setup.py — one-command registration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from openspace.setup import (
    MCP_ENV,
    copy_host_skills,
    setup_kiro,
    write_project_mcp_json,
)


class TestMcpEnvDefaults:
    """Verify privatization defaults are set."""

    def test_cloud_disabled(self):
        assert MCP_ENV["OPENSPACE_CLOUD_ENABLED"] == "false"

    def test_telemetry_disabled(self):
        assert MCP_ENV["MCP_USE_ANONYMIZED_TELEMETRY"] == "false"


class TestSetupKiro:

    def test_writes_mcp_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        kiro_dir = tmp_path / ".kiro"
        kiro_dir.mkdir()
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        result = setup_kiro()
        assert result is True

        mcp_path = kiro_dir / "settings" / "mcp.json"
        assert mcp_path.exists()
        config = json.loads(mcp_path.read_text())
        assert "openspace" in config["mcpServers"]
        assert config["mcpServers"]["openspace"]["env"] == MCP_ENV

    def test_skips_when_no_kiro(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        assert setup_kiro() is False

    def test_preserves_existing_servers(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        kiro_dir = tmp_path / ".kiro"
        settings = kiro_dir / "settings"
        settings.mkdir(parents=True)
        existing = {"mcpServers": {"other": {"command": "other-cmd"}}}
        (settings / "mcp.json").write_text(json.dumps(existing))
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        setup_kiro()

        config = json.loads((settings / "mcp.json").read_text())
        assert "other" in config["mcpServers"]
        assert "openspace" in config["mcpServers"]


class TestWriteProjectMcpJson:

    def test_writes_mcp_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)
        result = write_project_mcp_json()
        assert result is True
        config = json.loads((tmp_path / ".mcp.json").read_text())
        assert "openspace" in config["mcpServers"]

    def test_skips_if_exists(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".mcp.json").write_text("{}")
        assert write_project_mcp_json() is False


class TestCopyHostSkills:

    def test_copies_skills(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # Create fake host_skills
        host_skills = tmp_path / "host_skills"
        skill = host_skills / "my-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("name: my-skill")

        hub = tmp_path / "hub"
        monkeypatch.setattr("openspace.setup.HOST_SKILLS_DIR", host_skills)
        monkeypatch.setattr("openspace.setup.SHARED_SKILLS_HUB", hub)

        count = copy_host_skills()
        assert count == 1
        assert (hub / "my-skill" / "SKILL.md").exists()

    def test_skips_non_skill_dirs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        host_skills = tmp_path / "host_skills"
        (host_skills / "not-a-skill").mkdir(parents=True)  # no SKILL.md

        hub = tmp_path / "hub"
        monkeypatch.setattr("openspace.setup.HOST_SKILLS_DIR", host_skills)
        monkeypatch.setattr("openspace.setup.SHARED_SKILLS_HUB", hub)

        assert copy_host_skills() == 0
