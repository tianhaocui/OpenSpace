---
name: delegate-task
description: Delegate tasks to OpenSpace — a self-evolving MCP server for task execution, skill search, skill evolution, and Git-based skill sync. Use when the task needs tools beyond your capabilities, you tried and failed, or the user explicitly asks.
---

# Delegate Tasks to OpenSpace

OpenSpace is connected as an MCP server. You have 4 tools: `execute_task`, `search_skills`, `fix_skill`, `sync_skills_git`.

## When to use

- **You lack the capability** — the task requires tools beyond what you can access
- **You tried and failed** — OpenSpace may have a tested skill for it
- **Complex multi-step task** — benefits from OpenSpace's skill library and orchestration
- **User explicitly asks** — user requests delegation to OpenSpace

## Tools

### execute_task

Delegate a task to OpenSpace. It searches for relevant skills, executes, and auto-evolves skills.

```
execute_task(task="Monitor Docker containers, find the highest memory one, restart it gracefully")
```

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `task` | yes | — | Task instruction in natural language |
| `max_iterations` | no | `20` | Max agent iterations |
| `skill_dirs` | no | — | Extra skill directories to register |

### search_skills

Search for available skills before deciding whether to handle a task yourself or delegate.

```
search_skills(query="docker container monitoring")
```

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `query` | yes | — | Search query (natural language or keywords) |
| `limit` | no | `20` | Max results |

### fix_skill

Evolve a skill — provide what's wrong and how to fix it. Evolved skills auto-push to the team's Git repo.

```
fix_skill(
  skill_dir="/path/to/skills/weather-api",
  direction="The API endpoint changed from v1 to v2, update all URLs"
)
```

| Parameter | Required | Description |
|-----------|----------|-------------|
| `skill_dir` | yes | Path to skill directory (must contain SKILL.md) |
| `direction` | yes | What's broken and how to fix — be specific |

### sync_skills_git

Pull/push skills from/to Git repos via skillpull.

```
sync_skills_git(action="pull", repo="@team")
sync_skills_git(action="push")
```

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `action` | yes | — | `"pull"` or `"push"` |
| `repo` | no | registry default | Git repo URL, user/repo, or @alias |
| `skill_name` | no | — | Pull only this skill (pull only) |
| `force` | no | `false` | Overwrite existing skills on pull |

## Notes

- `execute_task` may take minutes — this is expected for multi-step tasks.
- Evolved skills auto-push to the team Git repo and send webhook notifications (if configured).
- After every OpenSpace call, **tell the user** what happened.
