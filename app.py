"""
app.py — Creatives Explorer Agent
Connects: Streamlit UI + ReAct Agent (LangGraph + Gemini) + MCP Server (SSE)
"""

import asyncio
import logging
import os
import traceback
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
from llm.react_agent import invoke_react_agent
from mcp_client_module.mcp_client import list_creative_formats, preview_creative

load_dotenv()

logger = logging.getLogger("app")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8080/mcp")
print("MCP_SERVER_URL --------" , MCP_SERVER_URL)
PREVIEW_TRIGGERS = {"preview", "show", "see", "yes", "show me", "show a preview", "preview it", "yes continue", "continue", "go ahead", "sure", "ok", "okay", "do it"}


# ====================== Tool Handler ======================

async def tool_handler(tool_name: str, tool_input: dict) -> dict:
    logger.info(f"[TOOL_HANDLER] tool={tool_name} input={tool_input}")
    if tool_name == "list_creative_formats":
        return await list_creative_formats(**tool_input)
    elif tool_name == "preview_creative":
        format_id = tool_input.get("format_id") or tool_input.get("creative_manifest", {}).get("format_id", {})
        assets = tool_input.get("assets") or tool_input.get("creative_manifest", {}).get("assets", {})

        # Fallback: if agent hallucinated format_id, use last known good one from session
        last_fid = st.session_state.get("last_format_id", {})
        if last_fid and (
            not format_id.get("id")
            or not format_id.get("agent_url")
            or format_id.get("agent_url") != last_fid.get("agent_url")
            or not format_id.get("id", "").startswith("adzymic-")
        ):
            format_id = last_fid
            logger.info(f"[TOOL_HANDLER] using last_format_id fallback: {format_id}")

        result = await preview_creative(
            format_id=format_id,
            assets=assets,
            output_format=tool_input.get("output_format", "url"),
            inputs=tool_input.get("inputs"),
        )
        logger.info(f"[TOOL_HANDLER] preview result keys={list(result.keys()) if isinstance(result, dict) else result}")
        return result
    return {"error": "Unsupported operation.", "status": "failed"}


# ====================== Server Health Check ======================

async def check_server() -> bool:
    try:
        result = await list_creative_formats(pagination={"max_results": 1})
        return "formats" in result
    except Exception:
        return False


# ====================== Main App ======================

def main():
    # Validate required env vars early
    if not os.getenv("GEMINI_API_KEY"):
        st.error("Configuration error: missing API key. Please contact support.")
        st.stop()

    render_page_config()
    render_header()
    connected = asyncio.run(check_server())
    render_server_status(connected, MCP_SERVER_URL)

    if not connected:
        render_error(
            "Cannot connect to the creative formats server. "
            "Please try again later or contact support."
        )
        st.stop()

    user_input = render_chat_interface()

    if user_input:
        is_preview_followup = (
            user_input.strip().lower() in PREVIEW_TRIGGERS
            or any(user_input.strip().lower().startswith(t) for t in PREVIEW_TRIGGERS)
        )

        # Enrich message with format_id context for follow-up preview requests
        enriched_input = user_input
        if is_preview_followup and st.session_state.get("last_format_id"):
            fmt_id = st.session_state["last_format_id"]
            enriched_input = (
                f"{user_input} "
                f"[Context: use format_id agent_url={fmt_id.get('agent_url')} id={fmt_id.get('id')}]"
            )

        # Append and immediately render user message
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user", avatar="👤"):
            st.markdown(user_input)

        with st.chat_message("assistant", avatar="⚙️"):
            with st.spinner("Thinking..."):
                context_id = str(uuid4())[:8]
                try:
                    result = asyncio.run(invoke_react_agent(
                        user_message=enriched_input,
                        tool_handler=tool_handler,
                        conversation_history=st.session_state.get("conversation_history", []),
                        context_id=context_id,
                    ))
                except Exception as e:
                    logger.error(f"[APP ERROR] {type(e).__name__}: {e}\n{traceback.format_exc()}")
                    result = {
                        "response": "Something went wrong. Please try again.",
                        "tool_calls": [],
                        "tool_results": [],
                        "messages": st.session_state.get("conversation_history", []),
                    }

            response = result["response"]
            tool_calls = result["tool_calls"]
            tool_results = result["tool_results"]

            st.markdown(response)
            render_tool_call_indicator(tool_calls)

            st.session_state.conversation_history = result["messages"]

            # Extract preview URLs — primary render only
            preview_urls = []
            # Update last_format_id from any list_creative_formats result this turn (needed for same-turn preview fallback)
            for tr in tool_results:
                if tr["name"] == "list_creative_formats":
                    formats = tr["result"].get("formats", [])
                    if formats:
                        st.session_state["last_format_id"] = formats[0].get("format_id", {})
            for tr in tool_results:
                if tr["name"] == "preview_creative":
                    result_data = tr["result"]
                    logger.info(f"[PREVIEW_EXTRACT] keys={list(result_data.keys()) if isinstance(result_data, dict) else type(result_data)}")
                    for preview in result_data.get("previews", []):
                        renders = preview.get("renders", [])
                        primary = next(
                            (r for r in renders if r.get("role") == "primary" and r.get("preview_url")),
                            next((r for r in renders if r.get("preview_url")), None)
                        )
                        if primary:
                            preview_urls.append({
                                "url": primary["preview_url"],
                                "name": preview.get("input", {}).get("name", "Preview"),
                            })
            logger.info(f"[PREVIEW_URLS] extracted={len(preview_urls)}")

            # Show no-preview message if preview was requested but unavailable
            preview_was_requested = any(tr["name"] == "preview_creative" for tr in tool_results)
            if preview_was_requested and not preview_urls:
                st.info("No preview available for this format.")

            st.session_state.messages.append({
                "role": "assistant",
                "content": response,
                "tool_calls": tool_calls,
                "preview_urls": preview_urls or None,
            })

            # Show format cards only when not showing a preview
            for tr in tool_results:
                if tr["name"] == "list_creative_formats" and not preview_urls:
                    formats = tr["result"].get("formats", [])
                    if not formats:
                        st.info("No formats matched. Try a different query.")
                    else:
                        # Store last format_id for follow-up preview requests
                        st.session_state["last_format_id"] = formats[0].get("format_id", {})
                        st.divider()
                        st.caption(f"📦 {len(formats)} formats found")
                        cols = st.columns(2)
                        for i, fmt in enumerate(formats):
                            with cols[i % 2]:
                                render_format_card(fmt)
                elif tr["name"] == "list_creative_formats" and preview_urls:
                    # Still store last_format_id even when showing preview
                    formats = tr["result"].get("formats", [])
                    if formats:
                        st.session_state["last_format_id"] = formats[0].get("format_id", {})

            # Clear stale format_id if user asked a completely new question
            if not is_preview_followup and not any(tr["name"] == "list_creative_formats" for tr in tool_results):
                st.session_state.pop("last_format_id", None)

            if preview_urls:
                st.divider()
                if len(preview_urls) > 1:
                    tabs = st.tabs([p["name"] for p in preview_urls])
                    for tab, p in zip(tabs, preview_urls):
                        with tab:
                            _render_preview_inline(p["url"])
                else:
                    _render_preview_inline(preview_urls[0]["url"])


if __name__ == "__main__":
    main()
