"""Tests for openspace/cloud/embedding.py — embedding API resolution."""

from __future__ import annotations
import importlib
from unittest import mock
import pytest


class TestResolveEmbeddingApi:

    def test_tier0_embedding_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("EMBEDDING_API_KEY", "emb-key")
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        import openspace.cloud.embedding as emb
        importlib.reload(emb)
        key, base = emb.resolve_embedding_api()
        assert key == "emb-key"

    def test_tier1_openrouter(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from openspace.cloud.embedding import resolve_embedding_api
        key, base = resolve_embedding_api()
        assert key == "or-key"

    def test_tier2_openai(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "oa-key")
        from openspace.cloud.embedding import resolve_embedding_api
        key, _ = resolve_embedding_api()
        assert key == "oa-key"

    def test_none_when_nothing_configured(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with mock.patch("openspace.host_detection.get_openai_api_key", return_value=None):
            from openspace.cloud.embedding import resolve_embedding_api
            key, _ = resolve_embedding_api()
            assert key is None


class TestSkillEmbeddingModel:

    def test_default_model(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
        import openspace.cloud.embedding as emb
        importlib.reload(emb)
        assert emb.SKILL_EMBEDDING_MODEL == "openai/text-embedding-3-small"

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("EMBEDDING_MODEL", "custom/model")
        import openspace.cloud.embedding as emb
        importlib.reload(emb)
        assert emb.SKILL_EMBEDDING_MODEL == "custom/model"


class TestEmbeddingUrlConfigurable:

    def test_openai_base_from_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_BASE_URL", "http://local:8080/v1")
        import openspace.cloud.embedding as emb
        importlib.reload(emb)
        assert emb._OPENAI_BASE == "http://local:8080/v1"

    def test_openrouter_base_from_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENROUTER_BASE_URL", "http://local:9090/v1")
        import openspace.cloud.embedding as emb
        importlib.reload(emb)
        assert emb._OPENROUTER_BASE == "http://local:9090/v1"

    def test_ranker_imports_from_embedding(self):
        from openspace.skill_engine import skill_ranker as r
        from openspace.cloud import embedding as e
        assert r.SKILL_EMBEDDING_MODEL == e.SKILL_EMBEDDING_MODEL
