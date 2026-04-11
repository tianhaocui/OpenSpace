"""Tests for simplified resolver — env-only LLM credential resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openspace.host_detection.resolver import (
    build_llm_kwargs,
    _infer_provider_name,
)
from openspace.host_detection import get_openai_api_key, read_host_mcp_env


class TestGetOpenaiApiKey:

    def test_reads_from_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
        assert get_openai_api_key() == "sk-test-123"

    def test_returns_none_when_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert get_openai_api_key() is None

    def test_strips_whitespace(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "  sk-test  ")
        assert get_openai_api_key() == "sk-test"


class TestReadHostMcpEnv:
    """Stub should always return empty dict."""

    def test_returns_empty(self):
        assert read_host_mcp_env() == {}


class TestInferProviderName:

    def test_openrouter_prefix(self):
        assert _infer_provider_name("openrouter/anthropic/claude-sonnet-4") == "openrouter"

    def test_anthropic_prefix(self):
        assert _infer_provider_name("anthropic/claude-sonnet-4") == "anthropic"

    def test_keyword_match(self):
        assert _infer_provider_name("gpt-4o") == "openai"

    def test_deepseek(self):
        assert _infer_provider_name("deepseek/deepseek-chat") == "deepseek"

    def test_unknown(self):
        assert _infer_provider_name("some-random-model") is None


class TestBuildLlmKwargs:

    def test_tier1_explicit_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENSPACE_LLM_API_KEY", "sk-explicit")
        monkeypatch.setenv("OPENSPACE_LLM_API_BASE", "https://my-proxy.com/v1")
        model, kwargs = build_llm_kwargs("gpt-4")
        assert model == "gpt-4"
        assert kwargs["api_key"] == "sk-explicit"
        assert kwargs["api_base"] == "https://my-proxy.com/v1"

    def test_model_from_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENSPACE_MODEL", "anthropic/claude-sonnet-4")
        monkeypatch.delenv("OPENSPACE_LLM_API_KEY", raising=False)
        model, kwargs = build_llm_kwargs("")
        assert model == "anthropic/claude-sonnet-4"

    def test_ollama_special_handling(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("OPENSPACE_LLM_API_KEY", raising=False)
        monkeypatch.delenv("OLLAMA_API_BASE", raising=False)
        model, kwargs = build_llm_kwargs("ollama/llama3")
        assert model == "ollama/llama3"
        assert kwargs["api_base"] == "http://127.0.0.1:11434"
        assert kwargs["api_key"] == "ollama"

    def test_extra_headers_json(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENSPACE_LLM_EXTRA_HEADERS", '{"X-Custom": "value"}')
        _, kwargs = build_llm_kwargs("gpt-4")
        assert kwargs.get("extra_headers") == {"X-Custom": "value"}

    def test_no_host_config_files_read(self, monkeypatch: pytest.MonkeyPatch):
        """Resolver should NOT read any host config files (hermes/nanobot/openclaw)."""
        monkeypatch.delenv("OPENSPACE_LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENSPACE_MODEL", raising=False)
        # Even with fake config files, resolver should not touch them
        model, kwargs = build_llm_kwargs("")
        # No api_key should be resolved from config files
        assert "api_key" not in kwargs
