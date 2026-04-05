import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional
from uuid import uuid4

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

mcp = FastMCP(name="adcp-creative-agent")


# ====================== Data Models ======================

class FormatID(BaseModel):
    agent_url: str
    id: str


class Dimensions(BaseModel):
    width: int
    height: int


class Render(BaseModel):
    role: Optional[str] = None
    dimensions: Optional[Dimensions] = None


class AssetRequirements(BaseModel):
    min: Optional[int] = None
    max: Optional[int] = None
    aspect_ratio: Optional[str] = None
    max_duration: Optional[int] = None
    max_length: Optional[int] = None
    catalog_type: Optional[str] = None
    min_items: Optional[int] = None
    max_items: Optional[int] = None
    required_fields: Optional[List[str]] = None
    feed_formats: Optional[List[str]] = None


class Asset(BaseModel):
    asset_id: str
    asset_type: str
    asset_role: Optional[str] = None
    item_type: Optional[str] = None
    required: bool = True
    requirements: Optional[AssetRequirements] = None


class CreativeAgent(BaseModel):
    agent_url: str
    agent_name: Optional[str] = None
    capabilities: Optional[List[str]] = None


class CreativeFormat(BaseModel):
    format_id: FormatID
    name: str
    type: Optional[str] = None
    is_responsive: Optional[bool] = None
    wcag_level: Optional[str] = None
    assets: List[Asset] = Field(default_factory=list)
    renders: Optional[List[Render]] = None
    input_format_ids: Optional[List[FormatID]] = None
    output_format_ids: Optional[List[FormatID]] = None
    disclosure_capabilities: Optional[List[Dict[str, Any]]] = None
    supported_disclosure_positions: Optional[List[str]] = None
    preview_urls: Optional[List[str]] = None
    dco_available: Optional[bool] = None
    specs: Optional[Dict[str, Any]] = None


class ListCreativeFormatsResponse(BaseModel):
    """AdCP list_creative_formats response.
    - formats: Array of full format definitions (format_id, name, assets, renders). type field is deprecated.
    - creative_agents: Optional array of other creative agents providing additional formats.
    """
    formats: List[CreativeFormat]
    creative_agents: Optional[List[CreativeAgent]] = None
    next_cursor: Optional[str] = None  # pagination cursor for next page

    def model_dump(self, **kwargs):
        """Serialize response, omitting deprecated type field from formats per AdCP spec."""
        data = super().model_dump(**kwargs)
        for fmt in data.get("formats", []):
            fmt.pop("type", None)  # type is deprecated — omit from response
        return data


# --- Preview models ---

class PreviewRender(BaseModel):
    render_id: str
    output_format: str  # "url" | "html" | "both"
    preview_url: Optional[str] = None
    preview_html: Optional[str] = None
    role: str = "primary"
    dimensions: Optional[Dimensions] = None


class PreviewInput(BaseModel):
    name: str
    macros: Optional[Dict[str, str]] = None
    context_description: Optional[str] = None


class Preview(BaseModel):
    preview_id: str
    renders: List[PreviewRender]
    input: PreviewInput


class BatchError(BaseModel):
    code: str
    message: str


class BatchResult(BaseModel):
    success: bool
    creative_id: str
    response: Optional[Dict[str, Any]] = None
    errors: Optional[List[BatchError]] = None


class PreviewCreativeResponse(BaseModel):
    """AdCP preview_creative response — oneOf: single, batch, variant."""
    response_type: str                              # "single" | "batch" | "variant"
    # single + variant
    previews: Optional[List[Preview]] = None
    expires_at: Optional[str] = None               # required for single + variant (ISO 8601)
    interactive_url: Optional[str] = None          # optional sandbox URL
    # variant only
    variant_id: Optional[str] = None
    creative_id: Optional[str] = None
    manifest: Optional[Dict[str, Any]] = None      # rendered manifest that was served
    # batch only
    results: Optional[List[BatchResult]] = None
    # pass-through
    context: Optional[Dict[str, Any]] = None
    ext: Optional[Dict[str, Any]] = None


# ====================== Load Formats ======================

def load_formats() -> List[CreativeFormat]:
    file_path = Path(__file__).parent / "registry" / "creative_formats.json"
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [CreativeFormat(**fmt) for fmt in data.get("formats", [])]
    except Exception as e:
        print(f"Error loading formats: {e}")
        return []


FORMATS = load_formats()
WCAG_ORDER = {"A": 1, "AA": 2, "AAA": 3}


# ====================== RESOURCES ======================

@mcp.resource("formats://all")
def resource_all_formats() -> str:
    """Full AdCP-schema catalog of all creative formats as JSON."""
    return json.dumps(
        [f.model_dump(exclude_none=True) for f in FORMATS],
        indent=2
    )


@mcp.resource("formats://summary")
def resource_formats_summary() -> str:
    """Lightweight list of format names and IDs — use for quick lookup before calling list_creative_formats."""
    summary = [
        {
            "id": f.format_id.id,
            "agent_url": f.format_id.agent_url,
            "name": f.name,
            "type": f.type,
        }
        for f in FORMATS
    ]
    return json.dumps(summary, indent=2)


# ====================== Filter Helpers ======================

def _filter_by_format_ids(formats: List[CreativeFormat], format_ids: List[Dict[str, str]]) -> List[CreativeFormat]:
    requested = {(f["agent_url"], f["id"]) for f in format_ids}
    return [f for f in formats if (f.format_id.agent_url, f.format_id.id) in requested]


def _filter_by_asset_types(formats: List[CreativeFormat], asset_types: List[str]) -> List[CreativeFormat]:
    return [f for f in formats if any(a.asset_type in asset_types for a in f.assets)]


def _filter_by_dimensions(
    formats: List[CreativeFormat],
    max_width: Optional[int], max_height: Optional[int],
    min_width: Optional[int], min_height: Optional[int],
) -> List[CreativeFormat]:
    def render_dims(f: CreativeFormat):
        return [r.dimensions for r in (f.renders or []) if r.dimensions]

    if max_width is not None:
        formats = [f for f in formats if any(d.width <= max_width for d in render_dims(f))]
    if max_height is not None:
        formats = [f for f in formats if any(d.height <= max_height for d in render_dims(f))]
    if min_width is not None:
        formats = [f for f in formats if any(d.width >= min_width for d in render_dims(f))]
    if min_height is not None:
        formats = [f for f in formats if any(d.height >= min_height for d in render_dims(f))]
    return formats


def _filter_by_wcag(formats: List[CreativeFormat], wcag_level: str) -> List[CreativeFormat]:
    min_level = WCAG_ORDER.get(wcag_level, 0)
    return [f for f in formats if WCAG_ORDER.get(f.wcag_level or "", 0) >= min_level]


def _filter_by_disclosure_positions(formats: List[CreativeFormat], positions: List[str]) -> List[CreativeFormat]:
    def supports(fmt: CreativeFormat) -> bool:
        if fmt.disclosure_capabilities:
            supported = {c.get("position") for c in fmt.disclosure_capabilities}
        elif fmt.supported_disclosure_positions:
            supported = set(fmt.supported_disclosure_positions)
        else:
            return False
        return all(p in supported for p in positions)
    return [f for f in formats if supports(f)]


def _filter_by_disclosure_persistence(formats: List[CreativeFormat], persistence: List[str]) -> List[CreativeFormat]:
    def supports(fmt: CreativeFormat) -> bool:
        for cap in (fmt.disclosure_capabilities or []):
            if all(m in set(cap.get("persistence", [])) for m in persistence):
                return True
        return False
    return [f for f in formats if supports(f)]


def _filter_by_output_format_ids(formats: List[CreativeFormat], ids: List[Dict[str, str]]) -> List[CreativeFormat]:
    requested = {(f["agent_url"], f["id"]) for f in ids}
    return [
        f for f in formats
        if f.output_format_ids and any((o.agent_url, o.id) in requested for o in f.output_format_ids)
    ]


def _filter_by_input_format_ids(formats: List[CreativeFormat], ids: List[Dict[str, str]]) -> List[CreativeFormat]:
    requested = {(f["agent_url"], f["id"]) for f in ids}
    return [
        f for f in formats
        if f.input_format_ids and any((i.agent_url, i.id) in requested for i in f.input_format_ids)
    ]


# ====================== Preview Helpers ======================

def _expires_at(hours: int = 24) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_render(output_format: str, format_id_str: str, suffix: str, dimensions: Optional[Dimensions] = None) -> PreviewRender:
    render_id = f"render_{suffix}"
    preview_url = None
    preview_html = None
    if output_format in ("url", "both"):
        preview_url = f"https://preview.adcontextprotocol.org/{format_id_str}/{str(uuid4())[:12]}"
    if output_format in ("html", "both"):
        preview_html = f'<div class="adcp-creative" data-format="{format_id_str}"><p>Preview: {format_id_str}</p></div>'
    return PreviewRender(
        render_id=render_id,
        output_format=output_format,
        preview_url=preview_url,
        preview_html=preview_html,
        role="primary",
        dimensions=dimensions,
    )


def _validate_assets(fmt: CreativeFormat, assets: Dict[str, Any]) -> List[str]:
    errors = []
    for spec in fmt.assets:
        if not spec.required:
            continue
        provided = assets.get(spec.asset_id) or assets.get(spec.asset_role or "")
        if not provided:
            errors.append(f"Missing required asset: '{spec.asset_id}' ({spec.asset_type})")
            continue
        if spec.requirements and spec.asset_type in ("image", "video"):
            items = provided if isinstance(provided, list) else [provided]
            if spec.requirements.min and len(items) < spec.requirements.min:
                errors.append(f"Asset '{spec.asset_id}' needs at least {spec.requirements.min} items, got {len(items)}")
    return errors


def _build_single_preview(
    fmt: CreativeFormat,
    output_format: str,
    inputs: Optional[List[Dict[str, Any]]],
) -> List[Preview]:
    format_id_str = fmt.format_id.id
    real_urls = fmt.preview_urls or []
    input_sets = inputs or [{"name": "Default", "macros": {}}]
    previews = []
    for idx, inp in enumerate(input_sets):
        renders = []
        for r_idx, render_spec in enumerate(fmt.renders or [{"role": "primary"}]):
            dims = None
            if hasattr(render_spec, "dimensions"):
                dims = render_spec.dimensions
            elif isinstance(render_spec, dict):
                d = render_spec.get("dimensions")
                dims = Dimensions(**d) if d else None
            # Use real URL if available for this render index, else reuse first URL
            if real_urls:
                real_url = real_urls[r_idx] if r_idx < len(real_urls) else real_urls[0]
            else:
                real_url = None
            render_id = f"render_{idx + 1}_{r_idx + 1}"
            renders.append(PreviewRender(
                render_id=render_id,
                output_format=output_format,
                preview_url=real_url if output_format == "url" else None,
                preview_html=(
                    f'<iframe src="{real_url}" width="600" height="400"></iframe>'
                    if real_url and output_format == "html"
                    else None
                ),
                role="primary" if r_idx == 0 else "companion",
                dimensions=dims,
            ))
        previews.append(Preview(
            preview_id=f"prev_{str(uuid4())[:8]}",
            renders=renders,
            input=PreviewInput(
                name=inp.get("name", "Default"),
                macros=inp.get("macros"),
                context_description=inp.get("context_description"),
            ),
        ))
    return previews


def _process_single_request(
    req: Dict[str, Any],
    default_output_format: str,
    default_quality: Optional[str],
) -> Dict[str, Any]:
    """Process one item from a batch requests array. Returns a dict matching BatchResult fields."""
    manifest = req.get("creative_manifest", {})
    fid = req.get("format_id") or manifest.get("format_id", {})
    creative_id = req.get("creative_id") or fid.get("id", str(uuid4())[:8])
    output_format = req.get("output_format", default_output_format)

    fmt = next(
        (f for f in FORMATS if f.format_id.agent_url == fid.get("agent_url") and f.format_id.id == fid.get("id")),
        None,
    )
    if not fmt:
        return {
            "success": False,
            "creative_id": creative_id,
            "errors": [{"code": "FORMAT_NOT_FOUND", "message": f"Format '{fid.get('id')}' not found"}],
        }

    asset_errors = _validate_assets(fmt, manifest.get("assets", {}))
    if asset_errors:
        return {
            "success": False,
            "creative_id": creative_id,
            "errors": [{"code": "VALIDATION_FAILED", "message": e} for e in asset_errors],
        }

    previews = _build_single_preview(fmt, output_format, req.get("inputs"))
    return {
        "success": True,
        "creative_id": creative_id,
        "response": {
            "previews": [p.model_dump(exclude_none=True) for p in previews],
            "expires_at": _expires_at(),
        },
    }


# ====================== TOOLS ======================

@mcp.tool()
async def list_creative_formats(
    format_ids: Optional[List[Dict[str, str]]] = None,
    type: Optional[str] = None,           # enum: audio, video, display, dooh
    asset_types: Optional[List[str]] = None,  # enum: image, video, audio, text, html, javascript, url
    max_width: Optional[int] = None,
    max_height: Optional[int] = None,
    min_width: Optional[int] = None,
    min_height: Optional[int] = None,
    is_responsive: Optional[bool] = None,
    name_search: Optional[str] = None,
    dco_available: Optional[bool] = None,
    wcag_level: Optional[str] = None,      # enum: A, AA, AAA
    disclosure_positions: Optional[List[str]] = None,
    disclosure_persistence: Optional[List[str]] = None,
    output_format_ids: Optional[List[Dict[str, str]]] = None,
    input_format_ids: Optional[List[Dict[str, str]]] = None,
    pagination: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,  # pass-through per AdCP schema
    ext: Optional[Dict[str, Any]] = None,       # pass-through per AdCP schema
) -> ListCreativeFormatsResponse:
    """Discover creative formats supported by this agent.

    Parameters (all optional):
    - format_ids: Return only specific format IDs (from get_products response)
    - type: (deprecated) Filter by type: audio, video, display, dooh. Prefer asset_types instead.
    - asset_types: Filter to formats accepting these asset types: image, video, audio, text, html, javascript, url. Uses OR logic. Recommended over type.
    - max_width: Maximum width in pixels (inclusive) - matches if ANY render fits
    - max_height: Maximum height in pixels (inclusive) - matches if ANY render fits
    - min_width: Minimum width in pixels (inclusive)
    - min_height: Minimum height in pixels (inclusive)
    - is_responsive: Filter for responsive formats that adapt to container size
    - name_search: Search formats by name (case-insensitive partial match)
    - wcag_level: Filter to formats meeting at least this WCAG level: A, AA, AAA
    - disclosure_positions: Filter to formats that support all of these disclosure positions
    - disclosure_persistence: Filter by persistence modes: continuous, initial, flexible
    - output_format_ids: Filter to formats whose output_format_ids includes any of these
    - input_format_ids: Filter to formats whose input_format_ids includes any of these
    - pagination: max_results (1-100, default 50) and cursor
    - context: pass-through context per AdCP schema
    - ext: pass-through extensions per AdCP schema
    """

    # Validate type enum per AdCP schema
    VALID_TYPES = {"audio", "video", "display", "dooh"}
    if type and type not in VALID_TYPES:
        type = None  # ignore invalid type silently

    # Validate asset_types enum per AdCP schema
    VALID_ASSET_TYPES = {"image", "video", "audio", "text", "html", "javascript", "url"}
    if asset_types:
        asset_types = [a for a in asset_types if a in VALID_ASSET_TYPES]
        if not asset_types:
            asset_types = None

    formats = FORMATS[:]

    if format_ids:
        formats = _filter_by_format_ids(formats, format_ids)
    if type:
        formats = [f for f in formats if f.type == type]
    if asset_types:
        formats = _filter_by_asset_types(formats, asset_types)
    if any(v is not None for v in (max_width, max_height, min_width, min_height)):
        formats = _filter_by_dimensions(formats, max_width, max_height, min_width, min_height)
    if is_responsive is not None:
        formats = [f for f in formats if f.is_responsive == is_responsive]
    if dco_available is not None:
        formats = [f for f in formats if f.dco_available == dco_available]
    if name_search:
        import html
        needle = name_search.lower().strip()
        # Normalize & variations
        needle_normalized = needle.replace(" and ", " & ").replace("and", "&")
        needle_and = needle.replace("&", "and")
        # Stem the needle — strip common suffixes for fuzzy matching
        stem = needle
        for suffix in ("ler", "led", "ing", "er", "ed", "s"):
            if needle.endswith(suffix) and len(needle) - len(suffix) >= 3:
                stem = needle[: -len(suffix)]
                break

        def name_matches(f: CreativeFormat) -> bool:
            name = html.unescape(f.name).lower()
            name_and = name.replace("&", "and")
            # Direct match
            if needle in name or needle_normalized in name or needle_and in name_and:
                return True
            # Stem match (single keyword only)
            if stem != needle and len(needle.split()) == 1 and stem in name:
                return True
            # Multi-word: ALL words must appear (only when >1 word in query)
            words = [w for w in needle.split() if len(w) >= 3]
            if len(words) > 1 and all(w in name for w in words):
                return True
            return False

        formats = [f for f in formats if name_matches(f)]
    if wcag_level:
        formats = _filter_by_wcag(formats, wcag_level)
    if disclosure_positions:
        formats = _filter_by_disclosure_positions(formats, disclosure_positions)
    if disclosure_persistence:
        formats = _filter_by_disclosure_persistence(formats, disclosure_persistence)
    if output_format_ids:
        formats = _filter_by_output_format_ids(formats, output_format_ids)
    if input_format_ids:
        formats = _filter_by_input_format_ids(formats, input_format_ids)

    max_results = 50
    cursor_index = 0
    if pagination:
        max_results = max(1, min(100, pagination.get("max_results", 50)))
        try:
            cursor_index = int(pagination.get("cursor") or 0)
        except ValueError:
            cursor_index = 0

    page = formats[cursor_index: cursor_index + max_results]
    next_cursor = str(cursor_index + max_results) if cursor_index + max_results < len(formats) else None

    return ListCreativeFormatsResponse(formats=page, next_cursor=next_cursor)


@mcp.tool()
async def preview_creative(
    request_type: str,                              # required: "single" | "batch" | "variant"
    # single mode
    creative_manifest: Optional[Dict[str, Any]] = None,  # required for single
    format_id: Optional[Dict[str, str]] = None,     # optional — defaults to creative_manifest.format_id
    inputs: Optional[List[Dict[str, Any]]] = None,  # array of {name, macros, context_description}
    template_id: Optional[str] = None,
    quality: Optional[str] = None,                  # enum: draft | production
    output_format: str = "url",                     # enum: url | html
    item_limit: Optional[int] = None,               # minimum: 1
    # variant mode
    variant_id: Optional[str] = None,               # required for variant
    creative_id: Optional[str] = None,
    # batch mode
    requests: Optional[List[Dict[str, Any]]] = None,  # required for batch, 1-50 items
    # pass-through per AdCP schema
    context: Optional[Dict[str, Any]] = None,
    ext: Optional[Dict[str, Any]] = None,
) -> PreviewCreativeResponse:
    """Generate preview renderings of creative manifests.

    Three modes via request_type:

    single (required: creative_manifest):
      - format_id: optional, defaults to creative_manifest.format_id
      - inputs: array of {name (required), macros, context_description} for multiple variants
      - quality: 'draft' (fast, lower-fidelity) or 'production' (full quality)
      - output_format: 'url' (default, iframe-embeddable) or 'html' (raw HTML)
      - item_limit: max catalog items to render (minimum 1)
      - template_id: specific template for custom rendering

    batch (required: requests array, 1-50 items):
      - Each item follows single request structure with creative_manifest required
      - quality and output_format at batch level are defaults, overridable per item

    variant (required: variant_id):
      - variant_id: from get_creative_delivery response
      - creative_id: optional context
      - output_format: 'url' or 'html'
    """

    # Validate quality enum
    VALID_QUALITY = {"draft", "production"}
    if quality and quality not in VALID_QUALITY:
        quality = None

    # Validate output_format enum — spec only allows url or html
    VALID_OUTPUT = {"url", "html"}
    if output_format not in VALID_OUTPUT:
        output_format = "url"

    # Validate item_limit minimum
    if item_limit is not None and item_limit < 1:
        item_limit = 1

    if request_type == "single":
        if not creative_manifest:
            # creative_manifest is required per spec — return error preview
            return PreviewCreativeResponse(
                response_type="single",
                previews=[Preview(
                    preview_id=f"prev_{str(uuid4())[:8]}",
                    renders=[PreviewRender(
                        render_id="render_1",
                        output_format=output_format,
                        preview_url=None,
                        preview_html=None,
                        role="primary",
                    )],
                    input=PreviewInput(name="Default"),
                )],
                expires_at=_expires_at(),
            )

        fid = format_id or creative_manifest.get("format_id", {})
        fmt = next(
            (f for f in FORMATS if f.format_id.agent_url == fid.get("agent_url") and f.format_id.id == fid.get("id")),
            None,
        )
        if not fmt:
            return PreviewCreativeResponse(
                response_type="single",
                previews=[Preview(
                    preview_id=f"prev_{str(uuid4())[:8]}",
                    renders=[PreviewRender(
                        render_id="render_1",
                        output_format=output_format,
                        preview_url=None,
                        preview_html=None,
                        role="primary",
                    )],
                    input=PreviewInput(name="Default"),
                )],
                expires_at=_expires_at(),
            )

        asset_errors = _validate_assets(fmt, creative_manifest.get("assets", {}))
        if asset_errors and creative_manifest.get("assets"):
            # Only fail validation if assets were actually provided but are wrong
            # If no assets provided, skip validation and return preview URLs directly
            return PreviewCreativeResponse(
                response_type="single",
                previews=[Preview(
                    preview_id=f"prev_{str(uuid4())[:8]}",
                    renders=[PreviewRender(
                        render_id="render_1",
                        output_format=output_format,
                        preview_url=None,
                        preview_html=None,
                        role="primary",
                    )],
                    input=PreviewInput(name="Default"),
                )],
                expires_at=_expires_at(),
            )

        previews = _build_single_preview(fmt, output_format, inputs)
        return PreviewCreativeResponse(
            response_type="single",
            previews=previews,
            expires_at=_expires_at(),
        )

    if request_type == "batch":
        if not requests:
            return PreviewCreativeResponse(response_type="batch", results=[])

        batch_requests = requests[:50]  # cap at 50 per spec
        results = []
        for req in batch_requests:
            r = _process_single_request(req, output_format, quality)
            # Ensure success=true has response, success=false has errors per AdCP spec
            if r["success"]:
                results.append(BatchResult(
                    success=True,
                    creative_id=r["creative_id"],
                    response=r.get("response"),
                ))
            else:
                results.append(BatchResult(
                    success=False,
                    creative_id=r["creative_id"],
                    errors=[BatchError(**e) for e in r.get("errors", [])],
                ))
        return PreviewCreativeResponse(
            response_type="batch",
            results=results,
        )

    if request_type == "variant":
        if not variant_id:
            return PreviewCreativeResponse(
                response_type="variant",
                variant_id="unknown",
                previews=[Preview(
                    preview_id=f"prev_{str(uuid4())[:8]}",
                    renders=[PreviewRender(
                        render_id="render_1",
                        output_format=output_format,
                        preview_url=None,
                        role="primary",
                    )],
                    input=PreviewInput(name="Variant Replay"),
                )],
                expires_at=_expires_at(),
            )

        preview_url = f"https://preview.adcontextprotocol.org/variant/{variant_id}"
        render = PreviewRender(
            render_id="render_1",
            output_format=output_format,
            preview_url=preview_url if output_format == "url" else None,
            preview_html=(
                f'<div class="adcp-creative" data-variant="{variant_id}"><p>Variant: {variant_id}</p></div>'
                if output_format == "html" else None
            ),
            role="primary",
        )
        return PreviewCreativeResponse(
            response_type="variant",
            variant_id=variant_id,          # required in response per spec
            creative_id=creative_id,
            previews=[Preview(
                preview_id=f"prev_{str(uuid4())[:8]}",
                renders=[render],
                input=PreviewInput(name="Variant Replay"),
            )],
            expires_at=_expires_at(),
        )

    # Unknown request_type
    return PreviewCreativeResponse(response_type=request_type, previews=[], expires_at=_expires_at())


# ====================== Run Server ======================
if __name__ == "__main__":
    import sys
    import os
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    port = int(os.getenv("PORT", 8001))
    print(f"Starting AdCP Creative Agent MCP Server — {len(FORMATS)} formats loaded")
    print(f"Transport: {transport}, Port: {port}")
    if transport == "sse":
        mcp.run(transport="sse", host="0.0.0.0", port=port)
    else:
        mcp.run(transport="stdio")
