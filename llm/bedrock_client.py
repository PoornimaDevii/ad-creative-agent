"""
LLM client — uses Gemini 2.5 Flash Lite via LangChain ChatGoogleGenerativeAI with tool calling.

Responsibilities:
- Send user messages to Gemini with tool calling enabled
- Route tool calls to MCP server via tool_handler
- Log all MCP calls with tool name, context_id, and status to a file
- Retry on transient failures (up to MAX_RETRIES per tool call)
- Guard against infinite agentic loops with MAX_ITERATIONS
"""

import json
import logging
import os
import time
from typing import Callable
from uuid import uuid4

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage

# ====================== Logger Setup ======================
# Write logs to a file so they are visible regardless of Streamlit stdout capture

log_path = os.path.join(os.path.dirname(__file__), "..", "agent.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(),
    ],
    force=True,
)
logger = logging.getLogger("gemini_client")

# ====================== Constants ======================

MODEL_ID = "gemini-2.5-flash-lite"
MAX_ITERATIONS = 5   # max agentic loop iterations before giving up
MAX_RETRIES = 3      # max retries per tool call on transient failure
RETRY_DELAY = 1.0    # seconds between retries

# ====================== Tool Schemas ======================

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

# ====================== System Prompt ======================

SYSTEM_PROMPT = """You are an AdCP Creative Agent assistant for the Adzymic platform.
You help users discover creative ad formats and generate previews.

You have access to two tools:
- list_creative_formats: to search and filter the 48 available Adzymic ad formats
- preview_creative: to generate preview URLs for a specific format

TOOL CALLING RULES:
1. For ANY question about formats, call list_creative_formats ONCE with appropriate filters
2. If user asks to preview a specific format, call list_creative_formats ONCE then preview_creative ONCE
3. After receiving tool results, STOP calling tools and write your response immediately
4. NEVER call the same tool twice in one conversation turn
5. NEVER call list_creative_formats more than once per user message

FOR LIST REQUESTS (e.g. "show carousel formats", "list video formats"):
- Call list_creative_formats with name_search using a single keyword
- Then respond with a brief summary of what was found

FOR PREVIEW REQUESTS (e.g. "preview product carousel", "show me the lead gen ad"):
- Call list_creative_formats to find the format
- Call preview_creative with the format_id from the result
- Then write a SHORT factual description using ONLY data from the tool result:
  * Format name
  * Available sizes (from renders field only)
  * Required assets with exact character limits
  * Optional assets
  * DCO availability
- End with: "Here is the preview:"

RESPONSE RULES:
- Always respond in plain English after receiving tool results
- NEVER include preview URLs in your text — the UI renders them automatically
- NEVER expose tool names or JSON to the user
- ONLY use facts present in the tool result — never infer or add details
- Keep responses concise"""


# ====================== Tool Call with Retry ======================

async def _call_tool_with_retry(
    tool_handler: Callable,
    tool_name: str,
    tool_input: dict,
    context_id: str,
) -> dict:
    """
    Call a tool via tool_handler with retry logic.

    Logs each attempt with tool name, context_id, and status.
    Retries up to MAX_RETRIES times on transient failures with exponential backoff.
    Returns an error dict if all retries are exhausted.
    """
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        logger.info(f"[MCP_CALL] context_id={context_id} tool={tool_name} attempt={attempt}/{MAX_RETRIES} input_keys={list(tool_input.keys())}")
        try:
            result = await tool_handler(tool_name, tool_input)

            # Check for error status in result — treat as non-completed
            if isinstance(result, dict) and result.get("status") in ("failed", "error"):
                logger.warning(f"[MCP_ERROR_STATUS] context_id={context_id} tool={tool_name} attempt={attempt} status={result.get('status')} error={result.get('error')}")
                last_error = result.get("error", "Unknown error")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY * attempt)
                continue

            logger.info(f"[MCP_OK] context_id={context_id} tool={tool_name} attempt={attempt} result_keys={list(result.keys()) if isinstance(result, dict) else type(result).__name__}")
            return result

        except Exception as e:
            last_error = str(e)
            logger.warning(f"[MCP_RETRY] context_id={context_id} tool={tool_name} attempt={attempt} error={type(e).__name__}: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)

    # All retries exhausted
    logger.error(f"[MCP_FAILED] context_id={context_id} tool={tool_name} after {MAX_RETRIES} attempts. last_error={last_error}")
    return {"error": last_error, "status": "failed"}


# ====================== Main LLM Invocation ======================

async def invoke_with_tools(
    user_message: str,
    tool_handler: Callable,
    conversation_history: list = None,
    context_id: str = None,
) -> dict:
    """
    Send a user message to Gemini with tool calling enabled.

    Runs an agentic loop:
    1. Send message to Gemini
    2. If model calls a tool → execute via _call_tool_with_retry → feed result back
    3. Repeat until model returns a final text response or MAX_ITERATIONS reached

    Args:
        user_message: Natural language query from the user
        tool_handler: Async callable(tool_name, tool_input) -> dict
        conversation_history: Prior turns in simple {role, content} format
        context_id: Optional trace ID (auto-generated if not provided)

    Returns:
        Dict with keys: response, tool_calls, tool_results, messages, context_id
    """
    context_id = context_id or str(uuid4())[:8]
    logger.info(f"[INVOKE_START] context_id={context_id} message_len={len(user_message)}")

    # Initialize Gemini LLM with tool schemas bound
    try:
        llm = ChatGoogleGenerativeAI(
            model=MODEL_ID,
            google_api_key=os.getenv("GEMINI_API_KEY"),
            thinking_budget=512,
        ).bind_tools(TOOLS_SCHEMA)
        logger.info(f"[LLM_INIT_OK] context_id={context_id} model={MODEL_ID}")
    except Exception as e:
        logger.error(f"[LLM_INIT_ERROR] context_id={context_id} error={type(e).__name__}: {e}", exc_info=True)
        return {
            "response": "I encountered an error initialising the AI model. Please try again.",
            "tool_calls": [], "tool_results": [], "messages": conversation_history or [],
            "context_id": context_id,
        }

    # Build message list starting with system prompt
    messages = [SystemMessage(content=SYSTEM_PROMPT)]

    # Convert stored conversation history into LangChain message objects
    for msg in (conversation_history or []):
        role = msg.get("role")
        text = "".join(block.get("text", "") for block in msg.get("content", []))
        if not text:
            continue
        if role == "user":
            messages.append(HumanMessage(content=text))
        elif role == "assistant":
            messages.append(AIMessage(content=text))

    # Append the current user message
    messages.append(HumanMessage(content=user_message))

    tool_calls = []
    tool_results = []
    final_response = ""
    iteration = 0
    tools_called = set()  # track which tools have been called to prevent loops

    while iteration < MAX_ITERATIONS:
        iteration += 1
        logger.info(f"[LLM_CALL] context_id={context_id} iteration={iteration}/{MAX_ITERATIONS}")

        try:
            response = await llm.ainvoke(messages)
            logger.info(f"[LLM_RESPONSE] context_id={context_id} iteration={iteration} has_tool_calls={bool(response.tool_calls)} content_len={len(response.content or '')}")
        except Exception as e:
            logger.error(f"[LLM_ERROR] context_id={context_id} iteration={iteration} error={type(e).__name__}: {e}", exc_info=True)
            final_response = "I encountered an error processing your request. Please try again."
            break

        # Append model response to message history for next iteration
        messages.append(response)

        if response.tool_calls:
            # Filter out duplicate tool calls to prevent loops
            new_tool_calls = [
                tc for tc in response.tool_calls
                if tc["name"] not in tools_called
            ]

            if not new_tool_calls:
                # All tools already called — force model to respond
                logger.warning(f"[LOOP_DETECTED] context_id={context_id} — all tools already called, forcing response")
                messages.append(HumanMessage(content="You have already retrieved the data. Now write your final response to the user based on the tool results above. Do not call any more tools."))
                continue

            # Execute each new tool call
            for tc in new_tool_calls:
                tool_name = tc["name"]
                tool_input = tc["args"]
                tool_id = tc["id"]

                tools_called.add(tool_name)
                tool_calls.append({"name": tool_name, "input": tool_input})

                result = await _call_tool_with_retry(tool_handler, tool_name, tool_input, context_id)
                tool_results.append({"name": tool_name, "result": result})

                messages.append(ToolMessage(
                    content=json.dumps(result),
                    tool_call_id=tool_id,
                ))
        else:
            # No tool calls — extract final text response
            content = response.content
            if isinstance(content, list):
                final_response = " ".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                )
            else:
                final_response = content or ""
            logger.info(f"[LLM_DONE] context_id={context_id} response_len={len(final_response)} total_tool_calls={len(tool_calls)}")
            break

    # Guard: if loop exhausted without a response
    if iteration >= MAX_ITERATIONS and not final_response:
        logger.error(f"[MAX_ITERATIONS] context_id={context_id} — loop exceeded {MAX_ITERATIONS} iterations")
        # If we have tool results, generate a fallback response instead of an error
        if tool_results:
            final_response = "Here are the results based on your request."
        else:
            final_response = "I was unable to complete your request. Please try a simpler query."

    # Auto-preview fallback: if list_creative_formats was called but preview_creative wasn't,
    # call preview_creative for the first format in the result
    list_tr = next((tr for tr in tool_results if tr["name"] == "list_creative_formats"), None)
    preview_tr = next((tr for tr in tool_results if tr["name"] == "preview_creative"), None)
    if list_tr and not preview_tr:
        formats = list_tr["result"].get("formats", [])
        if formats:
            fmt_id = formats[0].get("format_id", {})
            logger.info(f"[AUTO_PREVIEW] list called but preview missing, calling preview_creative for {fmt_id}")
            try:
                preview_result = await tool_handler("preview_creative", {"format_id": fmt_id, "assets": {}})
                tool_results.append({"name": "preview_creative", "result": preview_result})
                logger.info(f"[AUTO_PREVIEW_OK] preview_creative called successfully")
            except Exception as e:
                logger.error(f"[AUTO_PREVIEW_ERROR] {e}")

    # Store updated history in simple format for Streamlit session state
    updated_history = list(conversation_history or [])
    updated_history.append({"role": "user", "content": [{"text": user_message}]})
    updated_history.append({"role": "assistant", "content": [{"text": final_response}]})

    logger.info(f"[INVOKE_END] context_id={context_id} response_len={len(final_response)} tool_calls={len(tool_calls)}")

    return {
        "response": final_response.strip(),
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "messages": updated_history,
        "context_id": context_id,
    }
