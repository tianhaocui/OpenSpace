"""Shared utility functions for the skill engine.

Provides:
  - YAML frontmatter parsing/manipulation (unified across registry, evolver, etc.)
  - LLM output cleaning (markdown fence stripping, change summary extraction)
  - Skill content safety checking (regex-based moderation)
  - Skill directory validation
  - Text truncation
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from openspace.utils.logging import Logger

logger = Logger.get_logger(__name__)

SKILL_FILENAME = "SKILL.md"

_SAFETY_RULES = [
    ("blocked.malware",         re.compile(r"(ClawdAuthenticatorTool)", re.IGNORECASE)),
    ("blocked.pipe_to_shell",   re.compile(r"(curl|wget)[^\n]+\|\s*(sh|bash)", re.IGNORECASE)),
    ("blocked.reverse_shell",   re.compile(r"bash\s+-i\s+>&\s*/dev/tcp/", re.IGNORECASE)),
    ("blocked.exfiltration",    re.compile(r"curl\s+.*-X\s+POST\s+.*-d\s+\$\(", re.IGNORECASE)),
    ("suspicious.prompt_injection", re.compile(r"(ignore previous instructions|disregard all above instructions)", re.IGNORECASE)),
    ("suspicious.keyword",      re.compile(r"(malware|stealer|phish|phishing|keylogger)", re.IGNORECASE)),
    ("suspicious.secrets",      re.compile(r"(api[-_ ]?key|token|password|private key|secret)", re.IGNORECASE)),
    ("suspicious.crypto",       re.compile(r"(wallet|seed phrase|mnemonic|crypto)", re.IGNORECASE)),
    ("suspicious.webhook",      re.compile(r"(discord\.gg|webhook|hooks\.slack)", re.IGNORECASE)),
    ("suspicious.script",       re.compile(r"(curl[^\n]+\|\s*(sh|bash))", re.IGNORECASE)),
    ("suspicious.url_shortener", re.compile(r"(bit\.ly|tinyurl\.com|t\.co|goo\.gl|is\.gd)", re.IGNORECASE)),
]

_BLOCKING_FLAGS = frozenset(f for f, _ in _SAFETY_RULES if f.startswith("blocked."))


def check_skill_safety(text: str) -> List[str]:
    """Check *text* against safety rules, return list of triggered flag names.

    Returns an empty list if no rules match (= safe).
    """
    return [flag for flag, pat in _SAFETY_RULES if pat.search(text)]


def is_skill_safe(flags: List[str]) -> bool:
    """Return True if *flags* contain no blocking flag.

    ``suspicious.*`` flags are informational (logged / attached to search
    results) but do NOT block in standard mode.  Only ``blocked.*`` flags
    cause rejection.

    When ``OPENSPACE_SAFETY_LEVEL=strict``, any ``suspicious.*`` flag also
    causes rejection.
    """
    if any(f in _BLOCKING_FLAGS for f in flags):
        return False
    strict = os.environ.get("OPENSPACE_SAFETY_LEVEL", "").strip().lower() == "strict"
    if strict and any(f.startswith("suspicious.") for f in flags):
        return False
    return True

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)

# Characters that require YAML value quoting (colon-space, hash-space,
# or values starting with special YAML indicators).
_YAML_NEEDS_QUOTE_RE = re.compile(r"[:\#\[\]{}&*!|>'\"%@`]")


def _yaml_quote(value: str) -> str:
    """Quote a YAML scalar value if it contains special characters."""
    if not value or not _YAML_NEEDS_QUOTE_RE.search(value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _yaml_unquote(value: str) -> str:
    """Strip surrounding quotes and unescape a YAML scalar value."""
    if len(value) >= 2:
        if (value[0] == '"' and value[-1] == '"') or \
           (value[0] == "'" and value[-1] == "'"):
            inner = value[1:-1]
            if value[0] == '"':
                inner = inner.replace('\\"', '"').replace("\\\\", "\\")
            return inner
    return value


def _parse_yaml_value(value: str) -> Any:
    """Parse a YAML scalar or inline list value."""
    value = value.strip()
    if not value:
        return ""
    # Inline list: [a, b, c]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1]
        return [_yaml_unquote(item.strip()) for item in inner.split(",") if item.strip()]
    return _yaml_unquote(value)


def parse_frontmatter(content: str) -> Dict[str, Any]:
    """Parse YAML frontmatter into a dict.

    Simple line-by-line parser (no PyYAML dependency).
    Handles quoted/unquoted values, inline lists, and nested dicts.
    Returns ``{}`` if no valid frontmatter is found.
    """
    if not content.startswith("---"):
        return {}
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}
    fm: Dict[str, Any] = {}
    lines = match.group(1).split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if ":" not in line:
            i += 1
            continue
        # Determine indentation level
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if indent > 0:
            i += 1
            continue  # skip nested lines in top-level pass
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            i += 1
            continue
        if value:
            fm[key] = _parse_yaml_value(value)
        else:
            # Possibly a nested dict — collect indented lines
            nested: Dict[str, Any] = {}
            j = i + 1
            while j < len(lines):
                nline = lines[j]
                nstripped = nline.lstrip()
                nindent = len(nline) - len(nstripped)
                if nindent <= indent or not nstripped:
                    if not nstripped:
                        j += 1
                        continue
                    break
                if ":" in nstripped:
                    nkey, nval = nstripped.split(":", 1)
                    nkey = nkey.strip()
                    nval = nval.strip()
                    if nkey and nval:
                        nested[nkey] = _parse_yaml_value(nval)
                    elif nkey and not nval:
                        # Second level nesting
                        inner: Dict[str, Any] = {}
                        k = j + 1
                        while k < len(lines):
                            iline = lines[k]
                            istripped = iline.lstrip()
                            iindent = len(iline) - len(istripped)
                            if iindent <= nindent or not istripped:
                                if not istripped:
                                    k += 1
                                    continue
                                break
                            if ":" in istripped:
                                ik, iv = istripped.split(":", 1)
                                ik = ik.strip()
                                iv = iv.strip()
                                if ik:
                                    inner[ik] = _parse_yaml_value(iv)
                            k += 1
                        nested[nkey] = inner
                        j = k
                        continue
                j += 1
            fm[key] = nested
            i = j
            continue
        i += 1
    return fm


def get_frontmatter_field(content: str, field_name: str) -> Optional[str]:
    """Extract a single field value from YAML frontmatter.

    Returns ``None`` if the field is absent or content has no frontmatter.
    """
    if not content.startswith("---"):
        return None
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return None
    for line in match.group(1).split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            if key.strip() == field_name:
                return _yaml_unquote(value.strip())
    return None


def set_frontmatter_field(content: str, field_name: str, value: str) -> str:
    """Set (or insert) a field in YAML frontmatter.

    Values containing YAML special characters (``:``, ``#``, etc.) are
    automatically double-quoted to produce valid YAML.

    If *content* has no frontmatter, a new one is prepended.
    """
    quoted = _yaml_quote(value)
    if not content.startswith("---"):
        return f"---\n{field_name}: {quoted}\n---\n{content}"

    match = _FRONTMATTER_RE.match(content)
    if not match:
        return content

    fm_text = match.group(1)
    new_line = f"{field_name}: {quoted}"
    found = False
    new_lines = []
    for line in fm_text.split("\n"):
        if ":" in line and line.split(":", 1)[0].strip() == field_name:
            new_lines.append(new_line)
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(new_line)

    new_fm = "\n".join(new_lines)
    return f"---\n{new_fm}\n---{content[match.end():]}"


def normalize_frontmatter(content: str) -> str:
    """Re-serialize frontmatter with proper YAML quoting.

    Parses the existing frontmatter, then re-writes each value through
    :func:`_yaml_quote` so that colons, hashes, and other special
    characters are safely double-quoted.  The body after ``---`` is
    preserved verbatim.

    Returns *content* unchanged if no frontmatter is found.
    """
    if not content.startswith("---"):
        return content
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return content

    fm = parse_frontmatter(content)
    if not fm:
        return content

    safe_lines = [f"{k}: {_yaml_quote(v)}" for k, v in fm.items()]
    new_fm = "\n".join(safe_lines)
    return f"---\n{new_fm}\n---{content[match.end():]}"


def strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter from markdown content."""
    if content.startswith("---"):
        match = re.match(r"^---\n.*?\n---\n?", content, re.DOTALL)
        if match:
            return content[match.end():].strip()
    return content

def strip_markdown_fences(text: str) -> str:
    """Remove surrounding markdown code fences if present.

    Handles common LLM wrapping patterns:
      - ````` ```markdown ```, ````` ```md ```, ````` ``` ```, ````` ```text `````
      - Nested triple-backtick pairs (outermost only)
      - Leading/trailing whitespace around fences
    """
    text = text.strip()

    # Pattern: opening ``` with optional language tag, content, closing ```
    m = re.match(
        r"^```(?:markdown|md|text|yaml|diff|patch)?\s*\n(.*?)\n```\s*$",
        text,
        re.DOTALL,
    )
    if m:
        return m.group(1).strip()

    # Some LLMs emit ``````` (4+ backticks) as outer fence
    m = re.match(
        r"^`{3,}(?:\w+)?\s*\n(.*?)\n`{3,}\s*$",
        text,
        re.DOTALL,
    )
    if m:
        return m.group(1).strip()

    return text


_CHANGE_SUMMARY_RE = re.compile(
    r"^[\s*_]*(?:CHANGE[\s_-]?SUMMARY)\s*[:：]\s*(.+)",
    re.IGNORECASE,
)


def extract_change_summary(content: str) -> tuple[str, str]:
    """Extract ``CHANGE_SUMMARY`` from LLM output.

    Returns ``(clean_content, change_summary)``.
    """
    lines = content.split("\n")

    # Find the first non-blank line
    first_nonblank = -1
    for i, line in enumerate(lines):
        if line.strip():
            first_nonblank = i
            break

    if first_nonblank == -1:
        return content, ""

    m = _CHANGE_SUMMARY_RE.match(lines[first_nonblank])
    if not m:
        return content, ""

    # Strip markdown bold/italic markers (** or __) from both ends
    summary = m.group(1).strip().strip("*_").strip()

    # Skip blank lines after the summary line to find content start
    content_start = first_nonblank + 1
    while content_start < len(lines) and not lines[content_start].strip():
        content_start += 1

    rest = "\n".join(lines[content_start:])
    return rest.strip(), summary

def validate_skill_dir(skill_dir: Path) -> Optional[str]:
    """Validate a skill directory after edit application.

    Returns None if valid, or an error message string.
    Checks:
      1. Directory exists
      2. SKILL.md exists and is non-empty
      3. SKILL.md has valid YAML frontmatter with ``name`` field
      4. No empty files (warning-level, not blocking)
    """
    if not skill_dir.exists():
        return f"Skill directory does not exist: {skill_dir}"

    skill_file = skill_dir / SKILL_FILENAME
    if not skill_file.exists():
        return f"SKILL.md not found in {skill_dir}"

    try:
        content = skill_file.read_text(encoding="utf-8")
    except Exception as e:
        return f"Cannot read SKILL.md: {e}"

    if not content.strip():
        return "SKILL.md is empty"

    # Check frontmatter
    if not content.startswith("---"):
        return "SKILL.md missing YAML frontmatter (should start with '---')"

    m = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not m:
        return "SKILL.md has malformed YAML frontmatter (missing closing '---')"

    # Check for required 'name' field in frontmatter
    name = get_frontmatter_field(content, "name")
    if not name:
        return "SKILL.md frontmatter missing 'name' field"

    # Non-blocking checks: log warnings for empty auxiliary files
    for p in skill_dir.rglob("*"):
        if p.is_file() and p != skill_file:
            try:
                if p.stat().st_size == 0:
                    logger.warning(f"Validation: empty auxiliary file: {p.relative_to(skill_dir)}")
            except OSError:
                pass

    return None


def truncate(text: str, max_chars: int) -> str:
    """Truncate *text* to *max_chars* with an ellipsis marker."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n... [truncated at {max_chars} chars]"

