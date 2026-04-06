#!/bin/bash

# Start MCP server in background
python mcp_server.py sse &

# Wait for MCP server to start
sleep 5

# Start Streamlit app
streamlit run app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true
