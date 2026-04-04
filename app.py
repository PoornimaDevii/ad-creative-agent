"""
app.py — AdCP Creative Agent Platform
Connects: Streamlit UI + AWS Bedrock (Claude Haiku) + MCP Server (SSE)
"""

import asyncio
import os
from uuid import uuid4
import streamlit as st
from dotenv import load_dotenv

from frontend.ui import (
    render_page_config,
    render_header,
    render_chat_interface,
    render_format_card,
    render_tool_call_indicator,
    render_error,
    render_server_status,
    _render_preview_inline,
)
from llm.bedrock_client import invoke_with_tools
from mcp_client_module.mcp_client import list_creative_formats, preview_creative

load_dotenv()

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000/sse")


# ====================== Tool Handler ======================

async def tool_handler(tool_name: str, tool_input: dict) -> dict:
    import logging
    logger = logging.getLogger("tool_handler")
    logger.info(f"[TOOL_HANDLER] tool={tool_name} input={tool_input}")
    if tool_name == "list_creative_formats":
        return await list_creative_formats(**tool_input)
    elif tool_name == "preview_creative":
        format_id = tool_input.get("format_id") or tool_input.get("creative_manifest", {}).get("format_id", {})
        assets = tool_input.get("assets") or tool_input.get("creative_manifest", {}).get("assets", {})
        result = await preview_creative(
            format_id=format_id,
            assets=assets,
            output_format=tool_input.get("output_format", "url"),
            inputs=tool_input.get("inputs"),
        )
        logger.info(f"[TOOL_HANDLER] preview result keys={list(result.keys()) if isinstance(result, dict) else result}")
        return result
    return {"error": f"Unknown tool: {tool_name}"}


# ====================== Server Health Check ======================

async def check_server() -> bool:
    try:
        result = await list_creative_formats(pagination={"max_results": 1})
        return "formats" in result
    except Exception:
        return False


# ====================== Main App ======================

def main():
    render_page_config()
    render_header()

    connected = asyncio.run(check_server())
    render_server_status(connected, MCP_SERVER_URL)

    if not connected:
        render_error(
            f"Cannot connect to MCP server at {MCP_SERVER_URL}. "
            "Make sure mcp_server.py is running with SSE transport."
        )
        st.stop()

    user_input = render_chat_interface()

    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                context_id = str(uuid4())[:8]
                try:
                    result = asyncio.run(invoke_with_tools(
                        user_message=user_input,
                        tool_handler=tool_handler,
                        conversation_history=st.session_state.get("conversation_history", []),
                        context_id=context_id,
                    ))
                except Exception as e:
                    import traceback
                    print(f"[APP ERROR] {type(e).__name__}: {e}", flush=True)
                    traceback.print_exc()
                    st.error(f"{type(e).__name__}: {e}")
                    st.stop()
                response = result["response"]
                tool_calls = result["tool_calls"]
                tool_results = result["tool_results"]

            st.markdown(response)
            render_tool_call_indicator(tool_calls)

            st.session_state.conversation_history = result["messages"]

            # Extract preview URLs
            preview_urls = []
            for tr in tool_results:
                if tr["name"] == "preview_creative":
                    for preview in tr["result"].get("previews", []):
                        for render in preview.get("renders", []):
                            url = render.get("preview_url")
                            if url:
                                preview_urls.append({
                                    "url": url,
                                    "name": preview.get("input", {}).get("name", "Preview"),
                                })

            st.session_state.messages.append({
                "role": "assistant",
                "content": response,
                "tool_calls": tool_calls,
                "preview_urls": preview_urls or None,
            })

            for tr in tool_results:
                if tr["name"] == "list_creative_formats":
                    formats = tr["result"].get("formats", [])
                    if not formats:
                        st.info("🔍 No formats matched. Try a different query.")
                    else:
                        st.divider()
                        st.caption(f"📦 {len(formats)} formats found")
                        cols = st.columns(2)
                        for i, fmt in enumerate(formats):
                            with cols[i % 2]:
                                render_format_card(fmt)

            if preview_urls:
                st.divider()
                st.caption(f"👁 {len(preview_urls)} preview(s)")
                if len(preview_urls) > 1:
                    tabs = st.tabs([p["name"] for p in preview_urls])
                    for tab, p in zip(tabs, preview_urls):
                        with tab:
                            _render_preview_inline(p["url"])
                else:
                    _render_preview_inline(preview_urls[0]["url"])

        st.rerun()


if __name__ == "__main__":
    main()
