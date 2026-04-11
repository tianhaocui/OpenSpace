"""Tests for private deployment configuration defaults."""

from __future__ import annotations
import json
from pathlib import Path
import pytest


class TestTelemetryDefault:

    def test_telemetry_default_is_opt_in(self):
        source = (Path(__file__).resolve().parents[1] / "openspace" / "utils" / "telemetry" / "telemetry.py").read_text()
        assert 'getenv("MCP_USE_ANONYMIZED_TELEMETRY", "false")' in source

    def test_no_toplevel_posthog_import(self):
        source = (Path(__file__).resolve().parents[1] / "openspace" / "utils" / "telemetry" / "telemetry.py").read_text()
        before_class = source.split("class Telemetry")[0]
        assert "from posthog" not in before_class

    def test_posthog_key_from_env(self):
        source = (Path(__file__).resolve().parents[1] / "openspace" / "utils" / "telemetry" / "telemetry.py").read_text()
        assert "POSTHOG_API_KEY" in source
        assert 'PROJECT_API_KEY = "phc_' not in source


class TestGroundingConfig:

    def test_auto_install_disabled(self):
        config_path = Path(__file__).resolve().parents[1] / "openspace" / "config" / "config_grounding.json"
        config = json.loads(config_path.read_text())
        assert config["mcp"]["auto_install"] is False


class TestMcpJson:

    def test_mcp_json_cloud_disabled(self):
        mcp_path = Path(__file__).resolve().parents[1] / ".mcp.json"
        if not mcp_path.exists():
            pytest.skip(".mcp.json not in repo root")
        config = json.loads(mcp_path.read_text())
        env = config["mcpServers"]["openspace"]["env"]
        assert env["OPENSPACE_CLOUD_ENABLED"] == "false"
        assert env["MCP_USE_ANONYMIZED_TELEMETRY"] == "false"

    def test_mcp_json_has_model(self):
        mcp_path = Path(__file__).resolve().parents[1] / ".mcp.json"
        if not mcp_path.exists():
            pytest.skip(".mcp.json not in repo root")
        config = json.loads(mcp_path.read_text())
        assert config["mcpServers"]["openspace"]["env"].get("OPENSPACE_MODEL")


class TestNoHardcodedModels:

    def test_llm_client_no_hardcoded_default(self):
        import inspect, openspace.llm.client as mod
        assert "openrouter/anthropic/claude-sonnet-4.5" not in inspect.getsource(mod)

    def test_tool_layer_no_hardcoded_default(self):
        import inspect, openspace.tool_layer as mod
        assert "openrouter/anthropic/claude-sonnet-4.5" not in inspect.getsource(mod)
