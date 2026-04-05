"""
HTTP wrapper for the MCP server.

Mounts the FastMCP SSE transport onto a FastAPI app so the MCP server is
reachable over HTTP at /sse.  The Streamlit service connects via:

    http://creative-mcp-server.railway.internal:<PORT>/sse

The PORT environment variable controls which port uvicorn listens on
(defaults to 8080 to match the Railway internal service URL used by the
Streamlit app).
"""

import os
import uvicorn
from fastapi import FastAPI
from mcp_server import mcp  # import the FastMCP instance from mcp_server.py

# Build the FastAPI app and mount the MCP SSE ASGI app at /sse
app = FastAPI(title="Creative MCP Server")
app.mount("/sse", mcp.sse_app())


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    print(f"Starting Creative MCP HTTP server on port {port}")
    print(f"MCP SSE endpoint: http://0.0.0.0:{port}/sse")
    uvicorn.run(app, host="0.0.0.0", port=port)
