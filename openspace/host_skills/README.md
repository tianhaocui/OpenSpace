# Host Skills Integration Guide

This guide covers **agent-specific setup** for integrating OpenSpace. For installation and general concepts, see the [main README](../../README.md#-quick-start).

**Quick recommendation:**
- Use **stdio** if you want the simplest setup.
- For **nanobot**, prefer **SSE** if you want OpenSpace to run as a standalone server.
- For **openclaw**, prefer **streamable-http** for remote HTTP transport.

**Common remote endpoints:**
- Start `openspace-mcp --transport sse --host 127.0.0.1 --port 8080` and use `http://127.0.0.1:8080/sse`
- Start `openspace-mcp --transport streamable-http --host 127.0.0.1 --port 8081` and use `http://127.0.0.1:8081/mcp`

The endpoint is common; the **host config syntax is not**. nanobot uses `tools.mcpServers`, while openclaw uses `openclaw mcp set`.

**Pick your agent:**

| Agent | Setup Guide |
|------------|-------------|
| **[nanobot](https://github.com/HKUDS/nanobot)** | [Setup for nanobot](#setup-for-nanobot) |
| **[openclaw](https://github.com/openclaw/openclaw)** | [Setup for openclaw](#setup-for-openclaw) |
| **[Hermes Agent](https://github.com/NousResearch/hermes-agent)** | [Setup for Hermes Agent](#setup-for-hermes-agent) |
| **Other agents** | Follow the [generic setup](../../README.md#-path-a-empower-your-agent-with-openspace) in the main README |

---

## Setup for nanobot

### 1. Copy host skills

```bash
cp -r host_skills/skill-discovery/ /path/to/nanobot/nanobot/skills/
cp -r host_skills/delegate-task/ /path/to/nanobot/nanobot/skills/
```

### 2. Option A: stdio (simplest)

```json
{
  "tools": {
    "mcpServers": {
      "openspace": {
        "command": "openspace-mcp",
        "toolTimeout": 1200,
        "env": {
          "OPENSPACE_HOST_SKILL_DIRS": "/path/to/nanobot/nanobot/skills",
          "OPENSPACE_WORKSPACE": "/path/to/OpenSpace",
          "OPENSPACE_API_KEY": "sk-xxx"
        }
      }
    }
  }
}
```

> [!TIP]
> LLM credentials are auto-detected from nanobot's `providers.*` config — no need to set `OPENSPACE_LLM_API_KEY`.

### 3. Option B: remote HTTP transport

```json
{
  "tools": {
    "mcpServers": {
      "openspace": {
        "type": "sse",
        "url": "http://127.0.0.1:8080/sse",
        "toolTimeout": 1200
      }
    }
  }
}
```

Or:

```json
{
  "tools": {
    "mcpServers": {
      "openspace": {
        "type": "streamableHttp",
        "url": "http://127.0.0.1:8081/mcp",
        "toolTimeout": 1200
      }
    }
  }
}
```

`toolTimeout` still matters here. Changing transport to `sse` or `streamableHttp` does **not** remove nanobot's per-call timeout for slow MCP tools.

---

## Setup for openclaw

### 1. Copy host skills

```bash
cp -r host_skills/skill-discovery/ /path/to/openclaw/skills/
cp -r host_skills/delegate-task/ /path/to/openclaw/skills/
```

### 2. Option A: stdio via mcporter

openclaw uses [mcporter](https://github.com/steipete/mcporter) as its MCP runtime. Register the server and pass env vars in one command:

```bash
mcporter config add openspace --command "openspace-mcp" \
  --env OPENSPACE_HOST_SKILL_DIRS=/path/to/openclaw/skills \
  --env OPENSPACE_WORKSPACE=/path/to/OpenSpace \
  --env OPENSPACE_API_KEY=sk-xxx
```

### 3. Option B: remote HTTP transport

```bash
openclaw mcp set openspace '{"url":"http://127.0.0.1:8081/mcp","transport":"streamable-http","connectionTimeoutMs":10000}'
```

If you specifically want legacy SSE instead, OpenClaw also supports:

```bash
openclaw mcp set openspace '{"url":"http://127.0.0.1:8080","connectionTimeoutMs":10000}'
```

`connectionTimeoutMs` controls connection establishment for the remote server. It does **not** guarantee unlimited runtime for a long-running MCP tool call.

---

## Setup for Hermes Agent

Hermes Agent connects to OpenSpace via its built-in MCP client. OpenSpace auto-detects Hermes credentials from `~/.hermes/config.yaml`.

### 1. Install OpenSpace

```bash
pip install openspace
```

### 2. Option A: stdio (simplest)

Add to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  openspace:
    command: "openspace-mcp"
    env:
      OPENSPACE_API_KEY: "sk-xxx"  # optional, enables cloud skill search/upload
    timeout: 600  # important: execute_task can take minutes
```

> [!TIP]
> LLM credentials are auto-detected from Hermes's `model.*` config and provider env vars — no need to set `OPENSPACE_LLM_API_KEY`.

### 3. Option B: remote HTTP transport

Start OpenSpace as a standalone server:

```bash
openspace-mcp --transport sse --host 127.0.0.1 --port 8080
```

Then in `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  openspace:
    url: "http://127.0.0.1:8080/sse"
    timeout: 600
```

### 4. Verify

After configuring, Hermes will auto-discover 4 tools (prefixed as `mcp_openspace_*`):

```
hermes tools  # should show mcp_openspace_execute_task, etc.
```

### 5. Host skills (optional)

Copy the host skills to Hermes's skill directory for better delegation decisions:

```bash
cp -r host_skills/delegate-task/ ~/.hermes/skills/
cp -r host_skills/skill-discovery/ ~/.hermes/skills/
```

### Skill format compatibility

Hermes skills use the [agentskills.io](https://agentskills.io) standard with optional fields like `version`, `author`, `tags`, `platforms`, and `metadata`. OpenSpace now supports these fields — skills authored in Hermes work in OpenSpace and vice versa.

---

## Environment Variables (Agent-Specific)

The three env vars in each agent's setup above are the most important. For the **full env var list**, config files reference, and advanced settings, see the [Configuration Guide](../../README.md#configuration-guide) in the main README.

<details>
<summary>What needs <code>OPENSPACE_API_KEY</code>?</summary>

| Capability | Without API Key | With API Key |
|-----------|----------------|--------------|
| `execute_task` | ✅ works (local skills only) | ✅ + cloud skill search |
| `search_skills` | ✅ works (local results only) | ✅ + cloud results |
| `fix_skill` | ✅ works | ✅ works |
| `upload_skill` | ❌ fails | ✅ uploads to cloud |

All tools default to `"all"` (local + cloud) and **automatically fall back** to local-only if no API key is configured. No need to change tool parameters.

</details>

---

## How It Works

```
Your Agent (nanobot / openclaw / Hermes Agent / ...)
  │
  │  MCP protocol (stdio | HTTP/SSE | streamable-http)
  ▼
openspace-mcp              ← 4 tools exposed
  ├── execute_task           ← multi-step grounding agent loop
  ├── search_skills          ← local + cloud skill search
  ├── fix_skill              ← repair a broken SKILL.md
  └── upload_skill           ← push skill to cloud community
```

The two host skills teach the agent **when and how** to call these tools:

| Skill | MCP Tools | Purpose |
|-------|-----------|---------|
| **skill-discovery** | `search_skills` | Search local + cloud skills → decide: follow it yourself, delegate, or skip |
| **delegate-task** | `execute_task` `search_skills` `fix_skill` `upload_skill` | Delegate tasks, search skills, repair broken skills, upload evolved skills |

Skills auto-evolve inside `execute_task` (**FIX** / **DERIVED** / **CAPTURED**). After every call, your agent reports results to the user via its messaging tool.

> [!NOTE]
> For full parameter tables, examples, and decision trees, see each skill's SKILL.md directly.
