<div align="center">

<picture>
    <img src="assets/logo.png" width="320px" style="border: none; box-shadow: none;" alt="OpenSpace Logo">
</picture>

## OpenSpace: Self-Evolving Skills for AI Agents

[![Agents](https://img.shields.io/badge/Agents-Claude_Code%20%7C%20Codex%20%7C%20Kiro-99C9BF.svg)](https://modelcontextprotocol.io/)
[![Python](https://img.shields.io/badge/Python-3.12+-FCE7D6.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-C1E5F5.svg)](https://opensource.org/licenses/MIT/)

Skills that learn, improve, and share themselves across your AI tools.

</div>

---

## What is OpenSpace?

OpenSpace is an MCP server that gives your AI agents (Claude Code, Codex, Kiro) self-evolving skills. It plugs into any agent that supports the Model Context Protocol.

**What it does:**
- Skills automatically improve after each use (FIX / DERIVED / CAPTURED)
- Evolved skills push to your team's Git repo via skillpull
- Team members pull improvements automatically
- All agents share the same skill library

**What you get:**
- Reuse proven patterns instead of reasoning from scratch
- Failed approaches get fixed, not repeated
- One agent learns, all agents benefit

---

## Quick Start

```bash
git clone https://github.com/tianhaocui/OpenSpace.git && cd OpenSpace
pip install -e .
openspace-setup
```

`openspace-setup` will:
1. Ask you to choose an LLM provider (Anthropic, OpenAI, DeepSeek, or custom)
2. Auto-detect your API key from the environment
3. Register OpenSpace as an MCP server for Claude Code, Codex, Kiro
4. Configure Stop hooks for auto skill evolution (Codex + Claude Code)
5. Copy host skills to `~/.agents/skills/`

Done. Your agents now have self-evolving skills.

> **Need Python 3.12+.** If your system Python is older, use `python3.13 -m venv .venv && source .venv/bin/activate` first.

---

## MCP Tools

Once registered, your agent has 5 tools:

| Tool | What It Does |
|---|---|
| `execute_task` | Delegate a task — auto-selects skills, executes, records workflow |
| `search_skills` | Search local skill registry |
| `report_skill_usage` | Report external skill usage for quality tracking and auto-evolution |
| `fix_skill` | Evolve a skill — provide direction, OpenSpace rewrites it |
| `sync_skills_git` | Pull/push skills from/to Git repos via skillpull |

Your agent decides when to use these. You don't need to trigger them manually.

---

## Skill Evolution

Three ways skills evolve:

**1. Through execute_task** — After task execution, OpenSpace analyzes the result and evolves skills automatically.

**2. Through Stop hooks (Codex + Claude Code)** — A Stop hook runs at session end, parses the transcript, extracts skill evaluations (`[A/B/C/F]` scores), and reports usage via `openspace-report`. No agent cooperation needed — fully deterministic.

```
Session ends → Stop hook parses transcript → extracts [A/B/C/F] evaluations
  → Score B/C: openspace-report --note "specific issue"
  → Score F:   openspace-report --failed --note "reason"
  → Score A:   openspace-report (count only)
```

`openspace-setup` auto-configures hooks for both Codex (`~/.codex/hooks.json`) and Claude Code (`~/.claude/settings.json`).

**3. Through skill-evolution skill** — Your AI tool evaluates each skill after use, reports usage via `report_skill_usage`, and calls `fix_skill` when improvements are needed. Works across Claude Code, Codex, and Kiro. You'll see a rating:
```
[A] skillpull — accurate and complete, no changes needed
[B] git-commit — missing amend example → evolving
```

**4. Through report_skill_usage** — Track skill quality from any tool. Accumulates metrics and triggers auto-evolution:

- **3 consecutive failures** → immediate evolution (bypasses the 5-use threshold)
- **3 consecutive noted reports** (Score B/C) → immediate evolution
- **5+ uses** → metric-based evolution check (fallback rate, completion rate, effectiveness)

```bash
# MCP tool (Claude Code, Kiro)
report_skill_usage(skill_name="git-commit", task_completed=true, skill_applied=true)

# CLI (Codex, or any shell)
openspace-report git-commit
openspace-report git-commit --failed --note "pre-commit hook rejected"
```

**5. Manual** — Tell your agent: "evolve the skillpull skill, add X"

Evolved skills auto-push to your team's Git repo. Teammates get improvements on `skillpull update`.

### Webhook Notifications

Get notified when skills evolve. Set `OPENSPACE_NOTIFY_WEBHOOK` in your `.mcp.json` env:

| Platform | Webhook URL |
|---|---|
| Feishu | `https://open.feishu.cn/open-apis/bot/v2/hook/<token>` |
| WeCom | `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=<key>` |
| DingTalk | `https://oapi.dingtalk.com/robot/send?access_token=<token>` |

---

## Skill Sync via Git

Share skills with your team:

```bash
pip install skillpull
skillpull registry git@github.com:your-org/agent-skills.git
skillpull --all -f              # pull all skills
skillpull push                  # push evolved skills
```

### Project-Specific Skills

Skills can be scoped to projects. Repo structure:

```
agent-skills/
├── skills/              # shared across all projects
├── client-portal/       # only pulled when --project client-portal
├── linker-pom/          # only pulled when --project linker-pom
└── livechat/            # only pulled when --project livechat
```

In each project directory, create `.skillpullrc`:
```json
{"registry":"","project":"client-portal"}
```

Then `skillpull --all -f` pulls shared + project-specific skills.

---

## Configuration

### .mcp.json

```json
{
  "mcpServers": {
    "openspace": {
      "command": "openspace-mcp",
      "env": {
        "ANTHROPIC_API_KEY": "your-key",
        "OPENSPACE_MODEL": "anthropic/claude-opus-4-6-20250610",
        "OPENSPACE_CLOUD_ENABLED": "false",
        "MCP_USE_ANONYMIZED_TELEMETRY": "false"
      }
    }
  }
}
```

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` or `DEEPSEEK_API_KEY` | Yes (one) | LLM API key |
| `OPENSPACE_MODEL` | No | Auto-detected from API key |
| `OPENSPACE_LLM_API_BASE` | No | Custom LLM proxy URL |
| `EMBEDDING_BASE_URL` + `EMBEDDING_API_KEY` | No | Remote embedding (default: local model) |
| `OPENSPACE_NOTIFY_WEBHOOK` | No | Evolution notification webhook |
| `OPENSPACE_CLOUD_ENABLED` | No | Default `false` |
| `MCP_USE_ANONYMIZED_TELEMETRY` | No | Default `false` |

---

## Dashboard

Browse skills, track evolution lineage, view execution history:

```bash
openspace-dashboard --port 7788
cd frontend && npm install && npm run dev    # Node.js >= 20
```

---

<details>
<summary><b>Code Structure</b></summary>

```
openspace/
├── mcp_server.py              # MCP Server (5 tools) + openspace-report CLI
├── tool_layer.py              # Orchestration engine
├── setup.py                   # openspace-setup CLI (MCP + hooks auto-config)
├── dashboard_server.py        # Dashboard API
├── codex_hooks/               # Stop hook for Codex + Claude Code auto-evolution
├── agents/                    # Agent framework + GroundingAgent
├── grounding/
│   ├── core/                  # Tool search, quality tracking, security
│   └── backends/
│       ├── shell/             # Shell command execution
│       └── mcp/               # MCP server connections
├── skill_engine/              # Registry, analyzer, evolver, store
├── host_detection/            # LLM credential resolution (nanobot/openclaw/hermes)
├── host_skills/               # Built-in skills (delegate-task, skill-discovery, skill-evolution)
├── llm/                       # LiteLLM wrapper
├── cloud/cli/                 # skillpull Git sync
└── config/                    # Configuration system
```

Entry points:
- `openspace-mcp` — MCP Server
- `openspace-setup` — Interactive setup
- `openspace-dashboard` — Dashboard UI
- `openspace-skillpull` — Git skill sync CLI
- `openspace-report` — Report skill usage from CLI (for Codex and other non-MCP tools)

</details>

---

## License

MIT

---

<div align="center">

Built on [OpenSpace](https://github.com/HKUDS/OpenSpace) by HKUDS.

</div>
