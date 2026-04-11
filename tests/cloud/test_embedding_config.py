"""Tests for P0: Embedding config unification (resolve_embedding_api + EMBEDDING_MODEL)."""

from __future__ import annotations

import importlib
import os
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# resolve_embedding_api — priority chain
# ---------------------------------------------------------------------------

class TestResolveEmbeddingApi:

    def _reload_and_call(self):
        """Re-import to pick up env changes to module-level constants."""
        import openspace.cloud.embedding as mod
        importlib.reload(mod)
        return mod.resolve_embedding_api()

    def test_tier0_embedding_env_highest_priority(self, monkeypatch: pytest.MonkeyPatch):
        """EMBEDDING_API_KEY + EMBEDDING_BASE_URL should win over everything."""
        monkeypatch.setenv("EMBEDDING_API_KEY", "emb-key-123")
        monkeypatch.setenv("EMBEDDING_BASE_URL", "https://emb.example.com/v1")
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-key-should-be-skipped")
        key, base = self._reload_and_call()
        assert key == "emb-key-123"
        assert base == "https://emb.example.com/v1"

    def test_tier0_strips_trailing_slash(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("EMBEDDING_API_KEY", "emb-key")
        monkeypatch.setenv("EMBEDDING_BASE_URL", "https://emb.example.com/v1/")
        key, base = self._reload_and_call()
        assert not base.endswith("/")

    def test_tier0_defaults_base_url(self, monkeypatch: pytest.MonkeyPatch):
        """When EMBEDDING_API_KEY set but EMBEDDING_BASE_URL not, default to OpenAI base."""
        monkeypatch.setenv("EMBEDDING_API_KEY", "emb-key")
        monkeypatch.delenv("EMBEDDING_BASE_URL", raising=False)
        key, base = self._reload_and_call()
        assert key == "emb-key"
        assert "api.openai.com" in base

    def test_tier1_openrouter(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        key, base = self._reload_and_call()
        assert key == "or-key"
        assert "openrouter" in base

    def test_tier2_openai(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "oai-key")
        key, base = self._reload_and_call()
        assert key == "oai-key"

    def test_tier3_host_agent_fallback(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with mock.patch(
            "openspace.host_detection.get_openai_api_key",
            return_value="host-key",
        ):
            key, base = self._reload_and_call()
            assert key == "host-key"

    def test_none_when_nothing_configured(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with mock.patch(
            "openspace.host_detection.get_openai_api_key",
            return_value=None,
        ):
            key, base = self._reload_and_call()
            assert key is None


# ---------------------------------------------------------------------------
# SKILL_EMBEDDING_MODEL — env override
# ---------------------------------------------------------------------------

class TestSkillEmbeddingModel:

    def test_default_model(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
        import openspace.cloud.embedding as mod
        importlib.reload(mod)
        assert mod.SKILL_EMBEDDING_MODEL == "openai/text-embedding-3-small"

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-ada-002")
        import openspace.cloud.embedding as mod
        importlib.reload(mod)
        assert mod.SKILL_EMBEDDING_MODEL == "text-embedding-ada-002"


# ---------------------------------------------------------------------------
# skill_ranker imports from embedding.py (no duplicate constant)
# ---------------------------------------------------------------------------

class TestRankerUsesSharedConstant:

    def test_ranker_imports_from_embedding(self, monkeypatch: pytest.MonkeyPatch):
        """skill_ranker should import SKILL_EMBEDDING_MODEL from embedding.py, not define its own."""
        monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
        import openspace.cloud.embedding as emb_mod
        import openspace.skill_engine.skill_ranker as ranker_mod
        importlib.reload(emb_mod)
        importlib.reload(ranker_mod)
        assert ranker_mod.SKILL_EMBEDDING_MODEL == emb_mod.SKILL_EMBEDDING_MODEL
