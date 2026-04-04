"""
LLM client — uses Gemini 2.5 Flash Lite via LangChain ChatGoogleGenerativeAI with tool calling.
"""

import json
import logging
import os
from typing import Callable
from uuid import uuid4

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("gemini_client")

MODEL_ID = "gemini-2.5-flash-lite"
MAX_ITERATIONS = 5

TOOLS_SCHEMA = [
    {
        "name": "list_creative_formats",
        "description": (
            "Discover creative formats supported by the Adzymic creative agent. "
            "Returns full format specifications including asset requirements and technical constraints. "
            "Use this when the user asks about available formats, wants to browse or filter formats, "
            "or needs to find formats by type, size, asset type, or name."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name_search": {
                    "type": "string",
                    "description": "Search formats by name using a single keyword only e.g. 'carousel', 'video', 'facebook'."
                },
                "type": {
                    "type": "string",
                    "description": "Filter by type: audio, video, display, dooh."
                },
                "asset_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter to formats accepting these asset types: image, video, audio, text, html, javascript, url."
                },
                "max_width": {"type": "integer", "description": "Maximum width in pixels."},
                "max_height": {"type": "integer", "description": "Maximum height in pixels."},
                "min_width": {"type": "integer", "description": "Minimum width in pixels."},
                "min_height": {"type": "integer", "description": "Minimum height in pixels."},
                "is_responsive": {"type": "boolean", "description": "Filter for responsive formats."},
                "pagination": {"type": "object", "description": "Pagination: max_results (1-100) and cursor."},
            },
        },
    },
    {
        "name": "preview_creative",
        "description": (
            "Generate a preview of a creative format. Returns real Adzymic preview URLs. "
            "Use this when the user wants to preview or see what an ad format looks like."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "format_id": {
                    "type": "object",
                    "description": "Format identifier with agent_url and id.",
                    "properties": {
                        "agent_url": {"type": "string"},
                        "id": {"type": "string"},
                    },
                    "required": ["agent_url", "id"],
                },
                "assets": {
                    "type": "object",
                    "description": "Assets for the creative e.g. hero_image, headline.",
                },
                "output_format": {
                    "type": "string",
                    "description": "url (default) or html.",
                },
            },
            "required": ["format_id"],
        },
    },
]

SYSTEM_PROMPT = """You are an AdCP Creative Agent assistant for the Adzymic platform.
You help users discover creative ad formats and generate previews.

You have access to two tools:
- list_creative_formats: to search and filter the 48 available Adzymic ad formats
- preview_creative: to generate preview URLs for a specific format

Rules for using list_creative_formats:
- When user asks about any format by name, ALWAYS call list_creative_formats first
- Use name_search with a single keyword only e.g. 'carousel', 'video', 'lead', 'facebook', 'chatbot', 'countdown'
- Never combine multiple types as comma-separated string
- Call list_creative_formats ONLY ONCE per query

Rules for using preview_creative:
- When user asks to preview or see a SPECIFIC format, ALWAYS:
  1. Call list_creative_formats to find it
  2. IMMEDIATELY call preview_creative with the format_id from the result
- NEVER stop after list_creative_formats when user asked to preview a specific format
- NEVER say the preview URL is not available

Response rules:
- Always respond in plain English
- Never expose tool names, JSON, or parameters in your response
- Never include preview URLs or links in your text response — the UI renders previews automatically
- When a preview is requested, write a SHORT description using ONLY facts from the tool result:
  - Format name, available sizes (from renders only), required assets with exact character limits, optional assets, DCO availability
  - Do NOT add any information not present in the tool result
- End your description with: "Here is the preview:"
- Keep responses concise"""


async def invoke_with_tools(
    user_message: str,
    tool_handler: Callable,
    conversation_history: list = None,
    context_id: str = None,
) -> dict:
    import traceback
    context_id = context_id or str(uuid4())[:8]
    print(f"[INVOKE] context_id={context_id} message={user_message[:80]}", flush=True)

    try:
        llm = ChatGoogleGenerativeAI(
            model=MODEL_ID,
            google_api_key=os.getenv("GEMINI_API_KEY"),
        ).bind_tools(TOOLS_SCHEMA)
        print(f"[GEMINI] LLM initialized model={MODEL_ID}", flush=True)
    except Exception as e:
        print(f"[GEMINI_INIT_ERROR] {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        return {"response": "I encountered an error processing your request. Please try again.", "tool_calls": [], "tool_results": [], "messages": conversation_history or [], "context_id": context_id}

    # Build message list
    messages = [SystemMessage(content=SYSTEM_PROMPT)]

    # Convert conversation history
    for msg in (conversation_history or []):
        role = msg.get("role")
        text = ""
        for block in msg.get("content", []):
            if "text" in block:
                text += block["text"]
        if not text:
            continue
        if role == "user":
            messages.append(HumanMessage(content=text))
        elif role == "assistant":
            messages.append(AIMessage(content=text))

    messages.append(HumanMessage(content=user_message))

    tool_calls = []
    tool_results = []
    final_response = ""
    iteration = 0

    while iteration < MAX_ITERATIONS:
        iteration += 1
        logger.info(f"[LLM_CALL] context_id={context_id} iteration={iteration}/{MAX_ITERATIONS}")
        print(f"[LLM_CALL] context_id={context_id} iteration={iteration}/{MAX_ITERATIONS}", flush=True)

        try:
            response = await llm.ainvoke(messages)
            logger.info(f"[LLM_RESPONSE] context_id={context_id} type={type(response).__name__} tool_calls={len(response.tool_calls) if hasattr(response, 'tool_calls') else 'N/A'} content_len={len(response.content) if hasattr(response, 'content') else 'N/A'}")
            print(f"[LLM_RESPONSE] tool_calls={response.tool_calls} content={response.content[:100] if hasattr(response, 'content') and response.content else 'empty'}", flush=True)
        except Exception as e:
            logger.error(f"[LLM_ERROR] context_id={context_id} iteration={iteration} error={type(e).__name__}: {e}", exc_info=True)
            print(f"[LLM_ERROR] {type(e).__name__}: {e}", flush=True)
            import traceback; traceback.print_exc()
            final_response = "I encountered an error processing your request. Please try again."
            break

        messages.append(response)

        if response.tool_calls:
            for tc in response.tool_calls:
                tool_name = tc["name"]
                tool_input = tc["args"]
                tool_id = tc["id"]

                logger.info(f"[TOOL_CALL] context_id={context_id} tool={tool_name} input={tool_input}")
                tool_calls.append({"name": tool_name, "input": tool_input})

                try:
                    result = await tool_handler(tool_name, tool_input)
                    logger.info(f"[TOOL_OK] context_id={context_id} tool={tool_name} result_keys={list(result.keys()) if isinstance(result, dict) else type(result)}")
                except Exception as e:
                    logger.error(f"[TOOL_EXCEPTION] context_id={context_id} tool={tool_name} error={type(e).__name__}: {e}", exc_info=True)
                    result = {"error": str(e), "status": "failed"}

                tool_results.append({"name": tool_name, "result": result})
                messages.append(ToolMessage(
                    content=json.dumps(result),
                    tool_call_id=tool_id,
                ))
        else:
            final_response = response.content or ""
            logger.info(f"[LLM_DONE] context_id={context_id} response_len={len(final_response)} tool_calls_total={len(tool_calls)}")
            break

    if iteration >= MAX_ITERATIONS and not final_response:
        final_response = "I was unable to complete your request. Please try a simpler query."

    # Store history in simple format for session state
    updated_history = list(conversation_history or [])
    updated_history.append({"role": "user", "content": [{"text": user_message}]})
    updated_history.append({"role": "assistant", "content": [{"text": final_response}]})

    return {
        "response": final_response.strip(),
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "messages": updated_history,
        "context_id": context_id,
    }
