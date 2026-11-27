"""Self-contained loader for the Prism Deck pywebview frontend and floating overlay."""

from __future__ import annotations

from functools import lru_cache

from ..paths import webui_dir


@lru_cache(maxsize=1)
def load_webui_html() -> str:
    """Assemble index.html with inlined CSS and JS so WebView2 runs offline with zero latency."""
    base = webui_dir()
    html = (base / "index.html").read_text(encoding="utf-8")
    css = (base / "style.css").read_text(encoding="utf-8")
    js = (base / "app.js").read_text(encoding="utf-8")
    return html.replace("/*__PRISM_CSS__*/", css).replace("/*__PRISM_JS__*/", js)


@lru_cache(maxsize=1)
def load_floating_html() -> str:
    """Load the self-contained transparent floating overlay HTML."""
    base = webui_dir()
    return (base / "floating.html").read_text(encoding="utf-8")
