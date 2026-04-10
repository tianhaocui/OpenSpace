"""Cloud platform integration (local-only mode).

Provides:
  - ``SkillSearchEngine`` — hybrid BM25 + embedding search (local skills)
  - ``generate_embedding`` — embedding generation
"""


def __getattr__(name: str):
    if name == "SkillSearchEngine":
        from openspace.cloud.search import SkillSearchEngine
        return SkillSearchEngine
    if name == "generate_embedding":
        from openspace.cloud.embedding import generate_embedding
        return generate_embedding
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "SkillSearchEngine",
    "generate_embedding",
]
