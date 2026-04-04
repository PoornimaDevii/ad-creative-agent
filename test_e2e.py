"""
End-to-end test: Bedrock (Claude Haiku 4.5) + MCP tools over SSE
Run MCP server first: conda run -n activeloop1 python mcp_server.py sse
Then run: conda run -n activeloop1 python test_e2e.py
"""

import asyncio
from dotenv import load_dotenv
from llm.bedrock_client import invoke_with_tools
from mcp_client_module.mcp_client import list_creative_formats, preview_creative

load_dotenv()


async def tool_handler(tool_name: str, tool_input: dict) -> dict:
    if tool_name == "list_creative_formats":
        return await list_creative_formats(**tool_input)
    elif tool_name == "preview_creative":
        return await preview_creative(
            format_id=tool_input["format_id"],
            assets=tool_input.get("assets", {}),
            output_format=tool_input.get("output_format", "url"),
            inputs=tool_input.get("inputs"),
        )
    return {"error": f"Unknown tool: {tool_name}"}


async def main():
    queries = [
        "Show me all carousel formats",
        "What video formats are available?",
        "Preview the carousel standard format",
    ]

    for query in queries:
        print(f"\n{'='*60}")
        print(f"Query: {query}")
        print("="*60)

        result = await invoke_with_tools(
            user_message=query,
            tool_handler=tool_handler,
        )

        print(f"Tools used: {[tc['name'] for tc in result['tool_calls']]}")
        print(f"Response:\n{result['response']}")
        
        # Print preview URLs if any
        for tr in result['tool_results']:
            if tr['name'] == 'preview_creative':
                previews = tr['result'].get('previews', [])
                for p in previews:
                    for r in p.get('renders', []):
                        if r.get('preview_url'):
                            print(f"Preview URL: {r['preview_url']}")


if __name__ == "__main__":
    asyncio.run(main())
