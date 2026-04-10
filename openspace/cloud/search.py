"""Hybrid skill search engine (BM25 + embedding + lexical boost).

Implements the search pipeline:
  Phase 1: BM25 rough-rank over all candidates
  Phase 2: Vector scoring (embedding cosine similarity)
  Phase 3: Hybrid score = vector_score + lexical_boost
  Phase 4: Deduplication + limit

Remote search via skills.sh (Vercel's open agent skills directory)
is merged with local results when ``include_remote=True``.

Used by MCP ``search_skills`` tool, ``retrieve_skill`` agent tool,
and potentially other search interfaces.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger("openspace.cloud")
CLOUD_EMBEDDING_SEARCH_MAX_LIMIT = 300


def _check_safety(text: str) -> list[str]:
    """Lazy wrapper — avoids importing skill_engine at module load time."""
    from openspace.skill_engine.skill_utils import check_skill_safety
    return check_skill_safety(text)


def _is_safe(flags: list[str]) -> bool:
    from openspace.skill_engine.skill_utils import is_skill_safe
    return is_skill_safe(flags)

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(value: str) -> list[str]:
    return _WORD_RE.findall(value.lower()) if value else []


def _lexical_boost(query_tokens: list[str], name: str, slug: str) -> float:
    """Compute lexical boost score based on exact/prefix token matching."""
    slug_tokens = _tokenize(slug)
    name_tokens = _tokenize(name)
    boost = 0.0

    # Slug exact / prefix
    if slug_tokens and all(
        any(ct == qt for ct in slug_tokens) for qt in query_tokens
    ):
        boost += 1.4
    elif slug_tokens and all(
        any(ct.startswith(qt) for ct in slug_tokens) for qt in query_tokens
    ):
        boost += 0.8

    # Name exact / prefix
    if name_tokens and all(
        any(ct == qt for ct in name_tokens) for qt in query_tokens
    ):
        boost += 1.1
    elif name_tokens and all(
        any(ct.startswith(qt) for ct in name_tokens) for qt in query_tokens
    ):
        boost += 0.6

    return boost


class SkillSearchEngine:
    """Hybrid BM25 + embedding search engine for skills.

    Usage::

        engine = SkillSearchEngine()
        results = engine.search(
            query="weather forecast",
            candidates=candidates,
            query_embedding=[...],  # optional
            limit=20,
        )
    """

    def search(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        *,
        query_embedding: Optional[List[float]] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Run the full search pipeline on candidates.

        Each candidate dict should have at minimum:
          - ``skill_id``, ``name``, ``description``
          - ``_embedding`` (optional): pre-computed embedding vector
          - ``source``: "openspace-local" | "cloud"

        Args:
            query: Search query text.
            candidates: Candidate dicts to rank.
            query_embedding: Pre-computed query embedding (if available).
            limit: Max results to return.

        Returns:
            Sorted list of result dicts (highest score first).
        """
        q = query.strip()
        if not q or not candidates:
            return []

        query_tokens = _tokenize(q)
        if not query_tokens:
            return []

        # Phase 1: BM25 rough-rank
        filtered = self._bm25_phase(q, candidates, limit)

        # Phase 2+3: Vector + lexical scoring
        scored = self._score_phase(filtered, query_tokens, query_embedding)

        # Phase 4: Deduplicate and limit
        return self._dedup_and_limit(scored, limit)

    def _bm25_phase(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """BM25 rough-rank to keep top candidates for embedding stage."""
        from openspace.skill_engine.skill_ranker import SkillRanker, SkillCandidate

        ranker = SkillRanker(enable_cache=True)
        bm25_candidates = [
            SkillCandidate(
                skill_id=c.get("skill_id", ""),
                name=c.get("name", ""),
                description=c.get("description", ""),
                body="",
                metadata=c,
            )
            for c in candidates
        ]
        ranked = ranker.bm25_only(query, bm25_candidates, top_k=min(limit * 3, len(candidates)))

        ranked_ids = {sc.skill_id for sc in ranked}
        filtered = [c for c in candidates if c.get("skill_id") in ranked_ids]

        # If BM25 found nothing, fall back to all candidates
        return filtered if filtered else candidates

    def _score_phase(
        self,
        candidates: List[Dict[str, Any]],
        query_tokens: list[str],
        query_embedding: Optional[List[float]],
    ) -> List[Dict[str, Any]]:
        """Compute hybrid score = vector_score + lexical_boost."""
        from openspace.cloud.embedding import cosine_similarity

        scored = []
        for candidate in candidates:
            candidate_name = candidate.get("name", "")
            candidate_slug = candidate.get("skill_id", candidate_name).split("__")[0].replace(":", "-")

            # Vector score. If client-side query embeddings are unavailable,
            # reuse the server-side cloud rank so cloud results keep semantic signal.
            vector_score: Optional[float] = None
            ranking_signal_score = 0.0
            if query_embedding:
                candidate_embedding = candidate.get("_embedding")
                if candidate_embedding and isinstance(candidate_embedding, list):
                    vector_score = cosine_similarity(query_embedding, candidate_embedding)
                    ranking_signal_score = vector_score
            elif isinstance(candidate.get("_search_rank"), (int, float)):
                ranking_signal_score = float(candidate["_search_rank"])

            # Lexical boost
            lexical_boost = _lexical_boost(query_tokens, candidate_name, candidate_slug)

            final_score = ranking_signal_score + lexical_boost

            result_entry: Dict[str, Any] = {
                "skill_id": candidate.get("skill_id", ""),
                "name": candidate_name,
                "description": candidate.get("description", ""),
                "source": candidate.get("source", ""),
                "score": round(final_score, 4),
            }
            if vector_score is not None and vector_score > 0:
                result_entry["vector_score"] = round(vector_score, 4)
            if isinstance(candidate.get("_search_rank"), (int, float)):
                result_entry["server_search_rank"] = round(float(candidate["_search_rank"]), 4)
            # Include optional fields
            for key in ("path", "visibility", "created_by", "origin", "tags", "quality", "safety_flags"):
                if candidate.get(key):
                    result_entry[key] = candidate[key]
            scored.append(result_entry)

        scored.sort(key=lambda x: -x["score"])
        return scored

    @staticmethod
    def _dedup_and_limit(
        scored: List[Dict[str, Any]],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Deduplicate by name and apply limit."""
        seen: set[str] = set()
        deduped = []
        for item in scored:
            name = item["name"]
            if name in seen:
                continue
            seen.add(name)
            deduped.append(item)
        return deduped[:limit]


def build_local_candidates(
    skills: list,
    store: Any = None,
) -> List[Dict[str, Any]]:
    """Build search candidate dicts from SkillRegistry skills.

    Args:
        skills: List of ``SkillMeta`` from ``registry.list_skills()``.
        store: Optional ``SkillStore`` instance for quality data enrichment.

    Returns:
        List of candidate dicts ready for ``SkillSearchEngine.search()``.
    """
    from openspace.cloud.embedding import build_skill_embedding_text

    candidates: List[Dict[str, Any]] = []
    for s in skills:
        # Read SKILL.md body
        readme_body = ""
        try:
            raw = s.path.read_text(encoding="utf-8")
            m = re.match(r"^---\n.*?\n---\n?", raw, re.DOTALL)
            readme_body = raw[m.end():].strip() if m else raw
        except Exception:
            pass

        embedding_text = build_skill_embedding_text(s.name, s.description, readme_body)

        # Safety check
        flags = _check_safety(embedding_text)
        if not _is_safe(flags):
            logger.info(f"BLOCKED local skill {s.skill_id} — {flags}")
            continue

        candidates.append({
            "skill_id": s.skill_id,
            "name": s.name,
            "description": s.description,
            "source": "openspace-local",
            "path": str(s.path),
            "is_local": True,
            "safety_flags": flags if flags else None,
            "_embedding_text": embedding_text,
        })

    # Enrich with quality data
    if store and candidates:
        try:
            all_records = store.load_all(active_only=True)
            for c in candidates:
                rec = all_records.get(c["skill_id"])
                if rec:
                    c["quality"] = {
                        "total_selections": rec.total_selections,
                        "completion_rate": round(rec.completion_rate, 3),
                        "effective_rate": round(rec.effective_rate, 3),
                    }
                    c["tags"] = rec.tags
        except Exception as e:
            logger.warning(f"Quality lookup failed: {e}")

    return candidates


_SKILLS_SH_API = "https://skills.sh/api/search"
_SKILLS_SH_TIMEOUT = 5


def _search_skills_sh(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Search skills.sh (Vercel's open agent skills directory).

    Returns candidate dicts compatible with ``SkillSearchEngine.search()``.
    Failures are silently swallowed — this is a best-effort remote search.
    """
    try:
        url = f"{_SKILLS_SH_API}?q={urllib.request.quote(query)}&limit={limit}"
        req = urllib.request.Request(url, headers={"User-Agent": "OpenSpace/1.0"})
        with urllib.request.urlopen(req, timeout=_SKILLS_SH_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.debug("skills.sh search failed (non-fatal): %s", e)
        return []

    results: List[Dict[str, Any]] = []
    for skill in data.get("skills", []):
        name = skill.get("name", "")
        source = skill.get("source", "")
        slug = skill.get("id", "")
        if not name:
            continue
        results.append({
            "skill_id": f"skills-sh:{slug}",
            "name": name,
            "description": f"From skills.sh — install: npx skills add {source}@{name}",
            "source": "skills.sh",
            "is_local": False,
            "installs": skill.get("installs", 0),
            "install_command": f"npx skills add {source}@{name}" if source else f"npx skills add {slug}",
            "url": f"https://skills.sh/{slug}",
        })
    return results


async def hybrid_search_skills(
    query: str,
    local_skills: list = None,
    store: Any = None,
    source: str = "local",
    limit: int = 20,
    include_remote: bool = False,
) -> List[Dict[str, Any]]:
    """Local skill search with optional skills.sh remote results.

    Builds candidates, generates embeddings, runs ``SkillSearchEngine``.
    When *include_remote* is True, skills.sh results are appended after
    local results (local always takes priority).

    Args:
        query: Free-text search query.
        local_skills: ``SkillMeta`` list (from ``registry.list_skills()``).
        store: Optional ``SkillStore`` for quality enrichment.
        source: ``"local"`` (only local supported now).
        limit: Maximum results.
        include_remote: If True, also search skills.sh and append results.

    Returns:
        Ranked result dicts (same format as ``SkillSearchEngine.search()``).
    """
    from openspace.cloud.embedding import generate_embedding

    normalized_query = query.strip()
    if not normalized_query:
        return []

    candidates: List[Dict[str, Any]] = []

    if source in ("all", "local") and local_skills:
        candidates.extend(build_local_candidates(local_skills, store))

    if not candidates:
        return []

    # query embedding (optional — key/URL resolved inside generate_embedding)
    query_embedding: Optional[List[float]] = None
    try:
        query_embedding = await asyncio.to_thread(generate_embedding, normalized_query)
        if query_embedding:
            for candidate in candidates:
                if not candidate.get("_embedding") and candidate.get("_embedding_text"):
                    candidate_embedding = await asyncio.to_thread(
                        generate_embedding, candidate["_embedding_text"],
                    )
                    if candidate_embedding:
                        candidate["_embedding"] = candidate_embedding
    except Exception:
        pass

    engine = SkillSearchEngine()
    results = engine.search(normalized_query, candidates, query_embedding=query_embedding, limit=limit)

    # Append skills.sh remote results (after local, best-effort)
    if include_remote:
        local_names = {r["name"].lower() for r in results}
        try:
            remote = await asyncio.to_thread(_search_skills_sh, normalized_query, limit)
            for r in remote:
                if r["name"].lower() not in local_names:
                    results.append({
                        "skill_id": r["skill_id"],
                        "name": r["name"],
                        "description": r["description"],
                        "source": "skills.sh",
                        "score": 0,
                        "installs": r.get("installs", 0),
                        "install_command": r.get("install_command", ""),
                        "url": r.get("url", ""),
                    })
        except Exception:
            pass

    return results[:limit]
