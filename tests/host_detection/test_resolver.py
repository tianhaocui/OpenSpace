"""Tests for resolver.py — LLM credential resolution."""

from __future__ import annotations
import pytest
from openspace.host_detection.resolver import build_llm_kwargs, _DEFAULT_MODEL


class TestDefaultModel:

    def test_default_model_value(self):
        assert _DEFAULT_MODEL == ""


class TestBuildLlmKwargs:

    def test_tier1_explicit_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENSPACE_LLM_API_KEY", "sk-explicit")
        monkeypatch.setenv("OPENSPACE_LLM_API_BASE", "https://my-proxy.com/v1")
        model, kwargs = build_llm_kwargs("gpt-4")
        assert model == "gpt-4"
        assert kwargs["api_key"] == "sk-explicit"
        assert kwargs["api_base"] == "https://my-proxy.com/v1"

    def test_falls_back_to_default_when_no_keys(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("OPENSPACE_LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENSPACE_LLM_API_BASE", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        model, _ = build_llm_kwargs("")
        assert model == _DEFAULT_MODEL

    def test_ollama_special_handling(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("OPENSPACE_LLM_API_KEY", raising=False)
        monkeypatch.delenv("OLLAMA_API_BASE", raising=False)
        model, kwargs = build_llm_kwargs("ollama/llama3")
        assert model == "ollama/llama3"
        assert kwargs["api_base"] == "http://127.0.0.1:11434"
        assert kwargs["api_key"] == "ollama"
