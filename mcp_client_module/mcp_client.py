"""
MCP client — connects to the MCP server over SSE (HTTP).
Provides async methods for listing formats and previewing creatives.

Features:
- Logs all MCP tool calls with tool name, context_id, and status
- Retries on transient failures (up to MAX_RETRIES attempts)
- Gracefully handles non-completed statuses
"""

import json
import logging
import os
from typing import Any, Optional
from uuid import uuid4

from mcp import ClientSession
from mcp.client.sse import sse_client

# Configure module-level logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("mcp_client")

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000/sse")
MAX_RETRIES = 3
RETRY_DELAY = 1.0  # seconds between retries


async def _call_tool(tool_name: str, arguments: dict, context_id: str = None) -> Any:
    """
    Call a tool on the MCP server over SSE transport.

    Logs the call with tool_name, context_id, and final status.
    Retries up to MAX_RETRIES times on transient errors.
    Returns empty dict on non-recoverable failure.

    Args:
        tool_name: Name of the MCP tool to call
        arguments: Tool input arguments
        context_id: Optional trace ID for logging (auto-generated if not provided)
    """
    import asyncio

    context_id = context_id or str(uuid4())[:8]
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        logger.info(
            f"[CALL] tool={tool_name} context_id={context_id} attempt={attempt}/{MAX_RETRIES} args={list(arguments.keys())}"
        )
        try:
            async with sse_client(MCP_SERVER_URL) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)

                    # Check for non-completed status in result content
                    if not result.content:
                        logger.warning(
                            f"[EMPTY] tool={tool_name} context_id={context_id} — empty response"
                        )
                        return {}

                    parsed = json.loads(result.content[0].text)

                    # Check for error fields in the response
                    if isinstance(parsed, dict) and parsed.get("status") == "error":
                        errors = parsed.get("errors", [])
                        logger.warning(
                            f"[ERROR_STATUS] tool={tool_name} context_id={context_id} errors={errors}"
                        )
                        return parsed

                    logger.info(
                        f"[OK] tool={tool_name} context_id={context_id} keys={list(parsed.keys()) if isinstance(parsed, dict) else 'list'}"
                    )
                    return parsed

        except Exception as e:
            last_error = e
            logger.warning(
                f"[RETRY] tool={tool_name} context_id={context_id} attempt={attempt} error={type(e).__name__}: {e}"
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY * attempt)

    # All retries exhausted
    logger.error(
        f"[FAILED] tool={tool_name} context_id={context_id} after {MAX_RETRIES} attempts. Last error: {last_error}"
    )
    return {"error": str(last_error), "status": "failed"}


async def _read_resource(uri: str, context_id: str = None) -> Any:
    """
    Read an MCP resource by URI.

    Logs the resource read with uri, context_id, and status.
    Retries up to MAX_RETRIES times on transient errors.

    Args:
        uri: MCP resource URI e.g. formats://all
        context_id: Optional trace ID for logging
    """
    import asyncio

    context_id = context_id or str(uuid4())[:8]
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        logger.info(
            f"[READ_RESOURCE] uri={uri} context_id={context_id} attempt={attempt}/{MAX_RETRIES}"
        )
        try:
            async with sse_client(MCP_SERVER_URL) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.read_resource(uri)

                    if not result.contents:
                        logger.warning(
                            f"[EMPTY_RESOURCE] uri={uri} context_id={context_id}"
                        )
                        return {}

                    parsed = json.loads(result.contents[0].text)
                    logger.info(
                        f"[OK_RESOURCE] uri={uri} context_id={context_id} items={len(parsed) if isinstance(parsed, list) else 'dict'}"
                    )
                    return parsed

        except Exception as e:
            last_error = e
            logger.warning(
                f"[RETRY_RESOURCE] uri={uri} context_id={context_id} attempt={attempt} error={type(e).__name__}: {e}"
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY * attempt)

    logger.error(
        f"[FAILED_RESOURCE] uri={uri} context_id={context_id} after {MAX_RETRIES} attempts. Last error: {last_error}"
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
    pagination: Optional[dict] = None,
    context_id: Optional[str] = None,
) -> dict:
    """
    Call list_creative_formats tool on the MCP server.

    Builds the arguments dict from only the provided (non-None) parameters
    and delegates to _call_tool with retry and logging.

    Args:
        name_search: Partial name search keyword e.g. 'carousel'
        type: Format type filter — display, video, social, audio
        asset_types: List of asset types to filter by (OR logic)
        max_width: Maximum render width in pixels
        max_height: Maximum render height in pixels
        min_width: Minimum render width in pixels
        min_height: Minimum render height in pixels
        is_responsive: Filter for responsive formats
        pagination: Dict with max_results and optional cursor
        context_id: Optional trace ID for logging
    """
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
    Call preview_creative tool on the MCP server.

    Builds a single-mode preview request and delegates to _call_tool.

    Args:
        format_id: Dict with agent_url and id identifying the format
        assets: Dict of asset values e.g. {"hero_image": [...], "headline": "..."}
        output_format: "url" (default), "html", or "both"
        inputs: Optional list of input sets for device/locale variants
        context_id: Optional trace ID for logging
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
    Read formats://summary resource — lightweight name + id list.
    Use for quick lookup before calling list_creative_formats.
    """
    return await _read_resource("formats://summary", context_id)


async def get_all_formats(context_id: Optional[str] = None) -> list:
    """
    Read formats://all resource — full AdCP schema for all 48 formats.
    Use when you need complete format specs including assets and renders.
    """
    return await _read_resource("formats://all", context_id)
