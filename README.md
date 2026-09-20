# typesafe-tpm-mcp

An MCP server that reviews a work ticket with a TypeSafe System One model
before an agent executes it, and returns a binding routing verdict plus
section-level fixes.

Tickets follow the project's existing template (Goal / Description /
Acceptance Criteria / Not In Scope / Files to Create / Do Not Touch /
Context & References). Nothing about how tickets are written needs to
change — this just adds a check between drafting and execution.

## Quickstart

### 1. Get a TypeSafe API key

Create one at **https://console.typesafe.ai**. The SDK reads it from
`TYPESAFE_API_KEY`.

```bash
cp .env.example .env
# then put the key in .env
```

For local development you can also just export it:

```bash
export TYPESAFE_API_KEY="your-key-here"
```

The server does **not** read `.env` automatically — MCP clients launch it
as a subprocess, so the key goes in the client's config `env` block (step
3) or your shell profile. Keep the key out of version control either way.

### 2. Install

```bash
uv sync
```

or, without uv:

```bash
pip install -e .
```

Verify it starts (it will wait on stdio — Ctrl-C to exit):

```bash
uv run typesafe-tpm-mcp
```

### 3. Register the server with your MCP client

**Claude Code** — from the project root:

```bash
claude mcp add ticket-quality \
  --env TYPESAFE_API_KEY=your-key-here \
  -- uv --directory /absolute/path/to/typesafe-tpm-mcp run typesafe-tpm-mcp
```

**Any client using a JSON config** (`claude_desktop_config.json`,
`.mcp.json`, etc.):

```json
{
  "mcpServers": {
    "ticket-quality": {
      "command": "uv",
      "args": [
        "--directory", "/absolute/path/to/typesafe-tpm-mcp",
        "run", "typesafe-tpm-mcp"
      ],
      "env": { "TYPESAFE_API_KEY": "your-key-here" }
    }
  }
}
```

Use an absolute path for `--directory`. Restart the client after editing
JSON config.

### 4. Install the skill

The server exposes the tools; the skill tells agents when to call them and
how to act on the result. Copy it where your agents look for skills:

```bash
cp -r skills/ticket-quality ~/.claude/skills/
# or, to scope it to one project:
cp -r skills/ticket-quality .claude/skills/
```

### 5. Confirm it's working

Ask an agent with the skill loaded to draft a deliberately thin ticket
("add some tests to the comp finder"). You should see it call
`review_ticket_quality` and come back with `needs_revision` plus specific
fixes, rather than starting to write code.

## Tools

| Tool | What it does |
|---|---|
| `get_ticket_template` | Blank template with per-section guidance. Call before drafting. |
| `review_ticket_quality` | The gate. Returns `route`, `fixes`, `signals`, `gated`. |
| `explain_primitives` | Lists every question the gate asks. Useful for debugging a verdict. |

## Tuning

Routing thresholds live in `DEFAULT_THRESHOLDS` in
`src/typesafe_tpm_mcp/schema.py` and can be overridden per-key with
`TQ_`-prefixed environment variables — no code change needed:

```bash
TQ_ROUTE_READY_FOR_EXECUTION=0.85   # stricter about letting tickets through
TQ_READINESS_CONFIDENCE_FLOOR=0.65  # escalate more uncertain classifications
```

The defaults are a starting point. `route_ready_for_execution` carries the
highest bar because it's the only route where being wrong costs a real
agent run; `needs_revision` and `needs_human_scoping` sit low because
over-routing to them costs one extra editing pass.

Tune from observed behavior: if tickets you'd have approved keep getting
held, lower `route_ready_for_execution`. If bad tickets are getting
through, raise it before touching anything else.

## Design notes

- **One batched call.** All eleven questions go in a single
  `client.system_one(...)` request. TypeSafe evaluates them in parallel,
  so asking a question that turns out not to matter is nearly free —
  cheaper and faster than separate calls.
- **Routing lives in code, not in a prompt.** The model answers narrow
  questions; `route_ticket_review()` decides. Changing priorities means
  changing a threshold constant, not rewriting instructions.
- **Hard gates ignore confidence.** A self-contradicting ticket, or a
  wide-blast-radius ticket with nothing in Do Not Touch, is held no matter
  how confident the classifier is that it's ready.
- **Dependencies get verified, not classified.** The model can only tell
  you a dependency was *claimed*. `blocked_on_dependency` hands back a
  `verify` instruction rather than pretending to know whether the
  referenced ticket is closed.
- **Fails closed.** If the TypeSafe call errors, the tool returns
  `needs_human_scoping`, not a pass.

## Layout

```
src/typesafe_tpm_mcp/
  schema.py    TicketDraft, the jev primitives, thresholds, router, feedback builder
  server.py    FastMCP server exposing the three tools
skills/
  ticket-quality/SKILL.md
```
