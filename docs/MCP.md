# MCP (Model Context Protocol) in this repository

This document explains how **MCP tools** are wired up for the **Moboclaw** service and how to use them from Cursor.

## What is configured in-repo

Cursor reads **project-level** MCP settings from:

**`.cursor/mcp.json`**

That file registers one server:

| Key | Value |
|-----|--------|
| Server name | `moboclaw` |
| Transport | Streamable HTTP (`streamableHttp`) |
| URL | `http://127.0.0.1:8080/mcp/` |

The trailing slash on `/mcp/` matters: the app mounts the MCP HTTP app at `/mcp/`, and also redirects `/mcp` → `/mcp/` for clients that omit the slash.

**Important:** The port in `url` must match wherever you run the API. If you start Uvicorn on a different port (for example `8080` as in [moboclaw/README.md](../moboclaw/README.md)), either change the port in `.cursor/mcp.json` or run the server on `8098` so the URL stays valid.

## What must be running

MCP is served by the same FastAPI application as the REST API (`moboclaw/app/main.py` uses FastMCP and mounts the MCP app at `/mcp/`).

1. Start the Moboclaw app from the `moboclaw/` directory (see [moboclaw/README.md](../moboclaw/README.md) — local Uvicorn or Docker).
2. Ensure the process listens on the host and port expected by `.cursor/mcp.json` (currently `127.0.0.1:8080`).

Example (local venv, matching this repo’s MCP URL):

```bash
cd moboclaw
source .venv/bin/activate   # if you use a venv
uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
```

If the server is down or the URL/port is wrong, Cursor will not connect and **Moboclaw MCP tools will not appear** for the agent.

## How tools show up in Cursor

1. Open this workspace in Cursor.
2. Confirm **MCP** is enabled and the `moboclaw` server is listed and connected (Cursor **Settings → MCP**; exact UI labels may vary by version).
3. After a successful connection, agents can invoke the tools exposed by the Moboclaw MCP server (emulators, sessions, missions, health, etc.), subject to Cursor’s own MCP permissions.

No API keys are required for the local `moboclaw` server in `.cursor/mcp.json`.

## Other MCP servers (not in this file)

You may have **additional** MCP servers enabled in your **user** Cursor settings (for example GitHub, Slack, Atlassian). Those are not defined in this repo’s `.cursor/mcp.json`; they are separate from the Moboclaw entry above.

## Tool schemas (optional reference)

When Cursor connects to an MCP server, it can cache tool metadata under the editor’s project data. If you need to inspect parameter names and types for troubleshooting, look for descriptor JSON files under your Cursor project’s MCP cache for the `moboclaw` server (folder naming may include `user-moboclaw` / `moboclaw`). The authoritative behavior remains the **running** Moboclaw app and its FastMCP/FastAPI definitions in `moboclaw/app/`.
