# Creatives Explorer Agent — Technical Report

## Workflow Structure

```
User (Streamlit UI)
    │
    ▼
app.py  ──────────────────────────────────────────────────────────
│  • Validates GEMINI_API_KEY at startup                          │
│  • Detects follow-up preview triggers ("show", "yes", "continue", "sure", etc.) │
│  • Injects last known format_id into message for context                         │
│  • Fallback: replaces hallucinated format_id with last known good one            │
│  • Renders chat, format cards, and previews inside chat message area             │
    │
    ▼
react_agent.py (LangGraph ReAct)
│  • Gemini 2.5 Flash Lite — temperature 0.2, thinking_budget 512
│  • Reasoning loop: Thought → Action → Observation → Repeat    │
│  • 60s timeout on agent.ainvoke                                │
│  • Keeps last 3 conversation turns (6 messages) as context    │
    │
    ├── list_creative_formats(@tool) ──────────────────────────────
    │       Searches 48 Adzymic formats by name, dimensions, etc.  │
    │       type filter only for explicit: video/display/audio/dooh │
    │                                                              │
    └── preview_creative(@tool) ───────────────────────────────────
            Returns real Adzymic preview URLs for a format         │
            Fetched server-side to bypass X-Frame-Options headers  │
    │
    ▼
tool_handler (app.py)  ←── bridges agent tools to MCP client
    │
    ▼
mcp_client.py  ←── SSE client with retry (3 attempts, async backoff)
    │
    ▼
mcp_server.py (FastMCP, localhost:8000/sse)
    │  • list_creative_formats — filters, fuzzy name search with stemming
    │  • preview_creative — single / batch / variant modes
    │
    ▼
registry/creative_formats.json  ←── 48 Adzymic ad formats (AdCP schema)
```

---

## Design Rationale

### Context Handling
The agent receives only the last 3 conversation turns to keep the prompt lean and avoid token bloat. However, pure text history loses tool result data (format_ids, specs) between turns. To solve this, `app.py` maintains `st.session_state["last_format_id"]` — whenever `list_creative_formats` returns results, the first format's ID is stored. On follow-up preview requests ("show me", "yes", "continue", "sure", etc.), the format_id is injected directly into the enriched user message sent to the agent, bypassing the need for the agent to re-fetch. Additionally, if the agent hallucinates a format_id (wrong `agent_url` or ID not prefixed with `adzymic-`), `tool_handler` silently replaces it with the last known good one from session state. The stale format_id is cleared when the user asks about a completely new topic.

### Type Filter vs Name Search
The `type` field in the AdCP spec accepts only `audio`, `video`, `display`, `dooh`. Brand and platform names like "facebook", "instagram", "youtube", "tiktok" are not types — they are format name keywords. The agent is instructed (via both the tool docstring and system prompt) to always route these through `name_search` and never infer a `type` from them. This prevents the agent from returning "no DOOH formats available" when the user asks for "facebook ads".

### ReAct over Simple Tool Calling
A standard tool-calling loop calls tools mechanically. The ReAct pattern (Reasoning + Acting) makes the LLM explicitly reason before each action — checking whether the format was already fetched, whether the request is a follow-up, and what single keyword to use for search. This reduces redundant tool calls and handles ambiguous inputs like "caurosel overlap show me" more gracefully.

### Fuzzy Name Search
Format names like "Feature Scrolled Ad" won't match a query like "feature scroller". The MCP server applies suffix stemming (strips `er`, `ed`, `ing`, `ler`, `led`, `s`) and multi-word matching (all words in the query must appear in the format name). This makes search resilient to typos and natural language variations without requiring a vector database.

### Error Recovery
- **MCP client**: 3 retries with async exponential backoff (`asyncio.sleep`) — non-blocking, won't freeze the event loop
- **Agent timeout**: `asyncio.wait_for(60s)` prevents hung LLM calls from blocking the UI indefinitely
- **Missing preview URLs**: When `preview_creative` returns no URLs (format has no preview in registry, or agent sent a hallucinated format_id that was not caught by the fallback), the UI shows "No preview available" instead of silently rendering nothing
- **Preview rendering**: HTML is fetched server-side via `requests` to bypass `X-Frame-Options`/CSP headers, then injected via `st.components.v1.html` inside the chat message context
- **Missing API key**: Validated at startup with a clear error message before any rendering occurs
- **Tool name resolution**: LangGraph `ToolMessage.name` can be empty — the agent falls back to matching `tool_call_id` against `AIMessage.tool_calls` to correctly identify `preview_creative` results
