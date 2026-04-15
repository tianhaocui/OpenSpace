---
name: skill-evolution
description: "Auto-evolve skills after use. When a task completes and a skill was involved, evaluate the skill's effectiveness and call fix_skill to improve it if needed. Triggers after any task where a skill was loaded. Works across Claude Code, Codex, and Kiro."
license: MIT
---

# Skill Evolution — Post-Use Reflection & Auto-Improvement

## When This Activates

After you complete a task where **any skill was loaded and followed**, pause and run the evaluation below. This applies whether the task succeeded or failed.

**Skip evaluation when:**
- No skill was used in this task
- The task was purely conversational (no code/tool actions taken)
- You are a subagent dispatched for a narrow subtask

## Evaluation Process

After the task is done, reflect on each skill you used:

### 1. Was the skill helpful?

- Did it guide you to the right approach?
- Did you follow it, or did you deviate? Why?
- Was any instruction outdated, wrong, or missing?

### 2. Score the skill (internal, don't output this)

| Score | Meaning |
|-------|---------|
| A | Skill was accurate and complete, no changes needed |
| B | Skill was mostly right but has minor gaps or outdated details |
| C | Skill was partially wrong or missing critical steps |
| F | Skill was actively harmful or completely outdated |

### 3. Report usage to OpenSpace (ALWAYS, for every skill)

Regardless of score, report each skill's usage so OpenSpace can track quality metrics and trigger auto-evolution. Use whichever method is available in your environment:

**Option 1 — MCP tool** (Claude Code, Kiro, or any MCP-capable client):
```
report_skill_usage(
  skill_name="<skill-name>",
  task_completed=true/false,
  skill_applied=true/false,
  note="<optional: brief note on what happened>"
)
```

**Option 2 — CLI** (Codex, or any environment with shell access):
```bash
openspace-report <skill-name>                    # success
openspace-report <skill-name> --failed           # task failed
openspace-report <skill-name> --not-applied      # skill was loaded but not followed
openspace-report <skill-name> --note "details"   # with note
```

Map scores to parameters:
- **Score A**: `task_completed=true, skill_applied=true`
- **Score B**: `task_completed=true, skill_applied=true, note="<what was suboptimal>"`
- **Score C**: `task_completed=true/false, skill_applied=true, note="<what was wrong>"`
- **Score F**: `task_completed=false, skill_applied=false, note="<why it failed>"`

### 4. Act on the score

**Score A** — Do nothing. The skill is fine.

**Score B or C** — Call `fix_skill` to improve it:

```
fix_skill(
  skill_dir="/path/to/the/skill/directory",
  direction="<specific description of what to fix and why>"
)
```

The `direction` must be specific and actionable. Examples:
- "The API endpoint changed from /v1/users to /v2/users, update the curl examples"
- "Add error handling guidance for 429 rate limit responses, which we hit during execution"
- "The Docker compose command should use 'docker compose' not 'docker-compose' (V2 syntax)"
- "Missing step: need to run 'npm install' before 'npm run build' in the setup section"

**Score F** — Call `fix_skill` with a comprehensive rewrite direction, or flag to the user that the skill needs manual review.

## Rules

1. **Be specific in `direction`** — "improve the skill" is useless. Say exactly what's wrong and how to fix it.
2. **One fix_skill call per skill** — Don't call it multiple times for the same skill in one session.
3. **Don't fix what isn't broken** — Score A skills get no fix_skill call. Don't "improve" working skills.
4. **Fix based on evidence** — Only suggest fixes for issues you actually encountered during the task, not hypothetical problems.
5. **Always show the evaluation** — After evaluating, output a one-line summary for each skill used:
   - `[A] skillpull — accurate and complete, no changes needed`
   - `[B] git-commit — missing amend example → evolving`
   - `[C] lark-docs — wrong API endpoint → evolving`
   - `[F] old-workflow — completely outdated → flagged for review`

## Finding the Skill Directory

The skill directory is where the SKILL.md file lives. Common locations:
- `~/.claude/skills/<skill-name>/`
- `~/.codex/skills/<skill-name>/`
- `~/.kiro/skills/<skill-name>/`
- `~/.agents/skills/<skill-name>/`
- `.claude/skills/<skill-name>/` (project-level)

Use the path from where the skill was loaded. If unsure, check `~/.claude/skills/` first.

## What Happens After fix_skill

OpenSpace's evolution engine will:
1. Use LLM to rewrite the skill based on your direction
2. Run safety checks on the new content
3. Save the evolved version locally
4. **Auto-push to the team's Git repo** (via skillpull)

Your teammates will get the improved skill on their next `skillpull update`.
