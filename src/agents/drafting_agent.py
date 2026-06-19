"""Content-drafting agent: produces review-ready draft fixes for SEO recommendations.

Drafts are grounded ONLY in each page's real crawled content (title, headings,
visible text). The engine is instructed never to invent a brand, locations, or
services that do not appear on the page. Drafts are suggestions only — never
auto-applied.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from .geo_agent import EngineClient, MockEngineClient, get_engine_client
from ..engine.models import DraftedFix, Recommendation


# ---------------------------------------------------------------------------
# Crawled-content extraction (stdlib only) — used to ground every draft
# ---------------------------------------------------------------------------

class _PageContentParser(HTMLParser):
    """Pull the title, h1–h3 headings, and visible text out of raw HTML."""

    _SKIP_TAGS = {"script", "style", "noscript", "template"}
    _HEADING_TAGS = {"h1", "h2", "h3"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.headings: list[tuple[str, str]] = []
        self.text_parts: list[str] = []
        self._in_title = False
        self._skip_depth = 0
        self._cur_heading: str | None = None
        self._heading_buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self._HEADING_TAGS:
            self._cur_heading = tag
            self._heading_buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self._HEADING_TAGS and self._cur_heading == tag:
            text = " ".join(self._heading_buf).split()
            if text:
                self.headings.append((tag, " ".join(text)))
            self._cur_heading = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        if self._cur_heading is not None:
            self._heading_buf.append(data)
        stripped = data.strip()
        if stripped:
            self.text_parts.append(stripped)


def _empty_content() -> dict[str, Any]:
    return {"title": "", "headings": [], "text": ""}


def extract_page_content(html: str | None, max_text_chars: int = 1500) -> dict[str, Any]:
    """Extract title, headings, and a visible-text excerpt from raw HTML."""
    if not html:
        return _empty_content()
    parser = _PageContentParser()
    try:
        parser.feed(html)
    except Exception:
        # Malformed markup shouldn't crash drafting; use whatever was parsed.
        pass
    title = " ".join(" ".join(parser.title_parts).split())
    text = " ".join(" ".join(parser.text_parts).split())[:max_text_chars]
    return {"title": title, "headings": parser.headings, "text": text}


def _brand_matches_site(brand: str, base_url: str, contents: list[dict[str, Any]]) -> bool:
    """True if the configured brand appears in the crawled domain, titles, or text."""
    if not brand:
        return True
    norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
    needle = norm(brand)
    if not needle:
        return True
    if needle in norm(urlparse(base_url).netloc):
        return True
    for content in contents:
        headings = " ".join(text for _tag, text in content.get("headings", []))
        haystack = norm(content.get("title", "") + " " + headings + " " + content.get("text", ""))
        if needle in haystack:
            return True
    return False


# ---------------------------------------------------------------------------
# Mock client with canned, content-aware drafts for each SEO factor
# ---------------------------------------------------------------------------

class DraftingMockEngineClient(MockEngineClient):
    """MockEngineClient extended with generic draft templates for offline use.

    Templates reference {subject} (taken from the page's real title) rather than
    any hardcoded company name, so the mock never injects an unrelated brand.
    """

    # Templates use {subject}; filled at query time from the "Page title:" line.
    _DRAFT_TEMPLATES: dict[str, str] = {
        "title": (
            "[Mock] Suggested title (10–60 chars), based on the page topic:\n"
            "{subject} — [primary keyword + value proposition]"
        ),
        "meta_description": (
            "[Mock] Suggested meta description (50–160 chars):\n"
            "[One-sentence summary of {subject} drawn from the page — end with a call to action]"
        ),
        "h1": (
            "[Mock] Suggested H1 (under 70 chars):\n"
            "{subject} — [the page's main topic, keyword-relevant]"
        ),
        "canonical": (
            "[Mock] Add to the <head> of each affected page:\n"
            '<link rel="canonical" href="[this page\'s own absolute URL]">'
        ),
        "image_alt": (
            "[Mock] Example ALT text (replace brackets with what each image actually shows):\n"
            'alt="[Main subject] [what it shows] — relevant to {subject}"\n'
            'alt="[Screenshot or product] displaying [key detail]"\n'
            'alt=""  ← use empty alt for purely decorative images'
        ),
        "word_count": (
            "[Mock] Outline to expand the page past 300 words (sections only — fill from real content):\n"
            "1. [The problem or need this page addresses]\n"
            "2. [How {subject} addresses it]\n"
            "3. [Supporting detail or proof point]\n"
            "4. [Call to action]"
        ),
        "structured_data": (
            "[Mock] JSON-LD — paste inside <script type=\"application/ld+json\"> in the page <head>:\n"
            "{{\n"
            '  "@context": "https://schema.org",\n'
            '  "@type": "[Organization | WebPage | Article | Service]",\n'
            '  "name": "{subject}",\n'
            '  "url": "[this page\'s absolute URL]",\n'
            '  "description": "[one sentence from the page]"\n'
            "}}"
        ),
    }

    def query(self, prompt: str) -> str:
        """Return a content-aware draft template; fall back to the parent client."""
        subject = "[the page]"
        for line in prompt.splitlines():
            if line.startswith("Page title:"):
                title = line.split(":", 1)[1].strip()
                if title and not title.startswith("("):
                    subject = title
                break

        for factor, template in self._DRAFT_TEMPLATES.items():
            if f"Factor: {factor}" in prompt:
                return template.format(subject=subject)
        return super().query(prompt)


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def _get_draft_client(config: dict[str, Any]) -> EngineClient:
    """Return a drafting-aware client; uses DraftingMockEngineClient for mock."""
    if config.get("engine", "mock").lower() == "mock":
        return DraftingMockEngineClient()
    return get_engine_client(config)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_FACTOR_TASK: dict[str, str] = {
    "title": (
        "Write a rewritten page title: 10–60 characters, descriptive, keyword-rich. "
        "Return the title text only."
    ),
    "meta_description": (
        "Write a meta description: 50–160 characters, includes a call to action. "
        "Return the description text only."
    ),
    "h1": (
        "Write a single H1 heading for the page: concise, keyword-relevant, under 70 characters. "
        "Return the heading text only."
    ),
    "canonical": (
        "Write the corrected canonical <link> tag for each affected page, "
        "using the page's own URL as the canonical href."
    ),
    "image_alt": (
        "Write 2–3 example alt-text attributes for images on this page: descriptive, 5–15 words each. "
        "Return one example alt attribute per line."
    ),
    "word_count": (
        "Write a brief outline of 3–5 content sections to expand the page to at least 300 words. "
        "Include a suggested opening sentence per section."
    ),
    "structured_data": (
        "Write a complete JSON-LD structured data block appropriate for this page type, "
        "ready to paste inside a <script type='application/ld+json'> tag."
    ),
}


def build_drafting_prompt(rec: Recommendation, content: dict[str, Any] | None = None) -> str:
    """Build a factor-specific drafting prompt grounded in the page's real content.

    ``content`` is the extracted page content (title, headings, text) for the
    affected page. No brand or example company is injected — the engine is told
    to use only the supplied content and to invent nothing.
    """
    content = content or _empty_content()
    pages = "\n".join(f"  - {url}" for url in rec.affected_urls)
    task = _FACTOR_TASK.get(
        rec.factor,
        "Describe a concrete, copy-paste-ready fix for this SEO factor.",
    )

    title = content.get("title") or "(no title found on page)"
    headings = content.get("headings") or []
    headings_block = (
        "\n".join(f"  - {tag.upper()}: {text}" for tag, text in headings)
        if headings
        else "  (none found)"
    )
    page_text = content.get("text") or "(no visible text extracted)"

    return (
        "You are an SEO expert producing a review-ready draft fix.\n"
        "Ground your suggestion ONLY in the real page content below. Do NOT invent "
        "a brand name, company, locations, products, or services that do not appear "
        "in that content. If a detail is not present on the page, leave it out.\n\n"
        f"Factor: {rec.factor}\n"
        f"Severity: {rec.severity}\n"
        f"Scope: {rec.scope}\n"
        f"Issue: {rec.message}\n"
        f"Affected pages:\n{pages}\n\n"
        "--- REAL PAGE CONTENT (the only source of truth) ---\n"
        f"Page title: {title}\n"
        f"Headings:\n{headings_block}\n"
        f"Visible text (excerpt):\n{page_text}\n"
        "--- END PAGE CONTENT ---\n\n"
        f"Task: {task}\n\n"
        "Produce a concrete, copy-paste-ready suggestion grounded only in the content above. "
        "This draft is for human review only — it will not be applied automatically."
    )


# ---------------------------------------------------------------------------
# Fallbacks so every failing factor yields a non-empty, factor-appropriate draft
# ---------------------------------------------------------------------------

_FALLBACK_DRAFT: dict[str, str] = {
    "title": "[Title 10–60 chars — summarise the page's main topic from its content.]",
    "meta_description": "[Meta description 50–160 chars — one sentence from the page plus a call to action.]",
    "h1": "[Single H1 under 70 chars describing the page's main topic.]",
    "canonical": '<link rel="canonical" href="[this page\'s own absolute URL]">',
    "image_alt": (
        "Example ALT text (replace brackets with what each image actually shows):\n"
        'alt="[Main subject] [what it shows] — relevant context"\n'
        'alt="[Screenshot or product] displaying [key detail]"\n'
        'alt=""  ← use empty alt for purely decorative images'
    ),
    "word_count": (
        "Outline to expand the page past 300 words (fill each section from real page content):\n"
        "1. [Problem or need this page addresses]\n"
        "2. [How the page's offering addresses it]\n"
        "3. [Supporting detail or proof point]\n"
        "4. [Call to action]"
    ),
    "structured_data": (
        'JSON-LD — paste inside <script type="application/ld+json"> in the page <head>:\n'
        "{\n"
        '  "@context": "https://schema.org",\n'
        '  "@type": "[Organization | WebPage | Article | Service]",\n'
        '  "name": "[name exactly as it appears on the page]",\n'
        '  "url": "[this page\'s absolute URL]",\n'
        '  "description": "[one sentence from the page]"\n'
        "}"
    ),
}


def _fallback_for(factor: str) -> str:
    return _FALLBACK_DRAFT.get(
        factor, f"[No draft generated for factor '{factor}'. Review and address manually.]"
    )


# ---------------------------------------------------------------------------
# Main drafting function
# ---------------------------------------------------------------------------

def draft_fixes(
    recommendations: list[Recommendation],
    config: dict[str, Any],
    page_content: dict[str, dict[str, Any]] | None = None,
) -> list[DraftedFix]:
    """Draft a review-ready fix for each recommendation, grounded in page content.

    ``page_content`` maps a page URL to its extracted content (title, headings,
    text). Each draft is built from the content of its first affected page.
    Errors are captured gracefully and empty drafts fall back to a
    factor-appropriate template, so every factor yields a non-empty draft.
    """
    page_content = page_content or {}

    engine = str(config.get("engine", "mock")).lower()
    mode = str(config.get("openai", {}).get("mode", "live")).lower()
    # An explicit mock engine (e.g. the dashboard) always uses the offline client,
    # regardless of the openai mode default.
    if mode == "live" and engine != "mock":
        from src.clients import openai_client as _oc
        # Drafts (JSON-LD blocks, content outlines, multi-section rewrites) can be
        # long, so guarantee at least 1000 completion tokens for drafting and avoid
        # truncated fixes. The shared client reads this module global at call time,
        # so bumping it here only affects the drafting path.
        if _oc._MAX_TOKENS < 1000:
            _oc._MAX_TOKENS = 1000
        _get_draft = lambda prompt: _oc.client.chat(prompt)
    else:
        mock_client = _get_draft_client(config)
        _get_draft = lambda prompt: mock_client.query(prompt)

    fixes: list[DraftedFix] = []
    for rec in recommendations:
        content = page_content.get(rec.affected_urls[0]) if rec.affected_urls else None
        prompt = build_drafting_prompt(rec, content)
        try:
            draft = _get_draft(prompt)
        except Exception as exc:
            draft = f"[Draft error: {exc}]"
        if not draft or not draft.strip():
            draft = _fallback_for(rec.factor)
        fixes.append(DraftedFix(recommendation=rec, draft=draft, status="pending_review"))
    return fixes


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    from ..engine import scoring
    from ..engine.crawler import load_config as load_crawl_config
    from ..engine.models import SiteReport
    from ..engine.recommendations import _load_recommendation_weights, build_recommendations
    from .geo_agent import load_geo_config

    TOP_N = 5

    # Crawl once, then reuse the pages both to score and to ground the drafts.
    seo_config = scoring.load_config()
    weights = scoring.load_weights()
    crawled = scoring.crawl(seo_config)
    page_content = {page.url: extract_page_content(page.html) for page in crawled}

    reports = [scoring.extract_page(page, seo_config) for page in crawled]
    for report in reports:
        scoring.score_page(report, weights)
    site_report = SiteReport(
        site_name=seo_config.get("site", {}).get("name", "Unknown Site"),
        pages=reports,
        score=scoring.score_site(reports),
    )

    recommendations = build_recommendations(site_report, _load_recommendation_weights())

    geo_config = load_geo_config()
    brand = geo_config.get("brand", "")
    base_url = load_crawl_config().get("site", {}).get("base_url", "")

    # If the configured brand isn't found anywhere on the crawled site, the two
    # likely refer to different sites — stop rather than draft fixes for the wrong one.
    if not _brand_matches_site(brand, base_url, list(page_content.values())):
        print("⚠️  STOPPING — configured brand does not match the crawled site.\n")
        print(f"   geo_config brand : {brand!r}")
        print(f"   crawl base_url   : {base_url!r}")
        print("   The brand was not found in the crawled domain, page titles, or visible text.")
        print("   Fix `brand` in geo_config.yaml or `site.base_url` in crawl_config.yaml,")
        print("   then re-run. No drafts were produced.")
        return

    draft_config: dict[str, Any] = {
        "engine": geo_config.get("engine", "mock"),
        "openai": geo_config.get("openai", {}),
    }

    top = recommendations[:TOP_N]
    drafted = draft_fixes(top, draft_config, page_content=page_content)

    print(f"Drafted fixes for top {len(drafted)} recommendation(s) on {base_url}\n")
    print("=" * 60)
    for df in drafted:
        rec = df.recommendation
        print(f"\nFactor:   {rec.factor}")
        print(f"Severity: {rec.severity}  |  Scope: {rec.scope}  |  Priority: {rec.priority:.1f}")
        print(f"Pages:    {', '.join(rec.affected_urls)}")
        print(f"Issue:    {rec.message}")
        print(f"Status:   {df.status}")
        print("Draft fix:")
        for line in df.draft.splitlines():
            print(f"  {line}")
        print("-" * 60)


if __name__ == "__main__":
    main()
