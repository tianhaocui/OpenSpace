"""Tests for host_detection/hermes.py — Hermes Agent config reader."""

from __future__ import annotations
from pathlib import Path
import pytest
from openspace.host_detection.hermes import (
    _resolve_config_path, _resolve_hermes_home, is_hermes_host,
    read_hermes_mcp_env, try_read_hermes_config, get_hermes_openai_api_key,
)


class TestResolveHermesHome:

    def test_default_home(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("HERMES_HOME", raising=False)
        assert _resolve_hermes_home() == Path.home() / ".hermes"

    def test_explicit_home(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("HERMES_HOME", "/custom/hermes")
        assert _resolve_hermes_home() == Path("/custom/hermes")


class TestResolveConfigPath:

    def test_default_config(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("HERMES_CONFIG_PATH", raising=False)
        monkeypatch.delenv("HERMES_HOME", raising=False)
        assert _resolve_config_path() == Path.home() / ".hermes" / "config.yaml"

    def test_explicit_config(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("HERMES_CONFIG_PATH", "/etc/hermes.yaml")
        assert _resolve_config_path() == Path("/etc/hermes.yaml")


class TestIsHermesHost:

    def test_true_when_config_exists(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        config = tmp_path / "config.yaml"
        config.write_text("model:\n  provider: openai\n")
        monkeypatch.setenv("HERMES_CONFIG_PATH", str(config))
        assert is_hermes_host() is True

    def test_false_when_no_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("HERMES_CONFIG_PATH", str(tmp_path / "nope.yaml"))
        assert is_hermes_host() is False


class TestReadHermesMcpEnv:

    def test_reads_env_block(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        config = tmp_path / "config.yaml"
        config.write_text("mcp_servers:\n  openspace:\n    env:\n      OPENSPACE_API_KEY: hermes-key\n")
        monkeypatch.setenv("HERMES_CONFIG_PATH", str(config))
        assert read_hermes_mcp_env("openspace") == {"OPENSPACE_API_KEY": "hermes-key"}

    def test_returns_empty_when_no_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("HERMES_CONFIG_PATH", str(tmp_path / "nope.yaml"))
        assert read_hermes_mcp_env() == {}


class TestTryReadHermesConfig:

    def test_extracts_model_and_api_key(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        config = tmp_path / "config.yaml"
        config.write_text(
            "model:\n  provider: openrouter\n  default: anthropic/claude-sonnet-4\n"
            "  api_key: sk-or-test\n  base_url: https://openrouter.ai/api/v1\n"
        )
        monkeypatch.setenv("HERMES_CONFIG_PATH", str(config))
        result = try_read_hermes_config("")
        assert result["api_key"] == "sk-or-test"
        assert result["_model"] == "anthropic/claude-sonnet-4"
        assert result["_forced_provider"] == "openrouter"

    def test_returns_none_when_no_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("HERMES_CONFIG_PATH", str(tmp_path / "nope.yaml"))
        assert try_read_hermes_config("") is None


class TestGetHermesOpenaiApiKey:

    def test_prefers_env_var(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
        assert get_hermes_openai_api_key() == "sk-from-env"

    def test_returns_none_when_nothing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("HERMES_CONFIG_PATH", str(tmp_path / "nope.yaml"))
        assert get_hermes_openai_api_key() is None
