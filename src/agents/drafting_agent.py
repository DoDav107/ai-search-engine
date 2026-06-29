"""Content-drafting agent: produces review-ready draft fixes for SEO recommendations.

Drafts are grounded ONLY in each page's real crawled content (title, headings,
visible text). The engine is instructed never to invent a brand, locations, or
services that do not appear on the page. Drafts are suggestions only — never
auto-applied.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from .geo_agent import EngineClient, MockEngineClient, get_engine_client
from ..engine.models import AdvisoryRecommendation, DraftedFix, Recommendation


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
        "crawl_access": (
            "[Mock] Crawl access fix:\n"
            "Allow legitimate SEO audit crawlers to receive the same public HTML that users and search engines "
            "should see, then rerun the audit against the canonical page URL."
        ),
        "audit_coverage": (
            "[Mock] Full audit coverage fix:\n"
            "Make the page's public HTML crawlable so title, meta description, H1, copy depth, image ALT, "
            "canonical, and structured data checks can run on the real page."
        ),
        "https_enabled": (
            "[Mock] HTTPS fix:\n"
            "Redirect the audited URL to its HTTPS canonical version and update internal links, sitemap URLs, "
            "canonicals, and redirects to use HTTPS consistently."
        ),
        "domain_brand_signal": (
            "[Mock] Brand/domain signal fix:\n"
            "If the domain does not contain the brand, reinforce the brand in crawlable title tags, schema, "
            "H1 copy, organization markup, and internal linking."
        ),
        "canonical_url_shape": (
            "[Mock] Canonical URL fix:\n"
            "Audit the clean canonical URL without tracking query strings or fragments, and publish a matching "
            "<link rel=\"canonical\"> tag in the page head."
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
    "crawl_access": (
        "Describe the crawler/access issue and provide concrete checks for robots rules, CDN bot protection, "
        "firewall allowlists, canonical URL choice, and public HTML accessibility."
    ),
    "audit_coverage": (
        "Explain that the audit is in fallback mode and list the page HTML checks that require crawlable HTML."
    ),
    "https_enabled": (
        "Provide HTTPS remediation steps covering redirects, canonicals, sitemap URLs, and internal links."
    ),
    "domain_brand_signal": (
        "Provide brand/domain alignment recommendations for title tags, schema, H1 copy, and visible brand signals."
    ),
    "canonical_url_shape": (
        "Provide canonical URL cleanup steps covering query strings, fragments, redirects, and canonical tags."
    ),
    "heading_structure": (
        "Propose an ordered H2/H3 outline for this page: 3–6 H2 section headings with optional H3 sub-points. "
        "Return one heading per line, prefixed H2:/H3:."
    ),
    "open_graph": (
        "Write the Open Graph meta tags for this page: og:title, og:description, og:image, og:type, og:url. "
        "Return the <meta> tags only."
    ),
    "twitter_card": (
        "Write the Twitter card meta tags (twitter:card=summary_large_image, twitter:title, twitter:description, "
        "twitter:image). Return the <meta> tags only."
    ),
    "viewport_meta": (
        "Provide the responsive viewport meta tag and where to place it in the <head>."
    ),
    "html_lang": (
        "State the correct <html lang> value for this page and the exact attribute to add."
    ),
    "robots_meta": (
        "Explain how to remove the noindex/nofollow directive (or confirm the page should stay excluded) and "
        "the corrected robots meta tag."
    ),
    "internal_links": (
        "Suggest 3–5 internal links to add on this page (anchor text + target topic) to related pages."
    ),
    "favicon": (
        "Provide the favicon <link> tags to add to the <head> (icon + apple-touch-icon)."
    ),
    "hreflang": (
        "Explain whether hreflang is needed for this site and, if so, the alternate <link rel=\"alternate\" "
        "hreflang> tags to add."
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
    "crawl_access": (
        "Crawl access checklist:\n"
        "1. Confirm the canonical URL returns public HTML with HTTP 200 to normal browser and crawler user agents.\n"
        "2. Review CDN/WAF bot rules so legitimate audit and search crawlers are not served a security block.\n"
        "3. Rerun the audit after the page is crawlable so title, meta, headings, links, images, and schema can be scored."
    ),
    "audit_coverage": (
        "Fallback audit checklist:\n"
        "1. Make the canonical page return public HTML to the audit crawler.\n"
        "2. Rerun the audit to unlock title, meta description, H1, image ALT, word count, and JSON-LD checks.\n"
        "3. Keep this fallback result as an access warning, not a replacement for a full on-page crawl."
    ),
    "https_enabled": (
        "HTTPS checklist:\n"
        "1. Serve the canonical URL over HTTPS.\n"
        "2. 301 redirect HTTP to HTTPS.\n"
        "3. Update sitemap, internal links, canonical tags, and hreflang URLs to HTTPS."
    ),
    "domain_brand_signal": (
        "Brand signal checklist:\n"
        "1. Put the exact brand name in the title tag and Organization/WebSite schema.\n"
        "2. Use a clear branded H1 or visible brand mention on the page.\n"
        "3. Link from brand-owned profiles and pages to this canonical URL."
    ),
    "canonical_url_shape": (
        "Canonical URL checklist:\n"
        "1. Audit the clean canonical URL without tracking query strings or fragments.\n"
        "2. 301 redirect duplicate variants to the canonical URL where appropriate.\n"
        "3. Add a matching <link rel=\"canonical\"> tag in the page head."
    ),
    "heading_structure": (
        "Suggested outline:\n"
        "H2: [Primary section topic]\n"
        "H3: [Supporting point]\n"
        "H2: [Second section topic]\n"
        "Keep one H1, then ordered H2s with H3s nested beneath them."
    ),
    "open_graph": (
        '<meta property="og:title" content="[page title]">\n'
        '<meta property="og:description" content="[50–160 char summary]">\n'
        '<meta property="og:image" content="[absolute image URL]">\n'
        '<meta property="og:type" content="website">\n'
        '<meta property="og:url" content="[this page\'s absolute URL]">'
    ),
    "twitter_card": (
        '<meta name="twitter:card" content="summary_large_image">\n'
        '<meta name="twitter:title" content="[page title]">\n'
        '<meta name="twitter:description" content="[50–160 char summary]">\n'
        '<meta name="twitter:image" content="[absolute image URL]">'
    ),
    "viewport_meta": '<meta name="viewport" content="width=device-width, initial-scale=1">',
    "html_lang": 'Set the document language on the root element, e.g. <html lang="en">.',
    "robots_meta": (
        "If the page should be discoverable, remove any noindex/nofollow and use:\n"
        '<meta name="robots" content="index, follow">'
    ),
    "internal_links": (
        "Add contextual internal links, e.g.:\n"
        '<a href="/related-page">Descriptive anchor text</a>\n'
        "Link to 3–5 related pages from the body copy and navigation."
    ),
    "favicon": (
        '<link rel="icon" href="/favicon.ico" sizes="any">\n'
        '<link rel="apple-touch-icon" href="/apple-touch-icon.png">'
    ),
    "hreflang": (
        "Only if the site serves multiple languages/regions:\n"
        '<link rel="alternate" hreflang="en" href="https://example.com/en/">\n'
        '<link rel="alternate" hreflang="x-default" href="https://example.com/">'
    ),
}


def _fallback_for(factor: str) -> str:
    return _FALLBACK_DRAFT.get(
        factor, f"[No draft generated for factor '{factor}'. Review and address manually.]"
    )


# ---------------------------------------------------------------------------
# Advisory (rich) SEO recommendations
# ---------------------------------------------------------------------------

_FACTOR_LABEL: dict[str, str] = {
    "title": "Page title",
    "meta_description": "Meta description",
    "h1": "H1 heading",
    "canonical": "Canonical tag",
    "image_alt": "Image ALT text",
    "word_count": "Content depth",
    "structured_data": "Structured data (JSON-LD)",
    "crawl_access": "Crawl access",
    "audit_coverage": "Audit coverage",
    "https_enabled": "HTTPS",
    "domain_brand_signal": "Brand/domain signal",
    "canonical_url_shape": "Canonical URL shape",
    "heading_structure": "Heading structure (H2/H3)",
    "open_graph": "Open Graph tags",
    "twitter_card": "Twitter card",
    "viewport_meta": "Mobile viewport",
    "html_lang": "Language attribute",
    "robots_meta": "Robots meta directive",
    "internal_links": "Internal links",
    "favicon": "Favicon",
    "hreflang": "hreflang annotations",
}

# Concrete SEO consequences per factor — used as grounded fallback for why_it_matters.
_FACTOR_WHY: dict[str, str] = {
    "title": (
        "The <title> is the clickable headline in search results and a primary relevance signal. "
        "A missing, duplicated, or badly-sized title weakens rankings and lowers SERP click-through rate."
    ),
    "meta_description": (
        "The meta description is the snippet shown under the title in search results. Without a compelling "
        "50–160 character summary, search engines auto-generate a weak snippet, reducing click-through rate."
    ),
    "h1": (
        "The H1 tells users and search engines the page's main topic. A missing or duplicated H1 blurs "
        "topical focus and hurts both accessibility and rankings."
    ),
    "canonical": (
        "Canonical tags consolidate ranking signals onto one URL. Missing or incorrect canonicals cause "
        "duplicate-content dilution and unpredictable indexing."
    ),
    "image_alt": (
        "ALT text makes images understandable to screen readers and search engines. Missing ALT text fails "
        "WCAG accessibility and forfeits image-search visibility and on-page relevance signals."
    ),
    "word_count": (
        "Thin content gives search engines little to rank and rarely satisfies search intent, limiting the "
        "page's visibility for its target terms."
    ),
    "structured_data": (
        "Structured data (JSON-LD) helps engines understand the page's entities and can unlock rich results. "
        "Without it the page misses enhanced SERP features and entity clarity."
    ),
    "crawl_access": (
        "Search engines and SEO tools need crawlable public HTML to inspect metadata, headings, links, images, "
        "schema, and content. A blocked response prevents normal on-page SEO auditing and can indicate an "
        "indexing risk if search crawlers receive the same treatment."
    ),
    "audit_coverage": (
        "A fallback audit can catch URL and brand hygiene issues, but it cannot verify the actual on-page SEO "
        "signals that search engines use, including title tags, meta descriptions, headings, copy depth, "
        "image ALT text, and structured data."
    ),
    "https_enabled": (
        "HTTPS is a baseline trust and security requirement. Non-HTTPS canonical URLs can cause browser "
        "warnings, redirect waste, analytics fragmentation, and weaker search eligibility."
    ),
    "domain_brand_signal": (
        "When the brand is not obvious from the domain, search engines rely more heavily on crawlable metadata, "
        "schema, headings, and visible copy to connect the page to the right entity."
    ),
    "canonical_url_shape": (
        "Clean canonical URLs consolidate ranking signals and reduce duplicate variants. Query strings and "
        "fragments can fragment crawl signals if they are audited or indexed as primary URLs."
    ),
    "heading_structure": (
        "H2/H3 sub-headings break content into scannable, topically-labelled sections. Flat or out-of-order "
        "headings make it harder for users, screen readers, and AI engines to parse the page's structure."
    ),
    "open_graph": (
        "Open Graph tags control how the page appears when shared and are increasingly used by AI assistants "
        "for titles, summaries, and images. Missing tags yield poor, auto-guessed previews."
    ),
    "twitter_card": (
        "Twitter card tags give a controlled title/description/image when links are shared on X, improving "
        "click-through from social. Without them the preview is unpredictable."
    ),
    "viewport_meta": (
        "The viewport meta tag is required for responsive rendering. Without width=device-width the page can "
        "display zoomed-out on phones, hurting mobile usability and mobile-first ranking."
    ),
    "html_lang": (
        "The <html lang> attribute tells browsers, assistive tech, and search engines the page language, "
        "aiding correct pronunciation, translation prompts, and locale targeting."
    ),
    "robots_meta": (
        "A noindex/nofollow robots directive removes the page from search and AI indexes entirely. Left on a "
        "page that should rank, it makes all other SEO work moot."
    ),
    "internal_links": (
        "Internal links distribute authority and help crawlers (and AI) discover and relate pages. Pages with "
        "few internal links are crawled less and rank weaker for their topics."
    ),
    "favicon": (
        "A favicon is a small brand-trust signal shown in browser tabs, bookmarks, and some search results. "
        "Its absence looks unpolished but has minimal direct ranking impact."
    ),
    "hreflang": (
        "hreflang annotations map equivalent pages across languages/regions so the right version ranks per "
        "locale. They matter only for genuinely multi-locale sites."
    ),
}


def _seo_priority(severity: str, n_pages: int) -> str:
    """Priority from impact (severity) and reach (page count)."""
    if severity == "fail":
        return "High"
    return "Medium" if n_pages > 1 else "Low"


def _scope_str(urls: list[str]) -> str:
    """Human-readable scope listing the affected pages."""
    n = len(urls)
    if n == 0:
        return "No pages"
    shown = ", ".join(urls[:3])
    if n > 3:
        shown += f", +{n - 3} more"
    return f"{n} page{'s' if n != 1 else ''}: {shown}"


def parse_json_object(text: str | None) -> dict[str, Any] | None:
    """Best-effort parse of a JSON object from a model response (tolerates code fences)."""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except Exception:
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end > start:
            try:
                obj = json.loads(s[start : end + 1])
                return obj if isinstance(obj, dict) else None
            except Exception:
                return None
    return None


def build_seo_advisory_prompt(rec: Recommendation, content: dict[str, Any] | None = None) -> str:
    """Build a JSON-returning advisory prompt grounded in the page's real content."""
    content = content or _empty_content()
    title = content.get("title") or "(no title found on page)"
    headings = content.get("headings") or []
    headings_block = (
        "\n".join(f"  - {tag.upper()}: {text}" for tag, text in headings)
        if headings
        else "  (none found)"
    )
    page_text = content.get("text") or "(no visible text extracted)"
    pages = "\n".join(f"  - {url}" for url in rec.affected_urls)
    task = _FACTOR_TASK.get(rec.factor, "Provide a concrete, copy-paste-ready fix for this SEO factor.")

    return (
        "You are a senior SEO consultant. Using ONLY the real page content below, return a single JSON "
        "object (no markdown, no commentary) with exactly these keys:\n"
        '  "issue": what is specifically wrong on this page for this factor, referencing the real content;\n'
        '  "why_it_matters": the concrete SEO consequence (crawlability, SERP click-through, rankings, or '
        "accessibility) — specific to this factor, not generic filler;\n"
        '  "recommendation": the concrete, actionable fix;\n'
        '  "draft": ready-to-apply content for this factor (title / meta description / H1 / ALT text / '
        'JSON-LD), grounded only in the page content; use "" if not applicable.\n'
        "Do NOT invent a brand, company, products, locations, or services that are not present in the "
        "content. If a detail is not on the page, leave it out.\n\n"
        f"Factor: {rec.factor}\n"
        f"Severity: {rec.severity}\n"
        f"Affected pages:\n{pages}\n\n"
        "--- REAL PAGE CONTENT (the only source of truth) ---\n"
        f"Page title: {title}\n"
        f"Headings:\n{headings_block}\n"
        f"Visible text (excerpt):\n{page_text}\n"
        "--- END PAGE CONTENT ---\n\n"
        f"Guidance for the draft: {task}\n"
        "Return ONLY the JSON object."
    )


def build_seo_recommendations(
    recommendations: list[Recommendation],
    config: dict[str, Any],
    page_content: dict[str, dict[str, Any]] | None = None,
) -> list[AdvisoryRecommendation]:
    """Produce one rich AdvisoryRecommendation per failing/warning factor, grounded in page content."""
    page_content = page_content or {}

    engine = str(config.get("engine", "mock")).lower()
    mode = str(config.get("openai", {}).get("mode", "live")).lower()
    if mode == "live" and engine != "mock":
        from src.clients import openai_client as _oc
        if _oc._MAX_TOKENS < 1000:
            _oc._MAX_TOKENS = 1000
        _ask = lambda prompt: _oc.client.chat(prompt)
    else:
        mock_client = _get_draft_client(config)
        _ask = lambda prompt: mock_client.query(prompt)

    advisories: list[AdvisoryRecommendation] = []
    for rec in recommendations:
        content = page_content.get(rec.affected_urls[0]) if rec.affected_urls else None
        prompt = build_seo_advisory_prompt(rec, content)
        try:
            data = parse_json_object(_ask(prompt))
        except Exception:
            data = None
        data = data if isinstance(data, dict) else {}

        issue = str(data.get("issue") or "").strip() or rec.message
        why = str(data.get("why_it_matters") or "").strip() or _FACTOR_WHY.get(
            rec.factor, "Resolving this factor improves the page's search performance."
        )
        fix = str(data.get("recommendation") or "").strip() or _FACTOR_TASK.get(
            rec.factor, "Address this SEO factor."
        )
        draft = str(data.get("draft") or "").strip() or _fallback_for(rec.factor)

        advisories.append(
            AdvisoryRecommendation(
                area="SEO",
                title=_FACTOR_LABEL.get(rec.factor, rec.factor),
                priority=_seo_priority(rec.severity, len(rec.affected_urls)),
                scope=_scope_str(rec.affected_urls),
                issue=issue,
                why_it_matters=why,
                recommendation=fix,
                draft=draft,
            )
        )
    return advisories


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
