"""
ReAct Agent — Creatives Explorer Agent
Uses LangGraph's prebuilt ReAct agent with Gemini 2.5 Flash Lite.

ReAct = Reasoning + Acting:
  - The LLM reasons about what to do (Thought)
  - Decides which tool to call (Action)
  - Observes the result (Observation)
  - Repeats until it has enough to respond
"""

import asyncio
import json
import logging
import os
from typing import Callable
from uuid import uuid4

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

# ====================== Logger ======================

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
logger = logging.getLogger("react_agent")

# ====================== Constants ======================

MODEL_ID = "gemini-2.5-flash-lite"
MAX_RETRIES = 3
RETRY_DELAY = 1.0
AGENT_TIMEOUT = 60  # seconds

# ====================== System Prompt ======================

SYSTEM_PROMPT = """You are an AdCP Creative Agent assistant for the Adzymic platform.
You help users discover creative ad formats and generate previews.

You have access to two tools:
- list_creative_formats: search and filter the 48 available Adzymic ad formats
- preview_creative: generate preview URLs for a specific format

REASONING APPROACH (ReAct):
Think step by step before acting:
1. Read ONLY the latest user message to understand what is being asked RIGHT NOW.
2. If it is a follow-up preview request ("show a preview", "preview it", "yes", "show me") and a format was already discussed in history, extract the format_id from history and call preview_creative directly WITHOUT calling list_creative_formats.
3. If it is a new format question, call list_creative_formats with a single keyword.
4. Never mix words from different messages when forming tool arguments.

TOOL RULES:
- name_search must be ONE single keyword from the format name only
  GOOD: "countdown", "carousel", "shake", "gallery", "flip", "facebook"
  BAD: "countdown ad", "carousel format", "show preview", "countdown adshow"
- Strip all words like: ad, ads, format, creative, show, preview, a, the
- NEVER use the type filter unless the user explicitly says one of these exact words: "video", "display", "audio", "dooh" — brand/platform names like "facebook", "instagram", "youtube", "tiktok" are NOT types, always use name_search for them
- Use dco_available=true when user asks for DCO formats
- Use pagination={"max_results": N} when user asks for a specific number of results e.g. "give me 3"
- For follow-up preview requests: find the last format_id object in conversation history (it has agent_url and id fields) and pass it EXACTLY as-is to preview_creative — never invent or shorten the id
- For new format requests: call list_creative_formats ONCE
- NEVER call list_creative_formats more than once per turn
- NEVER guess or construct a format_id — always copy it verbatim from the tool result (e.g. id='adzymic-carousel-standard-001', not 'carousel_standard')

PREVIEW DETECTION:
- If the user message contains "preview", treat it as a preview request
- For "preview X": call list_creative_formats with name_search=X first, then immediately call preview_creative with the first result's format_id
- After calling preview_creative, respond with ONE sentence only: "Here is the preview of [format name]:"
- NEVER write a description when the user asked for a preview

RESPONSE STRUCTURE:
For INFO/LIST requests:
- Write a descriptive paragraph about the format(s): purpose, sizes, assets, DCO support
- Do NOT say "Here is the preview:"

For follow-up questions about the SAME format:
- Answer only what was asked, do NOT repeat the full description

For PREVIEW requests:
- Write one sentence about the format
- End with exactly: "Here is the preview:"
- The UI renders the preview automatically

RULES:
- NEVER say "Here is the preview:" unless preview_creative was called
- NEVER include preview URLs in your text
- NEVER expose tool names or JSON
- ONLY use facts from tool results
- Be concise and accurate"""

# ====================== Tool Factory ======================

def make_tools(tool_handler: Callable) -> list:
    """Create LangChain tool wrappers that delegate to the MCP tool_handler."""

    @tool
    async def list_creative_formats(
        name_search: str = None,
        type: str = None,
        asset_types: list[str] = None,
        max_width: int = None,
        max_height: int = None,
        min_width: int = None,
        min_height: int = None,
        is_responsive: bool = None,
        dco_available: bool = None,
        pagination: dict = None,
    ) -> dict:
        """Discover creative formats supported by the Adzymic creative agent.
        Returns full format specifications including asset requirements and technical constraints.
        Use this when the user asks about available formats, wants to browse or filter formats,
        or needs to find formats by type, size, asset type, or name.

        Args:
            name_search: Search formats by name using a single keyword e.g. 'carousel', 'facebook', 'shake'
            type: Filter by format type. ONLY use when user explicitly says one of these exact words: 'audio', 'video', 'display', 'dooh'. Never infer type from brand names like 'facebook', 'instagram', 'youtube'.
            asset_types: Filter by asset types: image, video, audio, text, html, javascript, url
            max_width: Maximum width in pixels
            max_height: Maximum height in pixels
            min_width: Minimum width in pixels
            min_height: Minimum height in pixels
            is_responsive: Filter for responsive formats only
            dco_available: Filter for formats that support DCO (Dynamic Creative Optimization)
            pagination: Dict with max_results (1-100) and cursor
        """
        args = {k: v for k, v in {
            "name_search": name_search,
            "type": type,
            "asset_types": asset_types,
            "max_width": max_width,
            "max_height": max_height,
            "min_width": min_width,
            "min_height": min_height,
            "is_responsive": is_responsive,
            "dco_available": dco_available,
            "pagination": pagination,
        }.items() if v is not None}
        return await _call_with_retry(tool_handler, "list_creative_formats", args)

    @tool
    async def preview_creative(
        format_id: dict,
        assets: dict = None,
        output_format: str = "url",
    ) -> dict:
        """Generate a preview of a creative format. Returns real Adzymic preview URLs.
        Use this ONLY when the user explicitly asks to preview or see a format.

        Args:
            format_id: Dict with agent_url and id e.g. {"agent_url": "...", "id": "..."}
            assets: Optional assets dict e.g. {"hero_image": "...", "headline": "..."}
            output_format: "url" (default) or "html"
        """
        args = {
            "format_id": format_id,
            "assets": assets or {},
            "output_format": output_format,
        }
        return await _call_with_retry(tool_handler, "preview_creative", args)

    return [list_creative_formats, preview_creative]


async def _call_with_retry(tool_handler: Callable, tool_name: str, args: dict) -> dict:
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        logger.info(f"[TOOL_CALL] tool={tool_name} attempt={attempt}/{MAX_RETRIES}")
        try:
            result = await tool_handler(tool_name, args)
            if isinstance(result, dict) and result.get("status") in ("failed", "error"):
                last_error = result.get("error", "Unknown error")
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY * attempt)
                continue
            logger.info(f"[TOOL_OK] tool={tool_name}")
            return result
        except Exception as e:
            last_error = str(e)
            logger.warning(f"[TOOL_RETRY] tool={tool_name} attempt={attempt} error={e}")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY * attempt)
    logger.error(f"[TOOL_FAILED] tool={tool_name} last_error={last_error}")
    return {"error": last_error, "status": "failed"}


# ====================== Main Invocation ======================

async def invoke_react_agent(
    user_message: str,
    tool_handler: Callable,
    conversation_history: list = None,
    context_id: str = None,
) -> dict:
    """
    Run the ReAct agent for a user message.

    Args:
        user_message: Natural language query from the user
        tool_handler: Async callable(tool_name, tool_input) -> dict
        conversation_history: Prior turns in {role, content} format
        context_id: Optional trace ID

    Returns:
        Dict with keys: response, tool_calls, tool_results, messages, context_id
    """
    context_id = context_id or str(uuid4())[:8]
    logger.info(f"[REACT_START] context_id={context_id} message={user_message[:60]}")

    # Build LLM
    try:
        llm = ChatGoogleGenerativeAI(
            model=MODEL_ID,
            google_api_key=os.getenv("GEMINI_API_KEY"),
            temperature=0.2,
            thinking_budget=512,
        )
    except Exception as e:
        logger.error(f"[LLM_INIT_ERROR] {e}")
        return {
            "response": "I encountered an error initialising the AI model. Please try again.",
            "tool_calls": [], "tool_results": [], "messages": conversation_history or [],
            "context_id": context_id,
        }

    tools = make_tools(tool_handler)
    agent = create_react_agent(llm, tools, prompt=SYSTEM_PROMPT)

    # Build message history — keep last 3 turns (6 messages) for context
    messages = []
    history = conversation_history or []
    recent_history = history[-6:] if len(history) > 6 else history
    for msg in recent_history:
        role = msg.get("role")
        text = "".join(block.get("text", "") for block in msg.get("content", []))
        if not text:
            continue
        if role == "user":
            messages.append(HumanMessage(content=text))
        elif role == "assistant":
            messages.append(AIMessage(content=text))

    messages.append(HumanMessage(content=user_message))

    # Run agent with timeout
    try:
        result = await asyncio.wait_for(
            agent.ainvoke({"messages": messages}),
            timeout=AGENT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.error(f"[REACT_TIMEOUT] context_id={context_id} exceeded {AGENT_TIMEOUT}s")
        return {
            "response": "The request timed out. Please try again.",
            "tool_calls": [], "tool_results": [], "messages": conversation_history or [],
            "context_id": context_id,
        }
    except Exception as e:
        logger.error(f"[REACT_ERROR] context_id={context_id} error={e}", exc_info=True)
        return {
            "response": "I encountered an error processing your request. Please try again.",
            "tool_calls": [], "tool_results": [], "messages": conversation_history or [],
            "context_id": context_id,
        }

    # Extract final response and tool calls from agent messages
    agent_messages = result.get("messages", [])
    final_response = ""
    tool_calls = []
    tool_results = []

    for msg in agent_messages:
        if isinstance(msg, AIMessage):
            for tc in (msg.tool_calls or []):
                tool_calls.append({"name": tc["name"], "input": tc["args"]})
            content = msg.content
            if isinstance(content, list):
                text = " ".join(
                    b.get("text", "") if isinstance(b, dict) else str(b)
                    for b in content
                )
            else:
                text = content or ""
            if text.strip():
                final_response = text.strip()

        elif isinstance(msg, ToolMessage):
            try:
                result_data = json.loads(msg.content)
            except Exception:
                result_data = {"raw": msg.content}
            tool_name = getattr(msg, "name", None) or ""
            if not tool_name:
                for tc_msg in agent_messages:
                    if isinstance(tc_msg, AIMessage):
                        for tc in (tc_msg.tool_calls or []):
                            if tc.get("id") == msg.tool_call_id:
                                tool_name = tc["name"]
                                break
            tool_results.append({"name": tool_name, "result": result_data})
            logger.info(f"[TOOL_RESULT] name={tool_name} keys={list(result_data.keys()) if isinstance(result_data, dict) else 'raw'}")

    logger.info(f"[REACT_DONE] context_id={context_id} response_len={len(final_response)} tool_calls={len(tool_calls)}")

    # Update conversation history — always store original user message, not enriched
    updated_history = list(conversation_history or [])
    updated_history.append({"role": "user", "content": [{"text": user_message.split(" [Context:")[0]}]})
    updated_history.append({"role": "assistant", "content": [{"text": final_response}]})

    return {
        "response": final_response,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "messages": updated_history,
        "context_id": context_id,
    }
