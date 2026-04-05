"""
MCP client — connects to the MCP server over SSE (HTTP).
Provides async methods for listing formats and previewing creatives.

Logging strategy:
  [CALL]           — every tool call attempt with tool name, context_id, args
  [OK]             — successful response
  [EMPTY]          — server returned no content (non-completed, skipped gracefully)
  [ERROR_STATUS]   — server returned status=error (logged, returned as-is)
  [RETRY]          — transient failure, will retry
  [FAILED]         — all retries exhausted

Non-completed status handling:
  - Empty response  → log [EMPTY], return {} (skip gracefully)
  - status=error    → log [ERROR_STATUS], return parsed dict (caller decides)
  - status=failed   → log [FAILED], return error dict after all retries
  - Exception       → log [RETRY], retry up to MAX_RETRIES with async backoff
"""

import asyncio
import json
import logging
import os
from typing import Any, Optional
from uuid import uuid4

from mcp import ClientSession
from mcp.client.sse import sse_client

# Module-level logger — writes to the same handler configured by react_agent.py
logger = logging.getLogger("mcp_client")

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000/sse")
MAX_RETRIES = 3
RETRY_DELAY = 1.0  # base seconds between retries (multiplied by attempt number)


async def _call_tool(tool_name: str, arguments: dict, context_id: str = None) -> Any:
    """
    Core MCP tool caller over Streamable HTTP transport.

    Logs every attempt with tool name, context_id, and outcome status.
    Handles non-completed statuses:
      - Empty content  → returns {} (skip gracefully, logged as [EMPTY])
      - status=error   → returns parsed error dict (logged as [ERROR_STATUS])
      - Exception      → retries up to MAX_RETRIES with exponential async backoff
      - All retries exhausted → returns {"error": ..., "status": "failed"}

    Args:
        tool_name:   Name of the MCP tool to invoke (e.g. "list_creative_formats")
        arguments:   Tool input arguments dict
        context_id:  Trace ID for correlating logs across calls (auto-generated if None)

    Returns:
        Parsed JSON response dict, or error dict on failure.
    """
    context_id = context_id or str(uuid4())[:8]
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        # Log every attempt with full context for traceability
        logger.info(
            f"[CALL] tool={tool_name} context_id={context_id} "
            f"attempt={attempt}/{MAX_RETRIES} args={list(arguments.keys())}"
        )
        try:
            async with sse_client(MCP_SERVER_URL) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)

                    # Non-completed: server returned no content — skip gracefully
                    if not result.content:
                        logger.warning(
                            f"[EMPTY] tool={tool_name} context_id={context_id} "
                            f"status=non-completed — empty response, skipping"
                        )
                        return {}

                    parsed = json.loads(result.content[0].text)

                    # Non-completed: server returned an error status — log and return
                    if isinstance(parsed, dict) and parsed.get("status") == "error":
                        logger.warning(
                            f"[ERROR_STATUS] tool={tool_name} context_id={context_id} "
                            f"status=error errors={parsed.get('errors', [])}"
                        )
                        # Return as-is so the caller can decide how to handle
                        return parsed

                    # Success
                    logger.info(
                        f"[OK] tool={tool_name} context_id={context_id} "
                        f"status=completed keys={list(parsed.keys()) if isinstance(parsed, dict) else 'list'}"
                    )
                    return parsed

        except Exception as e:
            last_error = e
            logger.warning(
                f"[RETRY] tool={tool_name} context_id={context_id} "
                f"attempt={attempt}/{MAX_RETRIES} status=transient-error "
                f"error={type(e).__name__}: {e}"
            )
            # Async exponential backoff — non-blocking
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY * attempt)

    # All retries exhausted — log final failure and return error dict
    logger.error(
        f"[FAILED] tool={tool_name} context_id={context_id} "
        f"status=failed after {MAX_RETRIES} attempts. last_error={last_error}"
    )
    return {"error": str(last_error), "status": "failed"}


async def _read_resource(uri: str, context_id: str = None) -> Any:
    """
    Read an MCP resource by URI over SSE transport.

    Logs every attempt with uri, context_id, and outcome status.
    Handles non-completed statuses the same way as _call_tool.

    Args:
        uri:         MCP resource URI e.g. "formats://all", "formats://summary"
        context_id:  Trace ID for correlating logs (auto-generated if None)

    Returns:
        Parsed JSON response, or {} on failure.
    """
    context_id = context_id or str(uuid4())[:8]
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        logger.info(
            f"[READ_RESOURCE] uri={uri} context_id={context_id} "
            f"attempt={attempt}/{MAX_RETRIES}"
        )
        try:
            async with sse_client(MCP_SERVER_URL) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.read_resource(uri)

                    # Non-completed: empty resource response — skip gracefully
                    if not result.contents:
                        logger.warning(
                            f"[EMPTY_RESOURCE] uri={uri} context_id={context_id} "
                            f"status=non-completed — empty contents, skipping"
                        )
                        return {}

                    parsed = json.loads(result.contents[0].text)
                    logger.info(
                        f"[OK_RESOURCE] uri={uri} context_id={context_id} status=completed"
                    )
                    return parsed

        except Exception as e:
            last_error = e
            logger.warning(
                f"[RETRY_RESOURCE] uri={uri} context_id={context_id} "
                f"attempt={attempt}/{MAX_RETRIES} status=transient-error "
                f"error={type(e).__name__}: {e}"
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY * attempt)

    logger.error(
        f"[FAILED_RESOURCE] uri={uri} context_id={context_id} "
        f"status=failed after {MAX_RETRIES} attempts. last_error={last_error}"
    )
    return {}


async def list_creative_formats(
    name_search: Optional[str] = None,
    type: Optional[str] = None,
    asset_types: Optional[list] = None,
    max_width: Optional[int] = None,
    max_height: Optional[int] = None,
    min_width: Optional[int] = None,
    min_height: Optional[int] = None,
    is_responsive: Optional[bool] = None,
    dco_available: Optional[bool] = None,
    pagination: Optional[dict] = None,
    context_id: Optional[str] = None,
) -> dict:
    """
    Call the list_creative_formats tool on the MCP server.

    Builds the arguments dict from only the provided (non-None) parameters
    to avoid sending unnecessary fields, then delegates to _call_tool
    which handles logging, retries, and non-completed status handling.

    Args:
        name_search:   Partial name keyword e.g. 'carousel', 'shake'
        type:          Format type: display, video, audio, dooh
        asset_types:   Asset type filter list (OR logic)
        max_width:     Maximum render width in pixels
        max_height:    Maximum render height in pixels
        min_width:     Minimum render width in pixels
        min_height:    Minimum render height in pixels
        is_responsive: Filter for responsive formats only
        dco_available: Filter for DCO-enabled formats only
        pagination:    Dict with max_results (1-100) and optional cursor
        context_id:    Trace ID for log correlation

    Returns:
        Dict with "formats" list and optional "next_cursor".
    """
    # Only include non-None args to keep the request minimal
    args = {}
    if name_search:
        args["name_search"] = name_search
    if type:
        args["type"] = type
    if asset_types:
        args["asset_types"] = asset_types
    if max_width is not None:
        args["max_width"] = max_width
    if max_height is not None:
        args["max_height"] = max_height
    if min_width is not None:
        args["min_width"] = min_width
    if min_height is not None:
        args["min_height"] = min_height
    if is_responsive is not None:
        args["is_responsive"] = is_responsive
    if dco_available is not None:
        args["dco_available"] = dco_available
    if pagination:
        args["pagination"] = pagination

    return await _call_tool("list_creative_formats", args, context_id)


async def preview_creative(
    format_id: dict,
    assets: dict,
    output_format: str = "url",
    inputs: Optional[list] = None,
    context_id: Optional[str] = None,
) -> dict:
    """
    Call the preview_creative tool on the MCP server in single mode.

    Wraps the format_id and assets into a creative_manifest and delegates
    to _call_tool which handles logging, retries, and non-completed statuses.

    Args:
        format_id:     Dict with agent_url and id identifying the format
        assets:        Asset values e.g. {"hero_image": "...", "headline": "..."}
        output_format: "url" (default, iframe-embeddable) or "html"
        inputs:        Optional list of input sets for multi-variant previews
        context_id:    Trace ID for log correlation

    Returns:
        Dict with "previews" list containing render URLs.
    """
    return await _call_tool("preview_creative", {
        "request_type": "single",
        "creative_manifest": {
            "format_id": format_id,
            "assets": assets,
        },
        "output_format": output_format,
        "inputs": inputs,
    }, context_id)


async def get_formats_summary(context_id: Optional[str] = None) -> list:
    """
    Read the formats://summary resource — lightweight name + id list.
    Use for quick lookup before calling list_creative_formats.
    """
    return await _read_resource("formats://summary", context_id)


async def get_all_formats(context_id: Optional[str] = None) -> list:
    """
    Read the formats://all resource — full AdCP schema for all 48 formats.
    Use when complete format specs including assets and renders are needed.
    """
    return await _read_resource("formats://all", context_id)
