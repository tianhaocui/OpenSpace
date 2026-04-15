#!/usr/bin/env python3
"""Stop Hook — auto-report skill usage to OpenSpace.

Works with both Codex and Claude Code.  Reads the session transcript,
identifies which skills were loaded and referenced by the assistant,
then calls ``openspace-report`` for each.

Designed to run as a ``Stop`` event hook.  Receives a JSON payload
on stdin with ``transcript_path`` and ``session_id``.

Transcript format detection:
  - Codex:      entries have ``type: "response_item"`` with ``payload.role``
  - Claude Code: entries have ``type: "user"`` / ``type: "assistant"`` at top level

Exit behaviour:
  - Prints a JSON object to stdout (hook protocol).
  - Never blocks the session from stopping (no ``decision: block``).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# Skills injected by Codex system (not user-installed)
_SYSTEM_SKILLS = frozenset({
    "imagegen", "openai-docs", "plugin-creator",
    "skill-creator", "skill-installer",
})

# MCP tool names that indicate the agent already reported manually
_MANUAL_REPORT_TOOLS = frozenset({
    "report_skill_usage", "fix_skill",
})

_SKILL_PATH_RE = re.compile(r"skills/([a-zA-Z0-9_.-]+)/SKILL\.md")
# Claude Code lists skills as "- skill-name: description..." in system-reminder
_SKILL_LIST_RE = re.compile(r"^- ([a-zA-Z0-9_-]+):", re.MULTILINE)
# skill-evolution skill outputs: [A] skill-name — reason
_EVAL_RE = re.compile(
    r"\[([ABCF])\]\s+([a-zA-Z0-9_-]+)\s*[—–\-]\s*(.+?)(?:\n|$)"
)


def _parse_payload() -> dict[str, Any]:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def _load_transcript(path: str | None) -> list[dict]:
    if not path:
        return []
    p = Path(path)
    if not p.is_file():
        return []
    entries: list[dict] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _detect_format(entries: list[dict]) -> str:
    """Detect transcript format: 'codex' or 'claude'."""
    for entry in entries[:20]:
        if entry.get("type") == "response_item":
            return "codex"
        if entry.get("type") in ("user", "assistant"):
            return "claude"
    return "unknown"


def _get_text_blocks(entry: dict, fmt: str, role_filter: str) -> list[str]:
    """Extract text blocks from an entry matching the given role."""
    texts: list[str] = []
    if fmt == "codex":
        if entry.get("type") != "response_item":
            return texts
        payload = entry.get("payload", {})
        if payload.get("role") != role_filter:
            return texts
        for c in payload.get("content", []):
            if isinstance(c, dict):
                texts.append(c.get("text", ""))
    elif fmt == "claude":
        if entry.get("type") != role_filter:
            return texts
        msg = entry.get("message", {})
        content = msg.get("content", []) if isinstance(msg, dict) else []
        for c in (content if isinstance(content, list) else []):
            if isinstance(c, dict) and c.get("type") in ("text", "input_text", "output_text"):
                texts.append(c.get("text", ""))
    return texts


def _extract_loaded_skills(entries: list[dict], fmt: str = "") -> set[str]:
    """Extract skill names from system/developer messages."""
    if not fmt:
        fmt = _detect_format(entries)
    skills: set[str] = set()
    # Codex: skills in developer messages; Claude Code: skills in user messages (system-reminder)
    role = "developer" if fmt == "codex" else "user"
    for entry in entries:
        for text in _get_text_blocks(entry, fmt, role):
            # Pattern 1: SKILL.md file paths (Codex primary, Claude Code sometimes)
            for m in _SKILL_PATH_RE.finditer(text):
                name = m.group(1)
                if name not in _SYSTEM_SKILLS and not name.startswith("."):
                    skills.add(name)
            # Pattern 2: "- skill-name: description" list in system-reminder (Claude Code)
            if fmt == "claude" and "skills are available" in text.lower():
                for m in _SKILL_LIST_RE.finditer(text):
                    name = m.group(1)
                    if name not in _SYSTEM_SKILLS and not name.startswith("."):
                        skills.add(name)
    return skills


def _extract_assistant_skill_refs(
    entries: list[dict], loaded: set[str], fmt: str = "",
) -> set[str]:
    """Find which loaded skills the assistant actually referenced."""
    if not fmt:
        fmt = _detect_format(entries)
    referenced: set[str] = set()
    for entry in entries:
        for text in _get_text_blocks(entry, fmt, "assistant"):
            text_lower = text.lower()
            for skill in loaded:
                if skill.lower() in text_lower:
                    referenced.add(skill)
    return referenced


def _check_manual_reports(entries: list[dict], fmt: str = "") -> set[str]:
    """Find skills already reported via MCP tool calls."""
    if not fmt:
        fmt = _detect_format(entries)
    reported: set[str] = set()

    for entry in entries:
        if fmt == "codex":
            if entry.get("type") != "response_item":
                continue
            payload = entry.get("payload", {})
            if payload.get("type") != "function_call":
                continue
            name = payload.get("name", "")
            if name not in _MANUAL_REPORT_TOOLS:
                continue
            args_str = payload.get("arguments", "")
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except json.JSONDecodeError:
                continue
            skill_name = args.get("skill_name", "") if isinstance(args, dict) else ""
            if skill_name:
                reported.add(skill_name)

        elif fmt == "claude":
            if entry.get("type") != "assistant":
                continue
            msg = entry.get("message", {})
            content = msg.get("content", []) if isinstance(msg, dict) else []
            for c in (content if isinstance(content, list) else []):
                if not isinstance(c, dict) or c.get("type") != "tool_use":
                    continue
                name = c.get("name", "")
                if name not in _MANUAL_REPORT_TOOLS:
                    continue
                inp = c.get("input", {})
                skill_name = inp.get("skill_name", "") if isinstance(inp, dict) else ""
                if skill_name:
                    reported.add(skill_name)

    return reported


def _extract_skill_evaluations(
    entries: list[dict], fmt: str = "",
) -> dict[str, tuple[str, str]]:
    """Extract skill evaluations from assistant messages.

    The skill-evolution skill outputs lines like:
        [B] git-commit — missing amend example → evolving
        [A] skillpull — accurate and complete, no changes needed

    Returns {skill_name: (score, reason)}.
    """
    if not fmt:
        fmt = _detect_format(entries)
    evals: dict[str, tuple[str, str]] = {}
    for entry in entries:
        for text in _get_text_blocks(entry, fmt, "assistant"):
            for m in _EVAL_RE.finditer(text):
                score, name, reason = m.group(1), m.group(2), m.group(3).strip()
                evals[name] = (score, reason)
    return evals


def _report_skill(skill_name: str, note: str = "") -> bool:
    """Call openspace-report CLI for a single skill."""
    cmd = shutil.which("openspace-report")
    if not cmd:
        return False
    try:
        args = [cmd, skill_name]
        if note:
            args.extend(["--note", note])
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _report_skill_failed(skill_name: str, note: str = "") -> bool:
    """Call openspace-report CLI with --failed flag."""
    cmd = shutil.which("openspace-report")
    if not cmd:
        return False
    try:
        args = [cmd, skill_name, "--failed"]
        if note:
            args.extend(["--note", note])
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def main() -> None:
    payload = _parse_payload()
    transcript_path = payload.get("transcript_path")
    entries = _load_transcript(transcript_path)

    if not entries:
        print(json.dumps({"continue": True}))
        return

    fmt = _detect_format(entries)
    if fmt == "unknown":
        print(json.dumps({"continue": True}))
        return

    loaded = _extract_loaded_skills(entries, fmt)
    if not loaded:
        print(json.dumps({"continue": True}))
        return

    referenced = _extract_assistant_skill_refs(entries, loaded, fmt)
    already_reported = _check_manual_reports(entries, fmt)
    evals = _extract_skill_evaluations(entries, fmt)

    # Report skills that were referenced but not manually reported
    to_report = referenced - already_reported
    reported_count = 0
    for skill in sorted(to_report):
        score, reason = evals.get(skill, ("", ""))
        if score == "F":
            ok = _report_skill_failed(skill, note=reason)
        elif score in ("B", "C"):
            ok = _report_skill(skill, note=reason)
        else:
            # Score A or no evaluation — success, no note
            ok = _report_skill(skill)
        if ok:
            reported_count += 1

    # Also report loaded-but-not-referenced skills as "not applied"
    not_applied = loaded - referenced - already_reported
    for skill in sorted(not_applied):
        cmd = shutil.which("openspace-report")
        if cmd:
            try:
                subprocess.run(
                    [cmd, skill, "--not-applied",
                     "--note", "loaded but not referenced by assistant"],
                    capture_output=True, text=True, timeout=10,
                )
            except (subprocess.TimeoutExpired, OSError):
                pass

    msg = f"OpenSpace: reported {reported_count} skill(s)"
    if not_applied:
        msg += f", {len(not_applied)} not-applied"
    print(json.dumps({"continue": True, "systemMessage": msg}))


if __name__ == "__main__":
    main()
