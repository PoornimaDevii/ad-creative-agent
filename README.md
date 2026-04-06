# Creatives Explorer Agent

## Workflow Structure

A user message flows through four layers before a response is rendered. The layers are as described below : 

**1. Streamlit UI — `app.py`**
The entry point. Validates the API key at startup, detects follow-up preview triggers ("show", "yes", "continue", "sure", etc.), and injects the last known `format_id` into the message for context. If the agent returns a hallucinated format_id, it's silently replaced with the last known good one from session state. Renders the chat, format cards, and previews.

**2. ReAct Agent — `llm/react_agent.py`**
Powered by Gemini 2.5 Flash Lite with configurations of temperature 0, thinking_budget 512 via LangGraph's prebuilt ReAct agent. Runs a Thought → Action → Observation loop with a 60s timeout. Keeps the last 2 conversation turns (4 messages) as context. Exposes two tools to the LLM:

- `list_creative_formats` — searches 48 Adzymic formats by name, type, dimensions, and asset requirements
- `preview_creative` — fetches a real Adzymic preview URL for a given format

**3. MCP Client — `mcp_client_module/mcp_client.py`**
Bridges the agent tools to the MCP server over Streamable HTTP aka SSE transport. Each call retries up to 3 times with async exponential backoff. Returns structured error dicts on failure rather than raising exceptions.

**4. MCP Server — `mcp_server.py`**
A FastMCP server running on `localhost:8000/sse` (port configurable via `PORT` env var, defaults to `8000`). The MCP client connects via `MCP_SERVER_URL` env var (defaults to `http://localhost:8000/sse`). Implements the full AdCP spec: fuzzy name search with suffix stemming, dimension filters, DCO filters, and preview generation in single / batch / variant modes. Reads format data from `registry/creative_formats.json`.

To know more about the setup of the MCP server and relevant tools, refer [MCP Readme](README_MCP.md).

MCP server interacts with a registry or storage where ground truth about the ads are stored, as described below : 

**Registry — `registry/`**
The source of ground truth for all format data. `creative_formats.json` holds the full AdCP v3 schema for all 48 formats, scraped from the [Adzymic format specifications](https://adzymic.freshdesk.com/support/solutions/articles/48000697384-ads-format-and-specifications-section) and parsed into structured JSON. `metadata.json` records the source URL, scrape/parse dates, schema version, and agent URL. `adzymic_raw.html` is the original scraped HTML kept for reference. To update the format catalog, re-run `parse_adzymic_to_json.py` against a fresh copy of the source HTML.

---

## Design Report

### Context Handling
The agent receives only the last 2 conversation turns (4 messages) to keep the prompt lean and avoid token bloat. However, pure text history loses tool result data (format_ids, specs) between turns. To solve this, `app.py` maintains `st.session_state["last_format_id"]` — whenever `list_creative_formats` returns results, the first format's ID is stored. On follow-up preview requests ("show me", "yes", "continue", "sure", etc.), the format_id is injected directly into the enriched user message sent to the agent, bypassing the need for the agent to re-fetch.

Additionally, if the agent hallucinates a format_id (wrong `agent_url` or ID not prefixed with `adzymic-`), `tool_handler` silently replaces it with the last known good one from session state. The stale format_id is cleared when the user asks about a completely new topic.

### Type Filter vs Name Search
The `type` field in the AdCP spec accepts only `audio`, `video`, `display` inputs. Brand and platform names like "facebook", "instagram", "youtube", "tiktok" are not types — they are format name keywords. The agent is instructed (via both the tool docstring and system prompt) to always route these through `name_search` and never infer a `type` from them. 

### ReAct over Simple Tool Calling
A standard tool-calling loop calls tools mechanically. The ReAct pattern (Reasoning + Acting) makes the LLM explicitly reason before each action — checking whether the format was already fetched, whether the request is a follow-up, and what single keyword to use for search. This reduces redundant tool calls and handles ambiguous inputs like "caurosel overlap show me" more gracefully.

### Fuzzy Name Search
Format names like "Feature Scrolled Ad" won't match a query like "feature scroller". The MCP server applies suffix stemming (strips `er`, `ed`, `ing`, `ler`, `led`, `s`) and multi-word matching (all words in the query must appear in the format name). This makes search resilient to typos and natural language variations without requiring a vector database.

### Error Recovery
- **MCP client**: 3 retries with async exponential backoff (`asyncio.sleep`) — non-blocking, won't freeze the event loop
- **Agent timeout**: `asyncio.wait_for(60s)` prevents hung LLM calls from blocking the UI indefinitely
- **Missing preview URLs**: When `preview_creative` returns no URLs (format has no preview in registry, or agent sent a hallucinated format_id that was not caught by the fallback), the UI shows "No preview available" instead of silently rendering nothing
- **Preview rendering**: HTML is fetched server-side via `requests` to bypass `X-Frame-Options`/CSP headers, then injected via `st.components.v1.html` inside the chat message context. Load failures show a user-friendly message without exposing raw errors.
- **Missing API key**: Validated at startup with a generic error message before any rendering occurs
- **Server unreachable**: Shown as a user-friendly message without exposing internal URLs or server details
- **Tool name resolution**: LangGraph `ToolMessage.name` can be empty — the agent falls back to matching `tool_call_id` against `AIMessage.tool_calls` to correctly identify `preview_creative` results

---

## Deployment

The app is deployed on [Railway](https://railway.app) as a single service running both the MCP server and Streamlit UI via `start.sh`.

### How it works

`start.sh` starts the MCP server in the background, waits 5 seconds for it to be ready, then launches the Streamlit app on the Railway-assigned `$PORT`:

```bash
#!/bin/bash
python mcp_server.py sse &
sleep 5
streamlit run app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true
```

### Railway config (`railway.streamlit.toml`)

```toml
[build]
builder = "nixpacks"

[deploy]
startCommand = "bash start.sh"
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 3
```

### Environment variables

Set these in the Railway dashboard under your service's Variables tab:

| Variable | Description |
|---|---|
| `GEMINI_API_KEY` | Your Gemini API key |
| `MCP_SERVER_URL` | Set to `http://localhost:8000/sse` since both processes run in the same container |

> `PORT` is automatically injected by Railway, hence it doesn't need to be set manually.

### Steps to deploy

1. Push the repo to GitHub
2. Create a new Railway project and connect the repo
3. Railway auto-detects `railway.streamlit.toml` and uses `bash start.sh` as the start command
4. Add `GEMINI_API_KEY` and `MCP_SERVER_URL` in the Variables tab
5. Deploy — Railway builds with Nixpacks and installs `requirements.txt` automatically

The agentic platform is available on public URL : https://ad-creative-agent-production.up.railway.app/
