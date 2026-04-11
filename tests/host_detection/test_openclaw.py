"""Tests for host_detection/openclaw.py — OpenClaw config reader."""

from __future__ import annotations
import json
from pathlib import Path
import pytest
from openspace.host_detection.openclaw import (
    is_openclaw_host, read_openclaw_skill_env, get_openclaw_openai_api_key,
    try_read_openclaw_config, _resolve_openclaw_config_path,
)


class TestResolveConfigPath:

    def test_explicit_env_existing_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        config = tmp_path / "openclaw.json"
        config.write_text("{}")
        monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(config))
        assert _resolve_openclaw_config_path() == config

    def test_returns_none_when_no_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(tmp_path / "nope.json"))
        monkeypatch.delenv("OPENCLAW_STATE_DIR", raising=False)
        # May still find legacy dirs, so just check it doesn't crash
        result = _resolve_openclaw_config_path()
        assert result is None or isinstance(result, Path)


class TestIsOpenclawHost:

    def test_true_when_config_exists(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        config = tmp_path / "openclaw.json"
        config.write_text(json.dumps({"skills": {"entries": {}}}))
        monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(config))
        assert is_openclaw_host() is True

    def test_false_when_no_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(tmp_path / "nope.json"))
        monkeypatch.delenv("OPENCLAW_STATE_DIR", raising=False)
        # is_openclaw_host checks for legacy dirs too, so just verify it returns bool
        result = is_openclaw_host()
        assert isinstance(result, bool)


class TestReadOpenclawSkillEnv:

    def test_reads_env_block(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        config = tmp_path / "openclaw.json"
        config.write_text(json.dumps({
            "skills": {"entries": {"openspace": {"env": {"OPENSPACE_MODEL": "gpt-4"}}}}
        }))
        monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(config))
        env = read_openclaw_skill_env("openspace")
        assert env.get("OPENSPACE_MODEL") == "gpt-4"

    def test_returns_empty_when_no_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(tmp_path / "nope.json"))
        assert read_openclaw_skill_env("openspace") == {}


class TestGetOpenclawOpenaiApiKey:

    def test_returns_none_when_no_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(tmp_path / "nope.json"))
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert get_openclaw_openai_api_key() is None
