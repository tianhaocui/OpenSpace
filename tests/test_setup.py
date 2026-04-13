"""Tests for openspace/setup.py — one-command registration."""

from __future__ import annotations
import json
from pathlib import Path
import pytest
from openspace.setup import MCP_ENV, copy_host_skills, setup_kiro, write_project_mcp_json


class TestMcpEnvDefaults:

    def test_cloud_disabled(self):
        assert MCP_ENV["OPENSPACE_CLOUD_ENABLED"] == "false"

    def test_telemetry_disabled(self):
        assert MCP_ENV["MCP_USE_ANONYMIZED_TELEMETRY"] == "false"


class TestSetupKiro:

    def test_writes_mcp_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        kiro_dir = tmp_path / ".kiro"
        kiro_dir.mkdir()
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        assert setup_kiro("openspace-mcp") is True
        config = json.loads((kiro_dir / "settings" / "mcp.json").read_text())
        assert "openspace" in config["mcpServers"]

    def test_skips_when_no_kiro(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        assert setup_kiro("openspace-mcp") is False

    def test_preserves_existing_servers(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        kiro_dir = tmp_path / ".kiro"
        settings = kiro_dir / "settings"
        settings.mkdir(parents=True)
        (settings / "mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        setup_kiro("openspace-mcp")
        config = json.loads((settings / "mcp.json").read_text())
        assert "other" in config["mcpServers"]
        assert "openspace" in config["mcpServers"]


class TestWriteProjectMcpJson:

    def test_writes_mcp_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)
        assert write_project_mcp_json("openspace-mcp") is True
        assert (tmp_path / ".mcp.json").exists()

    def test_skips_if_exists(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".mcp.json").write_text("{}")
        assert write_project_mcp_json("openspace-mcp") is False


class TestCopyHostSkills:

    def test_copies_skills(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        host_skills = tmp_path / "host_skills"
        skill = host_skills / "my-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("name: my-skill")
        hub = tmp_path / "hub"
        monkeypatch.setattr("openspace.setup.HOST_SKILLS_DIR", host_skills)
        monkeypatch.setattr("openspace.setup.SHARED_SKILLS_HUB", hub)
        assert copy_host_skills() == 1

    def test_skips_non_skill_dirs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        host_skills = tmp_path / "host_skills"
        (host_skills / "not-a-skill").mkdir(parents=True)
        hub = tmp_path / "hub"
        monkeypatch.setattr("openspace.setup.HOST_SKILLS_DIR", host_skills)
        monkeypatch.setattr("openspace.setup.SHARED_SKILLS_HUB", hub)
        assert copy_host_skills() == 0
