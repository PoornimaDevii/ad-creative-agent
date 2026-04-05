# AdCP Creative Agent MCP Server

An MCP (Model Context Protocol) server that provides access to 48 Adzymic creative ad formats through the Ad Context Protocol (AdCP) specification.

## Features

- **48 Creative Formats**: Access to carousel, video, gallery, social, and interactive ad formats
- **Format Discovery**: Search and filter formats by name, type, dimensions, and asset requirements
- **Preview Generation**: Generate real Adzymic preview URLs for creative formats
- **AdCP Compliant**: Fully implements AdCP `list_creative_formats` and `preview_creative` tools
- **Multiple Transports**: Supports both stdio and SSE (HTTP) transports

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### As MCP Server (stdio)
```bash
python mcp_server.py stdio
```

### As HTTP Server (SSE)
```bash
python mcp_server.py sse
# Server runs on http://localhost:8000/sse by default
# Override port via PORT env var: PORT=9000 python mcp_server.py sse
```

### With Claude Desktop

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "adcp-creative": {
      "command": "python",
      "args": ["/path/to/mcp_server.py", "stdio"]
    }
  }
}
```

### With Other MCP Clients

```python
from mcp import ClientSession
from mcp.client.sse import sse_client

async with sse_client("http://localhost:8000/sse") as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()

        # List formats
        result = await session.call_tool("list_creative_formats", {
            "name_search": "carousel"
        })

        # Preview format
        preview = await session.call_tool("preview_creative", {
            "request_type": "single",
            "creative_manifest": {
                "format_id": {
                    "agent_url": "https://creative.adcontextprotocol.org",
                    "id": "adzymic-carousel-standard-001"
                },
                "assets": {}
            }
        })
```

## Available Tools

### list_creative_formats
Discover and filter creative formats.

**Parameters:**
- `name_search` (string): Search by a single keyword from the format name e.g. `carousel`, `shake`, `facebook`
- `type` (string): Filter by type — only use when the user explicitly says one of: `display`, `video`, `audio`, `dooh`
- `asset_types` (array): Filter by asset types (`image`, `video`, `audio`, `text`, `html`, `javascript`, `url`)
- `max_width`, `max_height`, `min_width`, `min_height` (int): Filter by render dimensions in pixels
- `is_responsive` (boolean): Filter responsive formats only
- `dco_available` (boolean): Filter formats that support Dynamic Creative Optimization
- `pagination` (object): `{ "max_results": 1–100, "cursor": "..." }`

**Returns:** Object with `formats` array (full AdCP specs) and optional `next_cursor`

### preview_creative
Generate preview renderings of creative formats.

**Parameters:**
- `request_type` (string): `"single"`, `"batch"`, or `"variant"`
- `creative_manifest` (object): Contains `format_id` (`agent_url` + `id`) and `assets` dict
- `output_format` (string): `"url"` (default) or `"html"`
- `inputs` (array): Optional list of input variants for multi-variant previews

**Returns:** Object with `previews` array containing render URLs and metadata

## Resources

### formats://all
Full catalog of all 48 formats with complete AdCP specifications.

### formats://summary
Lightweight list of format names and IDs for quick lookup.

## Format Categories

- **Carousel Formats**: Standard, Rotation, Overlay, Flip, Skinny
- **Video Formats**: Vertical Video, In-Banner Video, Horizontal Video, Video Hotspot
- **Gallery Formats**: Gallery, Tiles, Full Image Gallery, Gallery Slideshow
- **Interactive Formats**: 3D Cube, 3D Parallax, Shake & Reveal, Scratch & Show, Tap to Win
- **Social Formats**: Facebook, Instagram, LinkedIn, TikTok
- **Product Formats**: Product Carousel, Product Color, Mix and Match, 360 View
- **Engagement Formats**: Lead Gen, ChatBot, Countdown, App Download

## Examples

### Search for carousel formats
```python
result = await session.call_tool("list_creative_formats", {
    "name_search": "carousel"
})
```

### Get format preview
```python
preview = await session.call_tool("preview_creative", {
    "request_type": "single",
    "creative_manifest": {
        "format_id": {
            "agent_url": "https://creative.adcontextprotocol.org",
            "id": "adzymic-carousel-standard-001"
        },
        "assets": {}
    }
})
```

## API Reference

Full AdCP specification: https://adcontextprotocol.org

## Credits

Built with:
- [MCP](https://modelcontextprotocol.io) — Model Context Protocol
- [FastMCP](https://github.com/jlowin/fastmcp) — Fast MCP server framework
- [Adzymic](https://adzymic.com) — Creative format provider
- [AdCP](https://adcontextprotocol.org) — Ad Context Protocol specification
