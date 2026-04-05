# AdCP Creative Agent MCP Server

An MCP (Model Context Protocol) server that provides access to 48 Adzymic creative ad formats through the Ad Context Protocol (AdCP) specification.

## Features

- **48 Creative Formats**: Access to carousel, video, gallery, social, and interactive ad formats
- **Format Discovery**: Search and filter formats by name, type, dimensions, and asset requirements
- **Preview Generation**: Generate real Adzymic preview URLs for creative formats
- **AdCP Compliant**: Fully implements AdCP list_creative_formats and preview_creative tools
- **Multiple Transports**: Supports both stdio and SSE (HTTP) transports

## Installation

### Via pip (when published)
```bash
pip install adcp-creative-agent-mcp
```

### From source
```bash
git clone https://github.com/yourusername/creative-management-agent.git
cd creative-management-agent/creative_agent
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
# Server runs on http://localhost:8000/sse
```

### With Claude Desktop

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "adcp-creative": {
      "command": "python",
      "args": ["/path/to/creative_agent/mcp_server.py", "stdio"]
    }
  }
}
```

### With Other MCP Clients

```python
from mcp import ClientSession
from mcp.client.stdio import stdio_client

async with stdio_client("python", ["mcp_server.py", "stdio"]) as (read, write):
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
- `name_search` (string): Search by format name
- `type` (string): Filter by type (display, video, audio, dooh)
- `asset_types` (array): Filter by asset types (image, video, text, etc.)
- `max_width`, `max_height`, `min_width`, `min_height` (int): Filter by dimensions
- `is_responsive` (boolean): Filter responsive formats
- `pagination` (object): Pagination with max_results and cursor

**Returns:** Array of format objects with full specifications

### preview_creative
Generate preview renderings of creative formats.

**Parameters:**
- `request_type` (string): "single", "batch", or "variant"
- `creative_manifest` (object): Format ID and assets
- `output_format` (string): "url" or "html"
- `inputs` (array): Optional input variants

**Returns:** Preview URLs and metadata

## Resources

### formats://all
Full catalog of all 48 formats with complete specifications.

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
```bash
# Using MCP CLI
mcp call list_creative_formats '{"name_search": "carousel"}'
```

### Get format preview
```bash
mcp call preview_creative '{
  "request_type": "single",
  "creative_manifest": {
    "format_id": {
      "agent_url": "https://creative.adcontextprotocol.org",
      "id": "adzymic-carousel-standard-001"
    },
    "assets": {}
  }
}'
```

## API Reference

Full AdCP specification: https://adcontextprotocol.org

## License

MIT License

## Contributing

Contributions welcome! Please open an issue or PR.

## Support

- GitHub Issues: https://github.com/yourusername/creative-management-agent/issues
- Documentation: https://github.com/yourusername/creative-management-agent/wiki

## Credits

Built with:
- [MCP](https://modelcontextprotocol.io) - Model Context Protocol
- [FastMCP](https://github.com/jlowin/fastmcp) - Fast MCP server framework
- [Adzymic](https://adzymic.com) - Creative format provider
- [AdCP](https://adcontextprotocol.org) - Ad Context Protocol specification
