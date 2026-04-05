"""
HTTP wrapper for the MCP server.

Runs the FastMCP SSE transport as the root ASGI app so the MCP server is
reachable over HTTP at /sse.  The Streamlit service connects via:

    http://creative-mcp-server.railway.internal:<PORT>/sse

FastMCP's sse_app() exposes two routes internally:
  GET  /sse       — opens the SSE stream (event source)
  POST /messages/ — receives client messages

Running it directly (without app.mount) avoids the 307 redirect / 404
that FastAPI's mount produces when the path has no trailing slash.

The PORT environment variable controls which port uvicorn listens on
(defaults to 8080 to match the Railway internal service URL used by the
Streamlit app).
"""

import os
import uvicorn
from mcp_server import mcp  # import the FastMCP instance from mcp_server.py

# Use the FastMCP SSE ASGI app directly as the root application.
# This avoids FastAPI's mount() trailing-slash redirect behaviour which
# causes "GET /sse  → 307" and "GET /sse/ → 404" when the sub-app is
# mounted at a prefix.
app = mcp.sse_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    print(f"Starting Creative MCP HTTP server on port {port}")
    print(f"MCP SSE endpoint: http://0.0.0.0:{port}/sse")
    uvicorn.run(app, host="0.0.0.0", port=port)
