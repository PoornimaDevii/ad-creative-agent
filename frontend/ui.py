"""
Streamlit UI components for the AdCP Creative Agent platform.
"""

import requests
import streamlit as st

CSS = """
<style>
/* Page background */
[data-testid="stAppViewContainer"] {
    background: #0f0f1a;
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stSidebar"] {
    background: #0d0d1a;
    border-right: 1px solid #2a2a4a;
}

/* All text default */
*, p, span, div, label {
    color: #e0e0ff;
}

/* Title */
h1, h2, h3 { color: #e0e0ff !important; }

/* Chat messages */
[data-testid="stChatMessage"] {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: 12px !important;
    margin-bottom: 8px !important;
}
[data-testid="stChatMessage"] p,
[data-testid="stChatMessage"] span,
[data-testid="stChatMessage"] div {
    color: #e0e0ff !important;
}

/* Chat input box */
[data-testid="stChatInput"] textarea {
    background: #1a1a2e !important;
    border: 1px solid #3a3a6a !important;
    border-radius: 12px !important;
    color: #e0e0ff !important;
    caret-color: #e0e0ff !important;
}
[data-testid="stChatInput"] textarea::placeholder {
    color: #6666aa !important;
}
[data-testid="stChatInput"] textarea:focus {
    border-color: #7c6af7 !important;
    outline: none !important;
}

/* Markdown output */
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] span {
    color: #e0e0ff !important;
}

/* Captions */
[data-testid="stCaptionContainer"] p { color: #8888aa !important; }

/* Buttons */
[data-testid="stButton"] > button {
    background: linear-gradient(135deg, #7c6af7, #5a4fcf) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 500 !important;
}
[data-testid="stButton"] > button:hover { opacity: 0.85 !important; }
[data-testid="stButton"] > button p { color: #ffffff !important; }

/* Divider */
hr { border-color: rgba(255,255,255,0.08) !important; }

/* Expander */
[data-testid="stExpander"] summary p { color: #c0b8ff !important; }

/* Code blocks */
[data-testid="stCode"] { background: #1a1a2e !important; }
code { color: #a89cf7 !important; }

/* Sidebar text */
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label {
    color: #c0b8ff !important;
}
</style>
"""


def _render_preview_inline(url: str):
    """Fetch preview HTML server-side to bypass X-Frame-Options."""
    st.markdown(
        f'<a href="{url}" target="_blank" style="color:#7c6af7;font-size:0.8rem;">↗ Open in new tab</a>',
        unsafe_allow_html=True,
    )
    try:
        r = requests.get(url, timeout=8)
        if r.status_code == 200:
            st.components.v1.html(r.text, height=520, scrolling=True)
        else:
            st.warning(f"Preview returned status {r.status_code}")
    except Exception as e:
        st.warning(f"Could not load preview: {e}")


def render_page_config():
    st.set_page_config(
        page_title="AdCP Creative Agent",
        page_icon="🎨",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def render_header():
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(
        """
        <div style="padding: 1.5rem 0 0.5rem 0;">
            <h1 style="margin:0; font-size:2rem;">🎨 AdCP Creative Agent</h1>
            <p style="margin:0; color:#6666aa; font-size:0.9rem;">Powered by Adzymic &times; AWS Bedrock &times; MCP</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.divider()




def render_format_card(fmt: dict):
    """Render a single format as a card."""
    name = fmt.get("name", "Unknown")
    fmt_type = fmt.get("type", "display")
    dco = fmt.get("dco_available", False)
    assets = fmt.get("assets", [])
    renders = fmt.get("renders", [])
    preview_urls = fmt.get("preview_urls", [])
    fmt_id = fmt.get("format_id", {})

    type_badges = {
        "display": ("#3b82f6", "Display"),
        "video": ("#ef4444", "Video"),
        "social": ("#22c55e", "Social"),
        "audio": ("#eab308", "Audio"),
    }
    badge_color, badge_label = type_badges.get(fmt_type, ("#6b7280", fmt_type.capitalize()))

    with st.container(border=True):
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(
                f'<span style="font-weight:600;font-size:1rem;color:#e0e0ff">{name}</span> '
                f'<span style="background:{badge_color}22;color:{badge_color};border:1px solid {badge_color}44;'
                f'border-radius:4px;padding:1px 7px;font-size:0.72rem;font-weight:500;">{badge_label}</span>',
                unsafe_allow_html=True,
            )
            st.caption(f"`{fmt_id.get('id', '')}`")
        with col2:
            if dco:
                st.markdown(
                    '<span style="background:#16a34a22;color:#4ade80;border:1px solid #16a34a44;'
                    'border-radius:4px;padding:2px 8px;font-size:0.72rem;font-weight:500;">DCO ✓</span>',
                    unsafe_allow_html=True,
                )

        sizes = [
            f"{r['dimensions']['width']}×{r['dimensions']['height']}"
            for r in renders if r.get("dimensions")
        ]
        if sizes:
            st.markdown(
                ' '.join(f'<code style="background:rgba(124,106,247,0.15);color:#a89cf7;border-radius:4px;padding:1px 5px;font-size:0.75rem">{s}</code>' for s in sizes[:4]),
                unsafe_allow_html=True,
            )

        required = [a["asset_id"] for a in assets if a.get("required")]
        optional = [a["asset_id"] for a in assets if not a.get("required")]
        if required:
            st.caption("✅ Required: " + ", ".join(required))
        if optional:
            st.caption("➕ Optional: " + ", ".join(optional))

        if preview_urls:
            with st.expander("👁 Preview", expanded=False):
                for url in preview_urls:
                    _render_preview_inline(url)




def render_chat_interface():
    """Render the chat input and message history."""
    st.markdown(
        '<p style="font-size:1.1rem;font-weight:600;color:#c0b8ff;margin-bottom:0.5rem">💬 Creative Agent</p>',
        unsafe_allow_html=True,
    )

    if "messages" not in st.session_state:
        st.session_state.messages = []

    if not st.session_state.messages:
        st.markdown(
            '<div style="text-align:center;padding:3rem 1rem;color:#4a4a6a">'  
            '<div style="font-size:2.5rem;margin-bottom:0.5rem">🎨</div>'
            '<p style="font-size:1rem;color:#6666aa">Ask me about creative ad formats, request previews, or explore what\'s available.</p>'
            '</div>',
            unsafe_allow_html=True,
        )

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("tool_calls"):
                with st.expander("🔧 Tools used"):
                    for tc in msg["tool_calls"]:
                        st.code(f"{tc['name']}\n{tc['input']}", language="json")
            if msg.get("preview_urls"):
                st.divider()
                st.caption(f"👁 {len(msg['preview_urls'])} preview(s)")
                urls = msg["preview_urls"]
                if len(urls) > 1:
                    tabs = st.tabs([p["name"] for p in urls])
                    for tab, p in zip(tabs, urls):
                        with tab:
                            _render_preview_inline(p["url"])
                else:
                    _render_preview_inline(urls[0]["url"])

    return st.chat_input("💬 Ask about formats, e.g. 'Show me the Product Carousel'")


def render_tool_call_indicator(tool_calls: list):
    """Show which tools were called."""
    if tool_calls:
        names = [tc["name"] for tc in tool_calls]
        st.caption(f"🔧 Used: {', '.join(names)}")


def render_error(message: str):
    st.error(f"❌ {message}")


def render_server_status(connected: bool, url: str):
    if connected:
        st.sidebar.success(f"🟢 MCP Server connected\n`{url}`")
    else:
        st.sidebar.error(f"🔴 MCP Server not reachable\n`{url}`")
