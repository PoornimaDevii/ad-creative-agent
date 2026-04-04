# AdCP Creative Agent Platform

An agentic platform built on the [Ad Context Protocol (AdCP)](https://docs.adcontextprotocol.org) that lets users discover and preview Adzymic creative ad formats using natural language.

## Architecture

```
Streamlit UI (Streamlit Cloud)
    ↓ natural language
AWS Bedrock — Claude 3.5 Haiku
    ↓ tool calls
MCP Client (SSE)
    ↓
MCP Server (Railway) ← creative_formats.json (48 Adzymic formats)
```

## Features

- 🔍 **Natural language search** — ask for formats by type, size, asset type
- 📋 **48 Adzymic formats** — full AdCP-schema specs parsed from Freshdesk
- 👁 **Live previews** — real Adzymic preview URLs embedded in iframe
- 🔧 **MCP tools** — `list_creative_formats` + `preview_creative`
- 📦 **MCP resources** — `formats://all` + `formats://summary`

## MCP Server

The MCP server runs over SSE transport and exposes:

### Tools
- `list_creative_formats` — filter by name, type, asset types, dimensions, WCAG level
- `preview_creative` — single, batch, and variant preview modes

### Resources
- `formats://all` — full AdCP schema for all 48 formats
- `formats://summary` — lightweight name + id list

## Local Development

1. Clone the repo
2. Install dependencies:
```bash
pip install -r requirements.txt
```
3. Copy `.env.example` to `.env` and fill in your AWS credentials
4. Start MCP server:
```bash
python mcp_server.py sse
```
5. Run Streamlit app:
```bash
streamlit run app.py
```

## Deployment

- **MCP Server** → Railway (auto-deploys from GitHub)
- **Streamlit App** → Streamlit Community Cloud (auto-deploys from GitHub)

## Environment Variables

| Variable | Description |
|---|---|
| `AWS_REGION` | AWS region e.g. `us-east-1` |
| `AWS_ACCESS_KEY_ID` | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key |
| `MCP_SERVER_URL` | MCP server SSE URL e.g. `https://xxx.railway.app/sse` |
