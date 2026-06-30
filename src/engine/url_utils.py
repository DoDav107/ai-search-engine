"""Single source of truth for normalising a user-typed site URL before crawling.

Used by BOTH dashboards (Streamlit directly; Next.js via the ``/api/normalize-url`` route
and the audit-config writer) and the pipeline crawl entry, so the behaviour can never drift
between surfaces. Accepts loose input ("nandos.com.au", "www.x.com/menu",
"https://x.com/?gclid=…#frag") and returns one clean, crawlable absolute URL — or raises
``ValueError`` with a clear message for input that isn't a usable http(s) site.

CLI (used by the Next.js preview route):
    python -m src.engine.url_utils "nandos.com.au"   # -> {"url": "https://nandos.com.au/"}
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Known tracking/click-id query keys to strip (plus the whole utm_* family, handled below).
_TRACKING_KEYS = {
    "gad_source", "gad_campaignid", "gbraid", "wbraid", "gclid", "gclsrc", "dclid",
    "fbclid", "msclkid", "yclid", "mc_eid", "mc_cid", "_hsenc", "_hsmi", "igshid",
    "scid", "twclid", "ttclid",
}

_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")
_HOSTPORT_RE = re.compile(r"^[a-zA-Z0-9.\-]+:\d+(/|$)")


def _is_tracking_param(key: str) -> bool:
    k = key.lower()
    return k in _TRACKING_KEYS or k.startswith("utm_")


def normalise_site_url(raw: str) -> str:
    """Normalise loose user input into one clean crawlable absolute URL.

    Rules: trim; add https:// when no scheme; lowercase scheme+host only (preserve path
    case); strip known tracking params + utm_*; drop the fragment; collapse a bare host to
    "/"; reject non-http(s) schemes and hosts without a dot or with whitespace.
    """
    s = (raw or "").strip()
    if not s:
        raise ValueError("Enter a website URL or domain, e.g. nandos.com.au")

    # Scheme handling — reject non-http(s); add https:// when there's no scheme.
    if "://" in s:
        scheme = s.split("://", 1)[0].lower()
        if scheme not in ("http", "https"):
            raise ValueError(f"Unsupported URL scheme '{scheme}:'. Use http(s) or a plain domain.")
    elif _SCHEME_RE.match(s) and not _HOSTPORT_RE.match(s):
        # e.g. "javascript:alert(1)" — a scheme with no //, and not a bare host:port.
        bad = s.split(":", 1)[0]
        raise ValueError(f"Unsupported URL scheme '{bad}:'. Use http(s) or a plain domain.")
    else:
        s = "https://" + s

    parts = urlsplit(s)
    host = (parts.hostname or "").strip()
    if not host or "." not in host or any(ch.isspace() for ch in parts.netloc):
        raise ValueError("Enter a valid domain, e.g. nandos.com.au")

    # Lowercase scheme + host only (paths/queries can be case-sensitive). Preserve port.
    netloc = host.lower()
    if parts.port:
        netloc = f"{netloc}:{parts.port}"

    # Strip tracking junk; keep any genuinely meaningful params.
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking_param(k)]
    query = urlencode(kept)

    # Collapse a bare host to "/"; otherwise keep the path exactly as given.
    path = parts.path or "/"

    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))  # fragment dropped


def main() -> None:
    import json
    import sys

    raw = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read()
    try:
        print(json.dumps({"url": normalise_site_url(raw)}))
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}))


if __name__ == "__main__":
    main()
