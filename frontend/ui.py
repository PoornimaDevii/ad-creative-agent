"""
frontend/ui.py — Streamlit UI components for the Creatives Explorer Agent.

Responsibilities:
  - Page config, CSS injection, and sidebar rendering
  - Chat interface: message history, input, suggestion chips
  - Format cards: display format metadata in a structured card layout
  - Preview rendering: fetches HTML server-side to bypass X-Frame-Options,
    injects a <base> tag so relative assets resolve against the origin
  - Tool call indicator: shows which MCP tools were used per response
"""

import requests
import streamlit as st

# ====================== Global CSS ======================
# Injected once via render_header(). Uses Streamlit data-testid selectors
# to override default styles without breaking component functionality.
# Expander icons (arrows_down / arrow_right Material Symbols) are hidden
# via display:none on svg/toggle elements and replaced with CSS ▼/▲ pseudo-elements.

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap');

* { font-family: 'Inter', sans-serif !important; }

/* ── Background ── */
[data-testid="stAppViewContainer"] { background: #fdf8f0; }
[data-testid="stHeader"]           { background: transparent; }
[data-testid="stMain"]             { background: #fdf8f0; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #f5ede0;
    border-right: 1px solid #e8d9c5;
}
[data-testid="stSidebar"] * { color: #111 !important; }

/* ── Global text ── */
*, p, span, div, label { color: #111; }
h1, h2, h3             { color: #000 !important; font-weight: 600 !important; }

/* ── Chat messages ── */
[data-testid="stChatMessage"] {
    background: transparent !important;
    border: none !important;
    border-radius: 0 !important;
    padding: 0.5rem 0 !important;
    margin-bottom: 0 !important;
    display: flex !important;
    flex-direction: row !important;
}
[data-testid="stChatMessage"] p,
[data-testid="stChatMessage"] span,
[data-testid="stChatMessage"] div { color: #111 !important; }

/* User message — right-aligned bubble */
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
    flex-direction: row-reverse !important;
}
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="stChatMessageContent"] {
    background: #e0e0e0 !important;
    border-radius: 18px 18px 4px 18px !important;
    padding: 0.6rem 1rem !important;
    max-width: 75% !important;
    margin-left: auto !important;
}

/* Assistant message — left-aligned, no background */
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) [data-testid="stChatMessageContent"] {
    background: transparent !important;
    border-radius: 18px 18px 18px 4px !important;
    padding: 0.6rem 0 !important;
    max-width: 85% !important;
}

/* ── Chat input ── */
[data-testid="stChatInput"] {
    background: #fffdf7 !important;
    border: 1px solid #e8d9c5 !important;
    border-radius: 16px !important;
}
[data-testid="stChatInput"] textarea {
    background: #fffdf7 !important;
    border: none !important;
    color: #111 !important;
    caret-color: #111 !important;
    font-size: 0.95rem !important;
    -webkit-text-fill-color: #111 !important; /* fixes invisible text in some browsers */
}
[data-testid="stChatInput"] textarea::placeholder { color: #999 !important; }
[data-testid="stChatInput"] button { color: #22c55e !important; }
[data-testid="stChatInput"] button svg { fill: #22c55e !important; }

/* ── Markdown ── */
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] span {
    color: #111 !important;
    line-height: 1.7 !important;
}

/* ── Buttons ── */
[data-testid="stButton"] > button {
    background: #ffffff !important;
    color: #111 !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 500 !important;
    padding: 0.4rem 1rem !important;
}
[data-testid="stButton"] > button:hover { background: #e5e5e5 !important; }

/* ── Divider ── */
hr { border-color: #e8d9c5 !important; margin: 0.75rem 0 !important; }

/* ── Expander ── */
[data-testid="stExpander"] {
    background: #f5ede0 !important;
    border: 1px solid #e8d9c5 !important;
    border-radius: 10px !important;
    margin: 0.5rem 0 !important;
}
[data-testid="stExpander"] summary {
    list-style: none !important;
    position: relative;
    padding-right: 30px !important;
}
/* Hide Streamlit's default Material Symbols icon (renders as "arrows_down" text when font missing) */
[data-testid="stExpander"] summary::-webkit-details-marker,
[data-testid="stExpander"] summary svg,
[data-testid="stExpander"] summary [data-testid="stExpanderToggleIcon"],
[data-testid="stExpander"] summary > div > span:not([class*="Label"]) {
    display: none !important;
    visibility: hidden !important;
    font-size: 0 !important;
    width: 0 !important;
    height: 0 !important;
    overflow: hidden !important;
}
/* Replace with clean CSS chevron via pseudo-element */
[data-testid="stExpander"] summary:after {
    content: "▼";
    position: absolute;
    right: 12px;
    top: 50%;
    transform: translateY(-50%);
    font-size: 0.78rem;
    color: #888;
    transition: all 0.2s ease;
    font-weight: 400;
}
[data-testid="stExpander"][open] summary:after {
    content: "▲";
}
[data-testid="stExpander"] summary p {
    color: #555 !important;
    font-size: 0.84rem !important;
    font-weight: 500 !important;
    margin: 0 !important;
}
[data-testid="stExpander"] details > div {
    padding: 0.75rem 0 0.25rem 0 !important;
}

/* ── Code ── */
code {
    background: #e0e0e0 !important;
    color: #059669 !important;
    border-radius: 4px !important;
    padding: 1px 5px !important;
    font-size: 0.82rem !important;
}

/* ── Containers / cards ── */
[data-testid="stVerticalBlockBorderWrapper"] {
    background: #fffdf7 !important;
    border: 1px solid #e8d9c5 !important;
    border-radius: 12px !important;
}

/* ── Tabs ── */
[data-testid="stTabs"] [role="tab"] {
    color: #888 !important;
    font-size: 0.85rem !important;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: #111 !important;
    border-bottom: 2px solid #111 !important;
}

/* ── Scrollbar ── */
::-webkit-scrollbar       { width: 6px; }
::-webkit-scrollbar-track { background: #fdf8f0; }
::-webkit-scrollbar-thumb { background: #d4b896; border-radius: 3px; }
</style>
"""

# ====================== Sidebar CSS ======================
# Separate from main CSS to allow sidebar-specific class definitions
# (.sidebar-logo, .sidebar-section, .status-dot) without polluting global scope.

SIDEBAR_CSS = """
<style>
.sidebar-logo {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0.5rem 0 1.5rem 0;
    border-bottom: 1px solid #e8d9c5;
    margin-bottom: 1.5rem;
}
.sidebar-logo span {
    font-size: 1.1rem;
    font-weight: 600;
    color: #111 !important;
}
.sidebar-section {
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    color: #999 !important;
    text-transform: uppercase;
    margin-bottom: 0.5rem;
}
.status-dot {
    display: inline-block;
    width: 7px; height: 7px;
    border-radius: 50%;
    margin-right: 6px;
}
</style>
"""


def _render_preview_inline(url: str):
    """
    Render an ad creative preview inline within the Streamlit app.

    Strategy: fetch HTML server-side to bypass X-Frame-Options: SAMEORIGIN
    restrictions set by enzymic.co. Injects a <base> tag pointing to the
    origin so relative asset paths (JS, CSS, images) resolve correctly.
    Falls back to a warning if the fetch fails or returns a non-200 status.

    Args:
        url: Preview URL from the MCP server (may be http:// — upgraded to https://)
    """
    from urllib.parse import urlparse

    # Upgrade http to https — required for mixed-content policy in modern browsers
    https_url = url.replace("http://", "https://") if url.startswith("http://") else url
    parsed = urlparse(https_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    # Always show a direct link as fallback in case the embedded preview fails
    st.markdown(
        f'<a href="{https_url}" target="_blank" '
        f'style="color:#888;font-size:0.78rem;text-decoration:none;">Open preview in new tab ↗</a>',
        unsafe_allow_html=True,
    )

    try:
        # Fetch HTML server-side — bypasses X-Frame-Options which blocks iframes
        # Disable SSL verification for demo.enzymic.co which has an expired certificate
        verify_ssl = "demo.enzymic.co" not in https_url
        r = requests.get(https_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"}, verify=verify_ssl)
        if r.status_code == 200:
            # Inject <base> so relative paths resolve against the preview origin
            html = r.text.replace("<head>", f'<head><base href="{base_url}">', 1)
            st.components.v1.html(html, height=520, scrolling=True)
        else:
            # Non-200 status — display warning, do not crash
            st.warning("Preview unavailable. Try opening it in a new tab.")
    except Exception:
        # Network error or timeout — display warning, do not crash
        st.warning("Could not load preview. Try opening it in a new tab.")


def render_page_config():
    """Set Streamlit page title, icon, layout, and sidebar state. Must be called first."""
    st.set_page_config(
        page_title="Creatives Explorer Agent",
        page_icon="🔍",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def render_header():
    """Inject global CSS into the page. Must be called after render_page_config()."""
    st.markdown(CSS, unsafe_allow_html=True)


def render_server_status(connected: bool, url: str):
    """
    Render the sidebar with logo, MCP server connection status, and capabilities list.

    Shows a green dot when connected, red when offline.
    The sidebar CSS is injected here since it's only needed when the sidebar renders.

    Args:
        connected: Whether the MCP server health check passed
        url:       The MCP server SSE URL shown under the status
    """
    # Inject sidebar-specific CSS classes
    st.sidebar.markdown(SIDEBAR_CSS, unsafe_allow_html=True)

    # App logo / title
    st.sidebar.markdown(
        '<div class="sidebar-logo">'
        '<span style="font-size:1.1rem;font-weight:600;color:#111">Creatives Explorer Agent</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.sidebar.markdown('<div class="sidebar-section">Connection</div>', unsafe_allow_html=True)

    # Status dot colour reflects live connection state
    dot_color = "#22c55e" if connected else "#ef4444"
    status_text = "MCP Server connected" if connected else "MCP Server offline"
    st.sidebar.markdown(
        f'<p style="font-size:0.82rem;color:#444;margin:0;">'
        f'<span class="status-dot" style="background:{dot_color}"></span>{status_text}</p>'
        f'<p style="font-size:0.72rem;color:#999;margin:2px 0 0 13px;">{url}</p>',
        unsafe_allow_html=True,
    )

    st.sidebar.markdown("<br>", unsafe_allow_html=True)
    st.sidebar.markdown('<div class="sidebar-section">Capabilities</div>', unsafe_allow_html=True)

    # Static capability list — informational only
    for cap in ["Browse creative formats", "Preview ad creatives", "Filter by type & size", "DCO format discovery"]:
        st.sidebar.markdown(
            f'<p style="font-size:0.82rem;color:#888;margin:0.2rem 0;">{cap}</p>',
            unsafe_allow_html=True,
        )


def render_format_card(fmt: dict):
    """
    Render a single creative format as a styled card.

    Displays: format name, ID, type badge, DCO badge (if applicable),
    render sizes (up to 4), and required/optional asset IDs.

    Args:
        fmt: Format dict from the MCP server response (AdCP schema)
    """
    name     = fmt.get("name", "Unknown")
    fmt_type = fmt.get("type", "display")
    dco      = fmt.get("dco_available", False)
    assets   = fmt.get("assets", [])
    renders  = fmt.get("renders", [])
    fmt_id   = fmt.get("format_id", {})

    # Colour-code the type badge by format category
    type_colors = {
        "display": "#3b82f6",
        "video":   "#ef4444",
        "social":  "#22c55e",
        "audio":   "#f59e0b",
    }
    color = type_colors.get(fmt_type, "#6b7280")

    with st.container(border=True):
        col1, col2 = st.columns([4, 1])
        with col1:
            # Format name and machine-readable ID
            st.markdown(
                f'<p style="margin:0;font-size:0.95rem;font-weight:600;color:#111">{name}</p>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<code style="font-size:0.72rem;color:#555;background:transparent;padding:0">'
                f'{fmt_id.get("id", "")}</code>',
                unsafe_allow_html=True,
            )
        with col2:
            # Type badge — always shown; DCO badge — only if supported
            badges = (
                f'<span style="background:{color}18;color:{color};border:1px solid {color}33;'
                f'border-radius:5px;padding:2px 8px;font-size:0.7rem;font-weight:500">{fmt_type}</span>'
            )
            if dco:
                badges += (
                    ' <span style="background:#22c55e18;color:#22c55e;border:1px solid #22c55e33;'
                    'border-radius:5px;padding:2px 8px;font-size:0.7rem;font-weight:500">DCO</span>'
                )
            st.markdown(badges, unsafe_allow_html=True)

        # Render sizes — show up to 4 to avoid card overflow
        sizes = [
            f"{r['dimensions']['width']}×{r['dimensions']['height']}"
            for r in renders if r.get("dimensions")
        ]
        if sizes:
            size_html = " ".join(
                f'<code style="background:#e8e8e8;color:#555;border-radius:4px;'
                f'padding:1px 6px;font-size:0.72rem">{s}</code>'
                for s in sizes[:4]
            )
            st.markdown(size_html, unsafe_allow_html=True)

        # Asset requirements split into required and optional
        required = [a["asset_id"] for a in assets if a.get("required")]
        optional = [a["asset_id"] for a in assets if not a.get("required")]
        if required:
            st.caption("Required: " + ", ".join(required))
        if optional:
            st.caption("Optional: " + ", ".join(optional))


def render_chat_interface():
    """
    Render the full chat interface: empty state, message history, and input box.

    On first load (no messages), shows a welcome screen with suggestion chips.
    Each chip acts as a shortcut — clicking it returns the suggestion string
    which app.py treats as a user message.

    For each stored message, renders:
      - The message text
      - A "Tools used" expander (if tool_calls present)
      - Inline preview (if preview_urls present)

    Returns:
        str | None — the user's typed input, or a suggestion chip value,
                     or None if no input was submitted this render cycle.
    """
    # Initialise message store on first run
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Empty state — show welcome screen and suggestion chips
    if not st.session_state.messages:
        st.markdown(
            '<div style="display:flex;flex-direction:column;align-items:center;'
            'justify-content:center;padding:5rem 1rem 3rem;gap:0.5rem;">'
            '<p style="font-size:2rem;font-weight:700;color:#5a3e2b;margin:0;'
            'letter-spacing:-0.5px;">Creatives Explorer Agent</p>'
            '<p style="font-size:0.9rem;color:#a07850;margin:0;text-align:center">'
            'Browse formats, preview creatives, and explore what\'s available.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        suggestions = [
            "Show me carousel formats",
            "Preview Shake & Reveal",
            "List video formats",
            "What formats support DCO?",
        ]
        cols = st.columns(len(suggestions))
        for col, s in zip(cols, suggestions):
            with col:
                # Clicking a chip returns the suggestion as if the user typed it
                if st.button(s, use_container_width=True):
                    return s

    # Render committed message history
    for msg in st.session_state.messages:
        avatar = "👤" if msg["role"] == "user" else "⚙️"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

            # Show tool calls in a collapsible expander
            if msg.get("tool_calls"):
                with st.expander("Tools used"):
                    for tc in msg["tool_calls"]:
                        st.code(f"{tc['name']}\n{tc['input']}", language="json")

            # Render stored preview URLs (from previous turns)
            if msg.get("preview_urls"):
                st.divider()
                urls = msg["preview_urls"]
                if len(urls) > 1:
                    # Multiple previews shown as tabs
                    tabs = st.tabs([p["name"] for p in urls])
                    for tab, p in zip(tabs, urls):
                        with tab:
                            _render_preview_inline(p["url"])
                else:
                    _render_preview_inline(urls[0]["url"])

    return st.chat_input("Message Creatives Explorer Agent...")


def render_tool_call_indicator(tool_calls: list):
    """
    Render a subtle one-line indicator showing which MCP tools were used.

    Displayed below the assistant response text, above format cards/previews.

    Args:
        tool_calls: List of tool call dicts with "name" and "input" keys
    """
    if tool_calls:
        names = ", ".join(tc["name"] for tc in tool_calls)
        st.markdown(
            f'<p style="font-size:0.75rem;color:#555;margin:0.25rem 0">Used {names}</p>',
            unsafe_allow_html=True,
        )


def render_error(message: str):
    """
    Display a full-width error banner. Used for critical failures like
    MCP server unreachable at startup.

    Args:
        message: Error message string to display
    """
    st.error(message)
